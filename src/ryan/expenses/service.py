from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from ryan.exceptions import create_exception_record
from ryan.expenses.provider import (
    OutboundPaymentProvider,
    OutboundPaymentRequest,
    SimulatedOutboundPaymentProvider,
)
from ryan.idempotency import IdempotencyResponseReference, run_idempotent
from ryan.ledger import append_ledger_entry
from ryan.models import ExpenseRequest, PolicyDecision, Wallet
from ryan.policy import PolicyEvaluationRequest, evaluate_policy
from ryan.telemetry import emit_expense_event

EXPENSE_CREATE_IDEMPOTENCY_SCOPE = "expense_create"


class ExpenseRequestError(ValueError):
    """Raised when an expense request cannot be processed safely."""


def create_expense_request(
    session: Session,
    *,
    vendor: str,
    category: str,
    amount: Decimal,
    currency: str,
    rationale: str,
    actor: str,
    idempotency_key: str,
    timestamp: datetime | None = None,
    irreversible: bool = False,
    outbound_provider: OutboundPaymentProvider | None = None,
) -> ExpenseRequest:
    payload = {
        "vendor": vendor,
        "category": category,
        "amount": str(amount),
        "currency": currency,
        "rationale": rationale,
        "actor": actor,
        "irreversible": irreversible,
    }
    response = run_idempotent(
        session,
        scope=EXPENSE_CREATE_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _create_expense_once(
            session,
            vendor=vendor,
            category=category,
            amount=amount,
            currency=currency,
            rationale=rationale,
            actor=actor,
            idempotency_key=idempotency_key,
            timestamp=timestamp,
            irreversible=irreversible,
            outbound_provider=outbound_provider,
        ),
    )
    expense = session.get(ExpenseRequest, response.response_reference_id)
    if expense is None:
        raise ExpenseRequestError("idempotent expense reference is missing")
    return expense


def _create_expense_once(
    session: Session,
    *,
    vendor: str,
    category: str,
    amount: Decimal,
    currency: str,
    rationale: str,
    actor: str,
    idempotency_key: str,
    timestamp: datetime | None,
    irreversible: bool,
    outbound_provider: OutboundPaymentProvider | None,
) -> IdempotencyResponseReference:
    operating_wallet = _operating_wallet(session, currency)
    if operating_wallet is None:
        raise ExpenseRequestError("expense execution requires an operating wallet")

    expense = ExpenseRequest(
        vendor=vendor,
        category=category,
        amount=amount,
        currency=currency,
        rationale=rationale,
        policy_status="pending",
        source_wallet_id=operating_wallet.id,
        execution_status="pending",
        idempotency_key=idempotency_key,
        created_by_actor=actor,
    )
    session.add(expense)
    session.flush()
    emit_expense_event(
        session,
        event_name="requested",
        expense_id=expense.id,
        actor=actor,
        metadata={
            "vendor": vendor,
            "category": category,
            "amount": str(amount),
            "currency": currency,
            "rationale": rationale,
        },
        timestamp=timestamp,
    )

    decision = evaluate_policy(
        session,
        request=PolicyEvaluationRequest(
            action_type="expense_execute",
            vendor=vendor,
            category=category,
            amount=amount,
            currency=currency,
            actor=actor,
            request_reference_type="expense",
            request_reference_id=expense.id,
            source_wallet_type="operating",
            irreversible=irreversible,
        ),
        timestamp=timestamp,
    )
    expense.policy_decision_id = decision.id
    _apply_policy_decision(
        session,
        expense=expense,
        decision=decision,
        operating_wallet=operating_wallet,
        actor=actor,
        timestamp=timestamp,
        outbound_provider=outbound_provider,
    )
    session.flush()
    return IdempotencyResponseReference(
        response_reference_type="expense",
        response_reference_id=expense.id,
    )


