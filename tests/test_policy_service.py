from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import ExpenseRequest, LedgerEntry, PolicyDecision, PolicyRule, Wallet
from ryan.policy.service import (
    PolicyEvaluationRequest,
    create_policy_rule,
    evaluate_policy,
    list_policy_rules,
)


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


def _monday_noon() -> datetime:
    return datetime(2026, 5, 25, 12, 0, tzinfo=UTC)


def _create_wallets(
    session,
    *,
    operating_balance: Decimal = Decimal("50.00"),
    revenue_balance: Decimal = Decimal("100.00"),
    operating_locked: bool = False,
):
    wallets = [
        Wallet(
            type="revenue",
            balance=revenue_balance,
            currency="USD",
            locked=False,
            limits={},
        ),
        Wallet(
            type="operating",
            balance=operating_balance,
            currency="USD",
            locked=operating_locked,
            limits={"reserve_minimum": "5.00", "currency": "USD"},
        ),
        Wallet(
            type="reserve",
            balance=Decimal("25.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "5.00", "currency": "USD"},
        ),
    ]
    session.add_all(wallets)
    session.flush()
    return {wallet.type: wallet for wallet in wallets}


def _create_required_rules(
    session,
    *,
    spend_threshold_configuration: dict | None = None,
    category_budget_configuration: dict | None = None,
    revenue_floor_configuration: dict | None = None,
    reserve_minimum_configuration: dict | None = None,
):
    create_policy_rule(
        session,
        rule_type="vendor_allowlist",
        configuration={
            "vendors": [
                {
                    "name": "sandbox-approved-vendor",
                    "categories": ["software"],
                    "status": "approved",
                }
            ]
        },
        actor="operator:test",
        priority=1,
    )
    create_policy_rule(
        session,
        rule_type="spend_threshold",
        configuration=spend_threshold_configuration
        or {"per_transaction_cap": "25.00", "currency": "USD"},
        actor="operator:test",
        priority=2,
    )
    create_policy_rule(
        session,
        rule_type="category_budget",
        configuration=category_budget_configuration
        or {
            "budgets": [
                {
                    "category": "software",
                    "limit": "100.00",
                    "currency": "USD",
                    "period": "monthly",
                }
            ]
        },
        actor="operator:test",
        priority=3,
    )
    create_policy_rule(
        session,
        rule_type="time_window",
        configuration={
            "windows": [
                {
                    "name": "weekday-business-hours",
                    "start_hour_utc": 9,
                    "end_hour_utc": 17,
                    "days": ["mon", "tue", "wed", "thu", "fri"],
                    "timezone": "UTC",
                }
            ]
        },
        actor="operator:test",
        priority=4,
    )
    create_policy_rule(
        session,
        rule_type="revenue_floor",
        configuration=revenue_floor_configuration
        or {"amount": "10.00", "currency": "USD"},
        actor="operator:test",
        priority=5,
    )
    create_policy_rule(
        session,
        rule_type="reserve_minimum",
        configuration=reserve_minimum_configuration
        or {"amount": "5.00", "currency": "USD"},
        actor="operator:test",
        priority=6,
    )


def _expense_request(
    *,
    vendor: str = "sandbox-approved-vendor",
    category: str = "software",
    amount: Decimal | None = Decimal("10.00"),
    currency: str | None = "USD",
    action_type: str = "expense_execute",
    reference_id: str = "expense-001",
    irreversible: bool = False,
) -> PolicyEvaluationRequest:
    return PolicyEvaluationRequest(
        action_type=action_type,
        vendor=vendor,
        category=category,
        amount=amount,
        currency=currency,
        actor="agent:ryan",
        request_reference_type="expense",
        request_reference_id=reference_id,
        source_wallet_type="operating",
        irreversible=irreversible,
    )


def _evaluate_default(session, **request_overrides):
    _create_wallets(session)
    _create_required_rules(session)
    return evaluate_policy(
        session,
        request=_expense_request(**request_overrides),
        timestamp=_monday_noon(),
    )


def test_policy_rule_helpers_create_and_list_active_rules(sqlite_session):
    active = create_policy_rule(
        sqlite_session,
        rule_type="vendor_allowlist",
        configuration={"vendors": [{"name": "vendor-a", "categories": ["software"]}]},
        actor="operator:test",
        priority=10,
    )
    create_policy_rule(
        sqlite_session,
        rule_type="vendor_allowlist",
        configuration={"vendors": [{"name": "vendor-b", "categories": ["ads"]}]},
        actor="operator:test",
        status="inactive",
        priority=20,
    )

    assert active.id is not None
    assert active.type == "vendor_allowlist"
    assert active.created_by_actor == "operator:test"
    assert [rule.id for rule in list_policy_rules(sqlite_session)] == [active.id]
    assert len(list_policy_rules(sqlite_session, active_only=False)) == 2


def test_allowlisted_vendor_under_cap_with_budget_and_active_window_approves(
    sqlite_session,
):
    decision = _evaluate_default(sqlite_session)

    assert decision.decision == "approve"
    assert "approved" in decision.reason
    assert decision.request_reference_id == "expense-001"
    assert decision.rule_results["vendor_allowlist"]["passed"] is True
    assert decision.rule_results["spend_threshold"]["passed"] is True
    assert decision.rule_results["category_budget"]["passed"] is True

    persisted = sqlite_session.get(PolicyDecision, decision.id)
    assert persisted is not None
    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(LedgerEntry.reference_id == decision.id)
    )
    assert audit_entry.type == "audit.policy.evaluated"


