from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import (
    BucketAllocation,
    ExceptionRecord,
    ExpenseRequest,
    LedgerEntry,
    Payment,
    PolicyDecision,
    Report,
    Wallet,
)
from ryan.reports.service import generate_daily_report


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


def _seed_report_data(session):
    revenue_wallet = Wallet(
        type="revenue",
        balance=Decimal("20.00"),
        currency="USD",
        locked=False,
        limits={},
    )
    operating_wallet = Wallet(
        type="operating",
        balance=Decimal("50.00"),
        currency="USD",
        locked=False,
        limits={},
    )
    reserve_wallet = Wallet(
        type="reserve",
        balance=Decimal("20.00"),
        currency="USD",
        locked=True,
        limits={},
    )
    session.add_all([revenue_wallet, operating_wallet, reserve_wallet])
    session.flush()
    payment = Payment(
        amount=Decimal("100.00"),
        currency="USD",
        status="settled",
        source="customer",
        payment_provider="simulated",
        provider_reference="provider-event-001",
        settlement_time=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
    )
    expense = ExpenseRequest(
        vendor="approved-vendor",
        category="software",
        amount=Decimal("10.00"),
        currency="USD",
        rationale="subscription",
        policy_status="approved",
        execution_status="executed",
        created_by_actor="agent:ryan",
        created_at=datetime(2026, 5, 25, 12, 30, tzinfo=UTC),
    )
    decision = PolicyDecision(
        action_type="expense_execute",
        decision="approve",
        reason="approved",
        rule_results={},
        request_reference_type="expense",
        request_reference_id="expense-001",
        actor="agent:ryan",
        created_at=datetime(2026, 5, 25, 12, 30, tzinfo=UTC),
    )
    exception = ExceptionRecord(
        type="budget_exhaustion",
        severity="high",
        status="open",
        reason="budget low",
        reference_type="wallet",
        reference_id=operating_wallet.id,
    )
    session.add_all([payment, expense, decision, exception])
    session.flush()
    session.add_all(
        [
            BucketAllocation(
                payment_id=payment.id,
                source_wallet_id=revenue_wallet.id,
                destination_wallet_id=operating_wallet.id,
                amount=Decimal("60.00"),
                currency="USD",
                allocation_rule_reference="test-policy",
                idempotency_key="allocation:operating",
            ),
            LedgerEntry(
                type="audit.wallet.freeze",
                amount=None,
                currency=None,
                reference_type="wallet",
                reference_id=reserve_wallet.id,
                timestamp=datetime(2026, 5, 25, 13, 0, tzinfo=UTC),
                actor="operator:test",
                metadata_={"reason": "manual review"},
            ),
        ]
    )
    session.flush()


def test_generate_daily_report_persists_financial_and_operational_summary(
    sqlite_session,
):
    _seed_report_data(sqlite_session)

    report = generate_daily_report(
        sqlite_session,
        report_date=datetime(2026, 5, 25, tzinfo=UTC).date(),
        actor="system:report",
    )

    assert report.type == "daily"
    assert report.status == "generated"
    assert report.summary["revenue_total"] == "100.00"
    assert report.summary["expense_total"] == "10.00"
    assert report.summary["profit_total"] == "90.00"
    assert report.summary["retained_surplus_total"] == "90.00"
    assert report.summary["wallet_balances"]["revenue"] == "20.00"
    assert report.summary["wallet_balances"]["reserve"] == "20.00"
    assert report.summary["wallet_locks"]["reserve"] is True
    assert report.summary["allocation_summary"]["operating"] == "60.00"
    assert report.summary["exception_counts"]["budget_exhaustion"] == 1
    assert report.summary["policy_decisions"]["approve"] == 1
    assert report.summary["notable_events"] == ["audit.wallet.freeze"]
    assert sqlite_session.get(Report, report.id) is not None


def test_daily_report_includes_profit_trend_over_time(sqlite_session):
    _seed_report_data(sqlite_session)
    previous_report = Report(
        type="daily",
        period_start=datetime(2026, 5, 24, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 25, 0, 0, tzinfo=UTC),
        status="generated",
        summary={"profit_total": "60.00"},
    )
    sqlite_session.add(previous_report)
    sqlite_session.flush()

    report = generate_daily_report(
        sqlite_session,
        report_date=datetime(2026, 5, 25, tzinfo=UTC).date(),
        actor="system:report",
    )

    assert report.summary["profit_trend"] == [
        {"date": "2026-05-24", "profit_total": "60.00"},
        {"date": "2026-05-25", "profit_total": "90.00"},
    ]