def _apply_policy_decision(
    session: Session,
    *,
    expense: ExpenseRequest,
    decision: PolicyDecision,
    operating_wallet: Wallet,
    actor: str,
    timestamp: datetime | None,
    outbound_provider: OutboundPaymentProvider | None,
) -> None:
    if decision.decision == "approve":
        _execute_approved_expense(
            session,
            expense=expense,
            operating_wallet=operating_wallet,
            actor=actor,
            timestamp=timestamp,
            outbound_provider=outbound_provider,
        )
        return
    if decision.decision == "escalate":
        expense.policy_status = "escalated"
        expense.execution_status = "pending_review"
        _create_policy_exception(
            session,
            expense=expense,
            decision=decision,
            exception_type="policy_escalation",
            severity="medium",
            actor=actor,
        )
        return

    expense.policy_status = "rejected"
    expense.execution_status = "blocked"
    _create_policy_exception(
        session,
        expense=expense,
        decision=decision,
        exception_type=_exception_type_for_rejection(decision),
        severity="high",
        actor=actor,
    )


def _execute_approved_expense(
    session: Session,
    *,
    expense: ExpenseRequest,
    operating_wallet: Wallet,
    actor: str,
    timestamp: datetime | None,
    outbound_provider: OutboundPaymentProvider | None,
) -> None:
    if operating_wallet.balance < expense.amount:
        raise ExpenseRequestError("operating wallet has insufficient funds")
    provider = outbound_provider or SimulatedOutboundPaymentProvider()
    provider_result = provider.submit_payment(
        OutboundPaymentRequest(
            expense_id=expense.id,
            vendor=expense.vendor,
            category=expense.category,
            amount=expense.amount,
            currency=expense.currency,
            rationale=expense.rationale,
            idempotency_key=expense.idempotency_key or expense.id,
        )
    )
    operating_wallet.balance -= expense.amount
    expense.policy_status = "approved"
    expense.execution_status = "executed"
    expense.outbound_payment_provider = provider_result.provider_name
    expense.outbound_payment_reference = provider_result.provider_reference
    expense.outbound_payment_status = provider_result.status
    session.flush()
    append_ledger_entry(
        session,
        type="outbound.payment.submitted",
        amount=-expense.amount,
        currency=expense.currency,
        reference_type="expense",
        reference_id=expense.id,
        actor=actor,
        metadata={
            "payment_provider": provider_result.provider_name,
            "provider_reference": provider_result.provider_reference,
            "provider_status": provider_result.status,
            "vendor": expense.vendor,
            "category": expense.category,
        },
        timestamp=timestamp,
    )
    append_ledger_entry(
        session,
        type="wallet.expense.debit",
        amount=-expense.amount,
        currency=expense.currency,
        reference_type="expense",
        reference_id=expense.id,
        actor=actor,
        metadata={
            "wallet_id": operating_wallet.id,
            "policy_decision_id": expense.policy_decision_id,
            "vendor": expense.vendor,
            "category": expense.category,
            "outbound_payment_provider": provider_result.provider_name,
            "outbound_payment_reference": provider_result.provider_reference,
        },
        timestamp=timestamp,
    )
    emit_expense_event(
        session,
        event_name="executed",
        expense_id=expense.id,
        actor=actor,
        metadata={
            "wallet_id": operating_wallet.id,
            "policy_decision_id": expense.policy_decision_id,
        },
        timestamp=timestamp,
    )


def _create_policy_exception(
    session: Session,
    *,
    expense: ExpenseRequest,
    decision: PolicyDecision,
    exception_type: str,
    severity: str,
    actor: str,
) -> None:
    create_exception_record(
        session,
        exception_type=exception_type,
        severity=severity,
        reason=decision.reason,
        reference_type="expense",
        reference_id=expense.id,
        actor=actor,
        policy_decision_id=decision.id,
    )


def _exception_type_for_rejection(decision: PolicyDecision) -> str:
    reason = decision.reason.lower()
    if "kill switch" in reason:
        return "kill_switch_blocked"
    if "minimum" in reason or "budget" in reason:
        return "budget_exhaustion"
    if "locked" in reason or "frozen" in reason:
        return "frozen_spend"
    return "policy_rejection"


def _operating_wallet(session: Session, currency: str) -> Wallet | None:
    from sqlalchemy import select

    return session.scalar(
        select(Wallet).where(Wallet.type == "operating", Wallet.currency == currency)
    )


__all__ = [
    "EXPENSE_CREATE_IDEMPOTENCY_SCOPE",
    "ExpenseRequestError",
    "create_expense_request",
]
