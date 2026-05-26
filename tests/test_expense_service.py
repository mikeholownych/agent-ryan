from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.expenses.service import create_expense_request
from ryan.models import ExceptionRecord, ExpenseRequest, LedgerEntry, PolicyRule, Wallet
from ryan.policy import create_policy_rule


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


def _create_wallets(sqlite_session, *, operating_balance=Decimal("100.00")):
    wallets = [
        Wallet(
            type="revenue",
            balance=Decimal("100.00"),
            currency="USD",
            locked=False,
            limits={},
        ),
        Wallet(
            type="operating",
            balance=operating_balance,
            currency="USD",
            locked=False,
            limits={"minimum": "5.00"},
        ),
        Wallet(
            type="reserve",
            balance=Decimal("25.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "5.00"},
        ),
    ]
    sqlite_session.add_all(wallets)
    sqlite_session.flush()
    return {wallet.type: wallet for wallet in wallets}


def _create_policy_rules(sqlite_session, *, spend_cap="25.00"):
    create_policy_rule(
        sqlite_session,
        rule_type="vendor_allowlist",
        configuration={
            "vendors": [
                {
                    "name": "approved-vendor",
                    "categories": ["software"],
                    "status": "approved",
                }
            ]
        },
        actor="operator:test",
        priority=1,
    )
    create_policy_rule(
        sqlite_session,
        rule_type="spend_threshold",
        configuration={"per_transaction_cap": spend_cap, "currency": "USD"},
        actor="operator:test",
        priority=2,
    )
    create_policy_rule(
        sqlite_session,
        rule_type="category_budget",
        configuration={
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
        sqlite_session,
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
        sqlite_session,
        rule_type="revenue_floor",
        configuration={"amount": "10.00", "currency": "USD"},
        actor="operator:test",
        priority=5,
    )
    create_policy_rule(
        sqlite_session,
        rule_type="reserve_minimum",
        configuration={"amount": "5.00", "currency": "USD"},
        actor="operator:test",
        priority=6,
    )


def _expense_payload(**overrides):
    payload = {
        "vendor": "approved-vendor",
        "category": "software",
        "amount": Decimal("10.00"),
        "currency": "USD",
        "rationale": "required software subscription",
        "actor": "agent:ryan",
        "idempotency_key": "expense-001",
        "timestamp": _monday_noon(),
    }
    payload.update(overrides)
    return payload


def test_approved_expense_executes_from_operating_wallet(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    _create_policy_rules(sqlite_session)

    expense = create_expense_request(sqlite_session, **_expense_payload())

    assert expense.policy_status == "approved"
    assert expense.execution_status == "executed"
    assert expense.source_wallet_id == wallets["operating"].id
    assert wallets["operating"].balance == Decimal("90.00")
    assert sqlite_session.scalar(select(ExceptionRecord)) is None
    ledger_types = set(
        sqlite_session.scalars(
            select(LedgerEntry.type).where(
                LedgerEntry.reference_type == "expense",
                LedgerEntry.reference_id == expense.id,
            )
        )
    )
    assert "audit.expense.requested" in ledger_types
    assert "wallet.expense.debit" in ledger_types


def test_expense_replay_does_not_duplicate_wallet_debit(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    _create_policy_rules(sqlite_session)

    first_expense = create_expense_request(sqlite_session, **_expense_payload())
    second_expense = create_expense_request(sqlite_session, **_expense_payload())

    assert second_expense.id == first_expense.id
    assert wallets["operating"].balance == Decimal("90.00")
    assert sqlite_session.scalar(select(func.count(ExpenseRequest.id))) == 1


def test_unallowlisted_expense_rejects_without_execution(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    _create_policy_rules(sqlite_session)

    expense = create_expense_request(
        sqlite_session,
        **_expense_payload(
            vendor="unapproved-vendor",
            idempotency_key="expense-unapproved",
        ),
    )

    assert expense.policy_status == "rejected"
    assert expense.execution_status == "blocked"
    assert wallets["operating"].balance == Decimal("100.00")
    exception = sqlite_session.scalar(select(ExceptionRecord))
    assert exception.type == "policy_rejection"


def test_over_threshold_expense_escalates_without_execution(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    _create_policy_rules(sqlite_session, spend_cap="25.00")

    expense = create_expense_request(
        sqlite_session,
        **_expense_payload(
            amount=Decimal("30.00"),
            idempotency_key="expense-over-threshold",
        ),
    )

    assert expense.policy_status == "escalated"
    assert expense.execution_status == "pending_review"
    assert wallets["operating"].balance == Decimal("100.00")
    exception = sqlite_session.scalar(select(ExceptionRecord))
    assert exception.type == "policy_escalation"


def test_budget_exhaustion_blocks_expense_and_creates_exception(sqlite_session):
    wallets = _create_wallets(sqlite_session, operating_balance=Decimal("12.00"))
    _create_policy_rules(sqlite_session)

    expense = create_expense_request(
        sqlite_session,
        **_expense_payload(idempotency_key="expense-budget-exhausted"),
    )

    assert expense.policy_status == "rejected"
    assert expense.execution_status == "blocked"
    assert wallets["operating"].balance == Decimal("12.00")
    exception = sqlite_session.scalar(select(ExceptionRecord))
    assert exception.type == "budget_exhaustion"
    alert_entry = sqlite_session.scalar(
        select(LedgerEntry).where(LedgerEntry.type == "alert.budget_exhaustion")
    )
    assert alert_entry is not None
