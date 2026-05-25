from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import LedgerEntry


@pytest.fixture()
def sqlite_session():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    try:
        with Session() as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)


def test_emit_action_event_appends_structured_audit_ledger_entry(sqlite_session):
    from ryan.telemetry.service import emit_action_event

    occurred_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)

    entry = emit_action_event(
        sqlite_session,
        domain="policy",
        event_name="expense_rejected",
        actor="policy-service",
        reference_type="policy_decision",
        reference_id="policy-123",
        metadata={"reason": "vendor_not_allowlisted"},
        timestamp=occurred_at,
    )

    persisted = sqlite_session.get(LedgerEntry, entry.id)
    assert persisted is not None
    assert persisted.type == "audit.policy.expense_rejected"
    assert persisted.amount is None
    assert persisted.currency is None
    assert persisted.actor == "policy-service"
    assert persisted.reference_type == "policy_decision"
    assert persisted.reference_id == "policy-123"
    assert persisted.timestamp == occurred_at
    assert persisted.metadata_ == {
        "telemetry_kind": "action",
        "domain": "policy",
        "event_name": "expense_rejected",
        "reason": "vendor_not_allowlisted",
    }


@pytest.mark.parametrize(
    ("alert_type", "reference_type", "reference_id", "metadata"),
    [
        (
            "budget_exhaustion",
            "wallet",
            "wallet-operating",
            {"wallet_type": "operating", "available_balance": "4.00"},
        ),
        (
            "invalid_payment_confirmation",
            "payment",
            "payment-123",
            {"provider": "sandbox", "provider_reference": "provider-123"},
        ),
        (
            "duplicate_event",
            "payment",
            "provider-event-123",
            {"idempotency_key": "idem-123", "scope": "payment_confirm"},
        ),
        (
            "frozen_spend_attempt",
            "wallet",
            "wallet-operating",
            {"wallet_type": "operating", "attempted_action": "expense_execution"},
        ),
        (
            "kill_switch_active",
            "kill_switch",
            "kill-switch-state-123",
            {"blocked_action": "wallet_transfer", "reason": "operator_stop"},
        ),
    ],
)
def test_emit_alert_appends_structured_alert_entries(
    sqlite_session,
    alert_type,
    reference_type,
    reference_id,
    metadata,
):
    from ryan.telemetry.service import emit_alert

    entry = emit_alert(
        sqlite_session,
        alert_type=alert_type,
        severity="critical",
        actor="system",
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata,
    )

    assert entry.type == f"alert.{alert_type}"
    assert entry.amount is None
    assert entry.currency is None
    assert entry.actor == "system"
    assert entry.reference_type == reference_type
    assert entry.reference_id == reference_id
    assert entry.metadata_ == {
        "telemetry_kind": "alert",
        "alert_type": alert_type,
        "severity": "critical",
        "requires_operator_review": True,
        **metadata,
    }


@pytest.mark.parametrize(
    ("helper_name", "expected_type", "reference_type", "reference_kw"),
    [
        (
            "emit_policy_event",
            "audit.policy.evaluated",
            "policy_decision",
            {"policy_decision_id": "policy-123"},
        ),
        (
            "emit_payment_event",
            "audit.payment.confirmed",
            "payment",
            {"payment_id": "payment-123"},
        ),
        (
            "emit_wallet_event",
            "audit.wallet.transferred",
            "wallet",
            {"wallet_id": "wallet-123"},
        ),
        (
            "emit_expense_event",
            "audit.expense.requested",
            "expense",
            {"expense_id": "expense-123"},
        ),
        (
            "emit_exception_event",
            "audit.exception.opened",
            "exception",
            {"exception_id": "exception-123"},
        ),
        (
            "emit_kill_switch_event",
            "audit.kill_switch.activated",
            "kill_switch",
            {"kill_switch_state_id": "kill-switch-123"},
        ),
        (
            "emit_report_event",
            "audit.report.generated",
            "report",
            {"report_id": "report-123"},
        ),
    ],
)
def test_domain_specific_helpers_emit_required_event_metadata(
    sqlite_session,
    helper_name,
    expected_type,
    reference_type,
    reference_kw,
):
    import ryan.telemetry.service as telemetry_service

    helper = getattr(telemetry_service, helper_name)
    entry = helper(
        sqlite_session,
        event_name=expected_type.rsplit(".", maxsplit=1)[-1],
        actor="domain-service",
        metadata={"correlation_id": "corr-123"},
        **reference_kw,
    )

    assert entry.type == expected_type
    assert entry.reference_type == reference_type
    assert entry.reference_id == next(iter(reference_kw.values()))
    assert entry.metadata_["telemetry_kind"] == "action"
    assert entry.metadata_["domain"] == expected_type.split(".")[1]
    assert entry.metadata_["event_name"] == expected_type.rsplit(".", maxsplit=1)[-1]
    assert entry.metadata_["correlation_id"] == "corr-123"


@pytest.mark.parametrize(
    ("helper_name", "expected_type"),
    [
        ("emit_freeze_event", "audit.wallet.freeze"),
        ("emit_unfreeze_event", "audit.wallet.unfreeze"),
    ],
)
def test_freeze_helpers_emit_fixed_wallet_control_event_names(
    sqlite_session,
    helper_name,
    expected_type,
):
    import ryan.telemetry.service as telemetry_service

    helper = getattr(telemetry_service, helper_name)
    entry = helper(
        sqlite_session,
        wallet_id="wallet-123",
        actor="operator:ops@example.com",
        metadata={"reason": "manual control"},
    )

    assert entry.type == expected_type
    assert entry.reference_type == "wallet"
    assert entry.reference_id == "wallet-123"
    assert entry.metadata_["telemetry_kind"] == "action"
    assert entry.metadata_["domain"] == "wallet"
    assert entry.metadata_["event_name"] == expected_type.rsplit(".", maxsplit=1)[-1]
    assert entry.metadata_["reason"] == "manual control"


def test_telemetry_helpers_flush_without_committing(sqlite_session):
    from ryan.telemetry.service import emit_payment_event

    entry = emit_payment_event(
        sqlite_session,
        event_name="created",
        payment_id="payment-123",
        actor="payments-service",
        metadata={},
    )

    assert entry.id is not None
    sqlite_session.rollback()

    assert sqlite_session.scalars(select(LedgerEntry)).all() == []
