from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from ryan.telemetry import emit_report_event


def generate_daily_report(
    session: Session,
    *,
    report_date: date,
    actor: str,
) -> Report:
    period_start = datetime.combine(report_date, time.min, tzinfo=UTC)
    period_end = period_start + timedelta(days=1)
    report = Report(
        type="daily",
        period_start=period_start,
        period_end=period_end,
        status="generated",
        summary=_build_daily_summary(session, period_start, period_end),
    )
    session.add(report)
    session.flush()
    emit_report_event(
        session,
        event_name="generated",
        report_id=report.id,
        actor=actor,
        metadata={
            "type": report.type,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
    )
    return report


def _build_daily_summary(
    session: Session,
    period_start: datetime,
    period_end: datetime,
) -> dict:
    revenue_total = _revenue_total(session, period_start, period_end)
    expense_total = _expense_total(session, period_start, period_end)
    profit_total = revenue_total - expense_total
    return {
        "revenue_total": str(revenue_total),
        "expense_total": str(expense_total),
        "profit_total": str(profit_total),
        "retained_surplus_total": str(_retained_surplus_total(session)),
        "profit_trend": _profit_trend(session, period_start, profit_total),
        "wallet_balances": _wallet_balances(session),
        "wallet_locks": _wallet_locks(session),
        "allocation_summary": _allocation_summary(session),
        "exception_counts": _exception_counts(session),
        "policy_decisions": _policy_decisions(session, period_start, period_end),
        "notable_events": _notable_events(session, period_start, period_end),
    }


def _revenue_total(
    session: Session,
    period_start: datetime,
    period_end: datetime,
) -> Decimal:
    payments = session.scalars(
        select(Payment).where(
            Payment.source == "customer",
            Payment.status == "settled",
            Payment.settlement_time >= period_start,
            Payment.settlement_time < period_end,
        )
    )
    return sum((payment.amount for payment in payments), Decimal("0.00"))


def _expense_total(
    session: Session,
    period_start: datetime,
    period_end: datetime,
) -> Decimal:
    expenses = session.scalars(
        select(ExpenseRequest).where(
            ExpenseRequest.execution_status == "executed",
            ExpenseRequest.created_at >= period_start,
            ExpenseRequest.created_at < period_end,
        )
    )
    return sum((expense.amount for expense in expenses), Decimal("0.00"))


def _wallet_balances(session: Session) -> dict[str, str]:
    return {
        wallet.type: str(wallet.balance)
        for wallet in session.scalars(select(Wallet).order_by(Wallet.type.asc()))
    }


def _retained_surplus_total(session: Session) -> Decimal:
    return sum(
        (wallet.balance for wallet in session.scalars(select(Wallet))),
        Decimal("0.00"),
    )


def _profit_trend(
    session: Session,
    period_start: datetime,
    current_profit_total: Decimal,
) -> list[dict[str, str]]:
    previous_points = [
        {
            "date": report.period_start.date().isoformat(),
            "profit_total": str(report.summary["profit_total"]),
        }
        for report in session.scalars(
            select(Report)
            .where(
                Report.type == "daily",
                Report.status == "generated",
                Report.period_start < period_start,
            )
            .order_by(Report.period_start.asc())
        )
        if "profit_total" in report.summary
    ]
    return [
        *previous_points,
        {
            "date": period_start.date().isoformat(),
            "profit_total": str(current_profit_total),
        },
    ]


def _wallet_locks(session: Session) -> dict[str, bool]:
    return {
        wallet.type: wallet.locked
        for wallet in session.scalars(select(Wallet).order_by(Wallet.type.asc()))
    }


def _allocation_summary(session: Session) -> dict[str, str]:
    wallet_by_id = {wallet.id: wallet for wallet in session.scalars(select(Wallet))}
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for allocation in session.scalars(select(BucketAllocation)):
        wallet = wallet_by_id.get(allocation.destination_wallet_id)
        if wallet is not None:
            totals[wallet.type] += allocation.amount
    return {wallet_type: str(amount) for wallet_type, amount in totals.items()}


def _exception_counts(session: Session) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for exception in session.scalars(select(ExceptionRecord)):
        counts[exception.type] += 1
    return dict(counts)


def _policy_decisions(
    session: Session,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for decision in session.scalars(
        select(PolicyDecision).where(
            PolicyDecision.created_at >= period_start,
            PolicyDecision.created_at < period_end,
        )
    ):
        counts[decision.decision] += 1
    return dict(counts)


def _notable_events(
    session: Session,
    period_start: datetime,
    period_end: datetime,
) -> list[str]:
    event_types = {
        entry.type
        for entry in session.scalars(
            select(LedgerEntry).where(
                LedgerEntry.timestamp >= period_start,
                LedgerEntry.timestamp < period_end,
                LedgerEntry.type.in_(
                    [
                        "audit.kill_switch.activated",
                        "audit.kill_switch.deactivated",
                        "audit.wallet.freeze",
                        "audit.wallet.unfreeze",
                    ]
                ),
            )
        )
    }
    return sorted(event_types)


__all__ = ["generate_daily_report"]