def test_unallowlisted_vendor_rejects_and_persists_reason(sqlite_session):
    decision = _evaluate_default(
        sqlite_session,
        vendor="unapproved-vendor",
        reference_id="expense-unapproved-vendor",
    )

    assert decision.decision == "reject"
    assert "vendor is not allowlisted" in decision.reason
    assert decision.rule_results["vendor_allowlist"]["passed"] is False

    persisted = sqlite_session.get(PolicyDecision, decision.id)
    assert persisted.reason == decision.reason


def test_amount_over_threshold_escalates_and_persists_decision(sqlite_session):
    decision = _evaluate_default(
        sqlite_session,
        amount=Decimal("30.00"),
        reference_id="expense-over-threshold",
    )

    assert decision.decision == "escalate"
    assert "exceeds autonomous spend threshold" in decision.reason
    assert decision.rule_results["spend_threshold"]["passed"] is False
    assert decision.rule_results["exception_escalation"]["decision"] == "escalate"
    assert sqlite_session.get(PolicyDecision, decision.id).decision == "escalate"


def test_category_budget_exceeded_rejects_fail_closed(sqlite_session):
    _create_wallets(sqlite_session, operating_balance=Decimal("150.00"))
    _create_required_rules(sqlite_session)
    sqlite_session.add(
        ExpenseRequest(
            vendor="sandbox-approved-vendor",
            category="software",
            amount=Decimal("95.00"),
            currency="USD",
            rationale="already approved spend",
            policy_status="approved",
            execution_status="executed",
            created_by_actor="agent:ryan",
        )
    )
    sqlite_session.flush()

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(
            amount=Decimal("10.00"),
            reference_id="expense-budget-exceeded",
        ),
        timestamp=_monday_noon(),
    )

    assert decision.decision == "reject"
    assert "category budget would be exceeded" in decision.reason
    assert decision.rule_results["category_budget"]["passed"] is False
    assert decision.rule_results["category_budget"]["decision"] == "reject"


def test_time_window_mismatch_rejects_fail_closed(sqlite_session):
    _create_wallets(sqlite_session)
    _create_required_rules(sqlite_session)

    # Sunday is outside the configured weekday window.
    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-after-hours"),
        timestamp=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
    )

    assert decision.decision == "reject"
    assert "outside active policy time window" in decision.reason
    assert decision.rule_results["time_window"]["passed"] is False


def test_time_window_evaluation_converts_aware_timestamp_to_utc(sqlite_session):
    _create_wallets(sqlite_session)
    _create_required_rules(sqlite_session)

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-non-utc-time"),
        # 12:00 at UTC+05:00 is 07:00 UTC, outside the 09-17 UTC window.
        timestamp=datetime(2026, 5, 25, 12, 0, tzinfo=timezone(timedelta(hours=5))),
    )

    assert decision.decision == "reject"
    assert "outside active policy time window" in decision.reason


