import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.exceptions.service import (
    ExceptionRecordError,
    create_exception_record,
    list_exception_records,
    transition_exception_status,
)
from ryan.models import ExceptionRecord, LedgerEntry, PolicyDecision


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


def _policy_decision(session, *, decision="reject"):
    record = PolicyDecision(
        action_type="expense_execute",
        decision=decision,
        reason="vendor is not allowlisted",
        rule_results={"vendor_allowlist": {"passed": False}},
        request_reference_type="expense",
        request_reference_id="expense-001",
        actor="agent:ryan",
    )
    session.add(record)
    session.flush()
    return record


def test_create_exception_record_persists_and_emits_audit_event(sqlite_session):
    decision = _policy_decision(sqlite_session)

    exception = create_exception_record(
        sqlite_session,
        exception_type="policy_rejection",
        severity="high",
        reason="vendor is not allowlisted",
        reference_type="policy_decision",
        reference_id=decision.id,
        actor="system:policy",
        policy_decision_id=decision.id,
    )

    assert exception.status == "open"
    assert exception.policy_decision_id == decision.id
    persisted = sqlite_session.get(ExceptionRecord, exception.id)
    assert persisted is not None
    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reference_type == "exception",
            LedgerEntry.reference_id == exception.id,
            LedgerEntry.type == "audit.exception.created",
        )
    )
    assert audit_entry is not None
    assert audit_entry.actor == "system:policy"


def test_create_exception_record_rejects_unknown_type(sqlite_session):
    with pytest.raises(ExceptionRecordError):
        create_exception_record(
            sqlite_session,
            exception_type="unknown",
            severity="low",
            reason="not supported",
            reference_type="payment",
            reference_id="payment-001",
            actor="system:test",
        )


def test_list_exception_records_filters_visible_open_items(sqlite_session):
    first = create_exception_record(
        sqlite_session,
        exception_type="invalid_payment_confirmation",
        severity="high",
        reason="amount mismatch",
        reference_type="checkout_session",
        reference_id="checkout-001",
        actor="system:webhook",
    )
    second = create_exception_record(
        sqlite_session,
        exception_type="duplicate_event",
        severity="medium",
        reason="duplicate provider event",
        reference_type="payment",
        reference_id="payment-001",
        actor="system:webhook",
    )
    transition_exception_status(
        sqlite_session,
        exception_id=second.id,
        status="resolved",
        actor="operator:test",
        reason="duplicate confirmed harmless",
    )

    assert [record.id for record in list_exception_records(sqlite_session)] == [
        first.id
    ]
    assert {
        record.id for record in list_exception_records(sqlite_session, status=None)
    } == {first.id, second.id}


def test_transition_exception_status_records_resolution_audit(sqlite_session):
    exception = create_exception_record(
        sqlite_session,
        exception_type="budget_exhaustion",
        severity="high",
        reason="operating wallet below threshold",
        reference_type="wallet",
        reference_id="wallet-operating",
        actor="system:wallet",
    )

    transitioned = transition_exception_status(
        sqlite_session,
        exception_id=exception.id,
        status="in_review",
        actor="operator:test",
        reason="reviewing budget",
    )
    resolved = transition_exception_status(
        sqlite_session,
        exception_id=exception.id,
        status="resolved",
        actor="operator:test",
        reason="budget replenished",
    )

    assert transitioned.id == exception.id
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reference_type == "exception",
            LedgerEntry.reference_id == exception.id,
            LedgerEntry.type == "audit.exception.status_changed",
        )
    )
    assert audit_entry is not None
    assert audit_entry.metadata_["status"] == "in_review"