def test_uncertain_spend_threshold_config_rejects_fail_closed(sqlite_session):
    _create_wallets(sqlite_session)
    _create_required_rules(
        sqlite_session,
        spend_threshold_configuration={"currency": "USD"},
    )

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-malformed-threshold"),
        timestamp=_monday_noon(),
    )

    assert decision.decision == "reject"
    assert "spend threshold rule is missing required currency or cap" in (
        decision.reason
    )
    assert decision.rule_results["spend_threshold"]["decision"] == "reject"


def test_malformed_numeric_policy_config_rejects_with_persisted_decision(
    sqlite_session,
):
    _create_wallets(sqlite_session)
    _create_required_rules(
        sqlite_session,
        spend_threshold_configuration={
            "per_transaction_cap": "NaN",
            "currency": "USD",
        },
    )

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-nan-threshold"),
        timestamp=_monday_noon(),
    )

    assert decision.decision == "reject"
    assert "spend threshold rule is missing required currency or cap" in (
        decision.reason
    )
    assert sqlite_session.get(PolicyDecision, decision.id) is not None


def test_revenue_floor_and_reserve_minimum_currency_mismatch_rejects(
    sqlite_session,
):
    _create_wallets(sqlite_session)
    _create_required_rules(
        sqlite_session,
        revenue_floor_configuration={"amount": "10.00", "currency": "EUR"},
    )

    revenue_floor_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-revenue-currency-mismatch"),
        timestamp=_monday_noon(),
    )

    assert revenue_floor_decision.decision == "reject"
    assert "revenue floor rule is missing required currency or amount" in (
        revenue_floor_decision.reason
    )

    sqlite_session.rollback()
    _create_wallets(sqlite_session)
    _create_required_rules(
        sqlite_session,
        reserve_minimum_configuration={"amount": "5.00", "currency": "EUR"},
    )

    reserve_minimum_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-reserve-currency-mismatch"),
        timestamp=_monday_noon(),
    )

    assert reserve_minimum_decision.decision == "reject"
    assert "reserve minimum rule is missing required currency or amount" in (
        reserve_minimum_decision.reason
    )


def test_negative_floor_and_minimum_policy_config_rejects_fail_closed(
    sqlite_session,
):
    _create_wallets(sqlite_session, revenue_balance=Decimal("0.00"))
    _create_required_rules(
        sqlite_session,
        revenue_floor_configuration={"amount": "-10.00", "currency": "USD"},
    )

    revenue_floor_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-negative-revenue-floor"),
        timestamp=_monday_noon(),
    )

    assert revenue_floor_decision.decision == "reject"
    assert "revenue floor rule is missing required currency or amount" in (
        revenue_floor_decision.reason
    )

    sqlite_session.rollback()
    _create_wallets(sqlite_session, operating_balance=Decimal("0.00"))
    _create_required_rules(
        sqlite_session,
        reserve_minimum_configuration={"amount": "-5.00", "currency": "USD"},
    )

    reserve_minimum_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-negative-reserve-minimum"),
        timestamp=_monday_noon(),
    )

    assert reserve_minimum_decision.decision == "reject"
    assert "reserve minimum rule is missing required currency or amount" in (
        reserve_minimum_decision.reason
    )


def test_revenue_floor_or_operating_minimum_blocks_spend(sqlite_session):
    _create_wallets(
        sqlite_session,
        revenue_balance=Decimal("5.00"),
        operating_balance=Decimal("50.00"),
    )
    _create_required_rules(sqlite_session)

    revenue_floor_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-revenue-floor"),
        timestamp=_monday_noon(),
    )
    assert revenue_floor_decision.decision == "reject"
    assert "revenue wallet is below required floor" in revenue_floor_decision.reason

    sqlite_session.rollback()
    _create_wallets(sqlite_session, operating_balance=Decimal("12.00"))
    _create_required_rules(sqlite_session)

    operating_minimum_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(
            amount=Decimal("10.00"),
            reference_id="expense-budget-exhausted",
        ),
        timestamp=_monday_noon(),
    )
    assert operating_minimum_decision.decision == "reject"
    assert "operating wallet minimum would be violated" in (
        operating_minimum_decision.reason
    )
    alert = sqlite_session.scalar(
        select(LedgerEntry).where(LedgerEntry.type == "alert.budget_exhaustion")
    )
    assert alert is not None
    assert alert.reference_id == operating_minimum_decision.id


def test_category_budget_only_counts_spend_inside_configured_period(sqlite_session):
    _create_wallets(sqlite_session, operating_balance=Decimal("150.00"))
    _create_required_rules(
        sqlite_session,
        category_budget_configuration={
            "budgets": [
                {
                    "category": "software",
                    "limit": "100.00",
                    "currency": "USD",
                    "period": "monthly",
                }
            ]
        },
    )
    sqlite_session.add(
        ExpenseRequest(
            vendor="sandbox-approved-vendor",
            category="software",
            amount=Decimal("95.00"),
            currency="USD",
            rationale="previous month spend",
            policy_status="approved",
            execution_status="executed",
            created_by_actor="agent:ryan",
            created_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        )
    )
    sqlite_session.flush()

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(
            amount=Decimal("10.00"),
            reference_id="expense-new-month-budget",
        ),
        timestamp=_monday_noon(),
    )

    assert decision.decision == "approve"
    assert decision.rule_results["category_budget"]["current_spend"] == "0.00"


def test_frozen_or_locked_wallet_rejects(sqlite_session):
    _create_wallets(sqlite_session, operating_locked=True)
    _create_required_rules(sqlite_session)

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-frozen-wallet"),
        timestamp=_monday_noon(),
    )

    assert decision.decision == "reject"
    assert "source wallet is locked or frozen" in decision.reason
    assert decision.rule_results["wallet_lock"]["passed"] is False


def test_active_kill_switch_blocks_external_action(sqlite_session):
    from ryan.kill_switch import activate_kill_switch

    _create_wallets(sqlite_session)
    _create_required_rules(sqlite_session)
    activate_kill_switch(
        sqlite_session,
        actor="operator:test",
        reason="operator stop",
        timestamp=_monday_noon(),
    )

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-kill-switch"),
        timestamp=_monday_noon(),
    )

    assert decision.decision == "reject"
    assert "kill switch is active" in decision.reason
    assert decision.rule_results["kill_switch"]["passed"] is False


def test_irreversible_action_escalates_for_exception_review(sqlite_session):
    decision = _evaluate_default(
        sqlite_session,
        action_type="payment_refund",
        reference_id="refund-operator-review",
        irreversible=True,
    )

    assert decision.decision == "escalate"
    assert "irreversible action requires operator review" in decision.reason
    assert decision.rule_results["exception_escalation"]["decision"] == "escalate"


def test_missing_required_inputs_or_policy_config_fails_closed(sqlite_session):
    _create_wallets(sqlite_session)
    _create_required_rules(sqlite_session)

    missing_input_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(amount=None, reference_id="expense-missing-amount"),
        timestamp=_monday_noon(),
    )
    assert missing_input_decision.decision == "reject"
    assert "missing required policy input: amount" in missing_input_decision.reason

    sqlite_session.rollback()
    _create_wallets(sqlite_session)
    create_policy_rule(
        sqlite_session,
        rule_type="vendor_allowlist",
        configuration={"vendors": []},
        actor="operator:test",
        priority=1,
    )

    missing_config_decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-missing-config"),
        timestamp=_monday_noon(),
    )
    assert missing_config_decision.decision == "reject"
    assert "missing active policy rule" in missing_config_decision.reason


def test_policy_service_flushes_without_committing(sqlite_session):
    _create_wallets(sqlite_session)
    _create_required_rules(sqlite_session)

    decision = evaluate_policy(
        sqlite_session,
        request=_expense_request(reference_id="expense-rollback"),
        timestamp=_monday_noon(),
    )

    assert decision.id is not None
    assert sqlite_session.scalar(select(func.count()).select_from(PolicyDecision)) == 1

    sqlite_session.rollback()

    assert sqlite_session.scalar(select(func.count()).select_from(PolicyDecision)) == 0
