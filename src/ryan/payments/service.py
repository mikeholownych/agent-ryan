from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.catalog import OfferNotUsableError, validate_offer_for_payment_creation
from ryan.idempotency import IdempotencyResponseReference, run_idempotent
from ryan.ledger import append_ledger_entry
from ryan.models import CheckoutSession, LedgerEntry, Payment, PolicyDecision, PolicyRule, Wallet
from ryan.payments.provider import (
    ProviderCheckoutRequest,
    SimulatedPaymentProvider,
    ProviderConfirmationRequest,
)
from ryan.telemetry import emit_alert
from ryan.wallets import allocate_settled_revenue

PAYMENT_CREATE_IDEMPOTENCY_SCOPE = "payment_create"
PAYMENT_CONFIRM_IDEMPOTENCY_SCOPE = "payment_confirm"
PAYMENT_REFUND_IDEMPOTENCY_SCOPE = "payment_refund"


class PaymentRequestError(ValueError):
    """Raised when a payment request cannot be created safely."""


class PaymentConfirmationError(ValueError):
    """Raised when provider confirmation cannot be trusted."""


class PaymentRefundError(ValueError):
    """Raised when a refund cannot be created safely."""


class PaymentRefundPolicyError(PermissionError):
    """Raised when a refund is not covered by an approval decision."""


def create_payment_request(
    session: Session,
    *,
    offer_id: str,
    channel: str,
    actor: str,
    idempotency_key: str,
    provider=None,
) -> CheckoutSession:
    payload = {
        "offer_id": offer_id,
        "channel": channel,
        "actor": actor,
    }
    response = run_idempotent(
        session,
        scope=PAYMENT_CREATE_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _create_payment_request_once(
            session,
            offer_id=offer_id,
            channel=channel,
            actor=actor,
            idempotency_key=idempotency_key,
            provider=provider,
        ),
    )
    checkout_session = session.get(CheckoutSession, response.response_reference_id)
    if checkout_session is None:
        raise PaymentRequestError("idempotent checkout session reference is missing")
    return checkout_session


def confirm_payment(
    session: Session,
    *,
    checkout_provider_reference: str,
    provider_event_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    verification_token: str,
    actor: str,
    idempotency_key: str,
) -> Payment:
    payload = {
        "checkout_provider_reference": checkout_provider_reference,
        "provider_event_id": provider_event_id,
        "amount": str(amount),
        "currency": currency,
        "status": status,
        "actor": actor,
    }
    response = run_idempotent(
        session,
        scope=PAYMENT_CONFIRM_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _confirm_payment_once(
            session,
            checkout_provider_reference=checkout_provider_reference,
            provider_event_id=provider_event_id,
            amount=amount,
            currency=currency,
            status=status,
            verification_token=verification_token,
            actor=actor,
            idempotency_key=idempotency_key,
        ),
    )
    payment = session.get(Payment, response.response_reference_id)
    if payment is None:
        raise PaymentConfirmationError("idempotent payment reference is missing")
    return payment


def confirm_trusted_provider_payment(
    session: Session,
    *,
    payment_provider: str,
    checkout_provider_reference: str,
    provider_event_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    actor: str,
    idempotency_key: str,
) -> Payment:
    payload = {
        "payment_provider": payment_provider,
        "checkout_provider_reference": checkout_provider_reference,
        "provider_event_id": provider_event_id,
        "amount": str(amount),
        "currency": currency,
        "status": status,
        "actor": actor,
    }
    response = run_idempotent(
        session,
        scope=PAYMENT_CONFIRM_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _confirm_trusted_provider_payment_once(
            session,
            payment_provider=payment_provider,
            checkout_provider_reference=checkout_provider_reference,
            provider_event_id=provider_event_id,
            amount=amount,
            currency=currency,
            status=status,
            actor=actor,
            idempotency_key=idempotency_key,
        ),
    )
    payment = session.get(Payment, response.response_reference_id)
    if payment is None:
        raise PaymentConfirmationError("idempotent payment reference is missing")
    return payment


def settle_revenue_for_payment(
    session: Session,
    *,
    payment: Payment,
    actor: str,
    idempotency_key: str,
) -> None:
    if payment.status != "settled":
        return
    revenue_wallet = _wallet_by_type_and_currency(
        session,
        wallet_type="revenue",
        currency=payment.currency,
    )
    if revenue_wallet is None:
        raise PaymentConfirmationError("settlement requires a revenue wallet")
    _credit_revenue_wallet_for_settlement(
        session,
        payment=payment,
        revenue_wallet=revenue_wallet,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    allocate_settled_revenue(
        session,
        payment_id=payment.id,
        source_wallet_id=revenue_wallet.id,
        allocations=_allocation_amounts_for_payment(session, payment),
        currency=payment.currency,
        actor=actor,
        allocation_rule_reference="active-revenue-allocation-policy",
        idempotency_key=f"revenue-allocation:{idempotency_key}",
    )


def create_refund(
    session: Session,
    *,
    payment_id: str,
    amount: Decimal,
    currency: str,
    actor: str,
    reason: str,
    policy_decision_id: str,
    idempotency_key: str,
) -> Payment:
    payload = {
        "payment_id": payment_id,
        "amount": str(amount),
        "currency": currency,
        "actor": actor,
        "reason": reason,
        "policy_decision_id": policy_decision_id,
    }
    response = run_idempotent(
        session,
        scope=PAYMENT_REFUND_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _create_refund_once(
            session,
            payment_id=payment_id,
            amount=amount,
            currency=currency,
            actor=actor,
            reason=reason,
            policy_decision_id=policy_decision_id,
            idempotency_key=idempotency_key,
        ),
    )
    refund = session.get(Payment, response.response_reference_id)
    if refund is None:
        raise PaymentRefundError("idempotent refund reference is missing")
    return refund


def _create_payment_request_once(
    session: Session,
    *,
    offer_id: str,
    channel: str,
    actor: str,
    idempotency_key: str,
    provider=None,
) -> IdempotencyResponseReference:
    try:
        offer = validate_offer_for_payment_creation(
            session,
            offer_id=offer_id,
            channel=channel,
        )
    except OfferNotUsableError as error:
        raise PaymentRequestError(str(error)) from error

    checkout_provider = provider or SimulatedPaymentProvider()
    provider_result = checkout_provider.create_checkout(
        ProviderCheckoutRequest(
            offer_id=offer.id,
            amount=offer.price,
            currency=offer.currency,
            channel=channel,
            offer_name=offer.name,
            idempotency_key=idempotency_key,
        )
    )
    checkout_session = CheckoutSession(
        offer_id=offer.id,
        status="created",
        payment_provider=provider_result.provider_name,
        provider_reference=provider_result.provider_reference,
        checkout_url=provider_result.checkout_url,
        amount=offer.price,
        currency=offer.currency,
        idempotency_key=idempotency_key,
    )
    session.add(checkout_session)
    session.flush()
    append_ledger_entry(
        session,
        type="audit.payment.checkout_created",
        amount=checkout_session.amount,
        currency=checkout_session.currency,
        reference_type="checkout_session",
        reference_id=checkout_session.id,
        actor=actor,
        metadata={
            "offer_id": offer.id,
            "channel": channel,
            "payment_provider": provider_result.provider_name,
            "provider_reference": provider_result.provider_reference,
        },
    )
    return IdempotencyResponseReference(
        response_reference_type="checkout_session",
        response_reference_id=checkout_session.id,
    )


def _confirm_payment_once(
    session: Session,
    *,
    checkout_provider_reference: str,
    provider_event_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    verification_token: str,
    actor: str,
    idempotency_key: str,
) -> IdempotencyResponseReference:
    existing_payment = _payment_by_provider_event(
        session,
        payment_provider="simulated",
        provider_event_id=provider_event_id,
    )
    if existing_payment is not None:
        return IdempotencyResponseReference(
            response_reference_type="payment",
            response_reference_id=existing_payment.id,
        )

    checkout_session = _checkout_session_by_provider_reference(
        session,
        payment_provider="simulated",
        provider_reference=checkout_provider_reference,
    )
    provider = SimulatedPaymentProvider()
    confirmation = provider.verify_confirmation(
        ProviderConfirmationRequest(
            provider_event_id=provider_event_id,
            amount=amount,
            currency=currency,
            status=status,
            verification_token=verification_token,
        )
    )
    if not confirmation.verified:
        _record_invalid_confirmation_alert(
            session,
            actor=actor,
            checkout_session=checkout_session,
            provider_event_id=provider_event_id,
            reason="provider confirmation verification failed",
        )
        raise PaymentConfirmationError("provider confirmation verification failed")

    if checkout_session is None:
        _record_invalid_confirmation_alert(
            session,
            actor=actor,
            checkout_session=None,
            provider_event_id=provider_event_id,
            reason="checkout session was not found",
        )
        raise PaymentConfirmationError("checkout session was not found")

    if checkout_session.amount != amount or checkout_session.currency != currency:
        _record_invalid_confirmation_alert(
            session,
            actor=actor,
            checkout_session=checkout_session,
            provider_event_id=provider_event_id,
            reason="amount or currency mismatch",
        )
        raise PaymentConfirmationError("amount or currency mismatch")

    payment_status = _normalize_payment_status(status)
    payment = Payment(
        checkout_session_id=checkout_session.id,
        amount=amount,
        currency=currency,
        status=payment_status,
        source="customer",
        payment_provider="simulated",
        provider_reference=provider_event_id,
        settlement_time=datetime.now(UTC) if payment_status == "settled" else None,
        idempotency_key=idempotency_key,
    )
    session.add(payment)
    checkout_session.status = payment_status
    session.flush()
    append_ledger_entry(
        session,
        type="audit.payment.confirmed",
        amount=payment.amount,
        currency=payment.currency,
        reference_type="payment",
        reference_id=payment.id,
        actor=actor,
        metadata={
            "checkout_session_id": checkout_session.id,
            "provider_event_id": provider_event_id,
            "payment_provider": "simulated",
            "status": payment_status,
        },
    )
    return IdempotencyResponseReference(
        response_reference_type="payment",
        response_reference_id=payment.id,
    )


def _confirm_trusted_provider_payment_once(
    session: Session,
    *,
    payment_provider: str,
    checkout_provider_reference: str,
    provider_event_id: str,
    amount: Decimal,
    currency: str,
    status: str,
    actor: str,
    idempotency_key: str,
) -> IdempotencyResponseReference:
    existing_payment = _payment_by_provider_event(
        session,
        payment_provider=payment_provider,
        provider_event_id=provider_event_id,
    )
    if existing_payment is not None:
        return IdempotencyResponseReference(
            response_reference_type="payment",
            response_reference_id=existing_payment.id,
        )

    checkout_session = _checkout_session_by_provider_reference(
        session,
        payment_provider=payment_provider,
        provider_reference=checkout_provider_reference,
    )
    if checkout_session is None:
        _record_invalid_confirmation_alert(
            session,
            actor=actor,
            checkout_session=None,
            provider_event_id=provider_event_id,
            reason="checkout session was not found",
        )
        raise PaymentConfirmationError("checkout session was not found")

    if checkout_session.amount != amount or checkout_session.currency != currency:
        _record_invalid_confirmation_alert(
            session,
            actor=actor,
            checkout_session=checkout_session,
            provider_event_id=provider_event_id,
            reason="amount or currency mismatch",
        )
        raise PaymentConfirmationError("amount or currency mismatch")

    payment_status = _normalize_payment_status(status)
    payment = Payment(
        checkout_session_id=checkout_session.id,
        amount=amount,
        currency=currency,
        status=payment_status,
        source="customer",
        payment_provider=payment_provider,
        provider_reference=provider_event_id,
        settlement_time=datetime.now(UTC) if payment_status == "settled" else None,
        idempotency_key=idempotency_key,
    )
    session.add(payment)
    checkout_session.status = payment_status
    session.flush()
    append_ledger_entry(
        session,
        type="audit.payment.confirmed",
        amount=payment.amount,
        currency=payment.currency,
        reference_type="payment",
        reference_id=payment.id,
        actor=actor,
        metadata={
            "checkout_session_id": checkout_session.id,
            "provider_event_id": provider_event_id,
            "payment_provider": payment_provider,
            "status": payment_status,
        },
    )
    return IdempotencyResponseReference(
        response_reference_type="payment",
        response_reference_id=payment.id,
    )


def _create_refund_once(
    session: Session,
    *,
    payment_id: str,
    amount: Decimal,
    currency: str,
    actor: str,
    reason: str,
    policy_decision_id: str,
    idempotency_key: str,
) -> IdempotencyResponseReference:
    original_payment = session.get(Payment, payment_id)
    if original_payment is None or original_payment.status != "settled":
        raise PaymentRefundError("refund requires a settled payment")
    if original_payment.currency != currency:
        raise PaymentRefundError("refund currency must match original payment")
    if not amount.is_finite() or amount <= Decimal("0") or amount > original_payment.amount:
        raise PaymentRefundError("refund amount must be positive and within payment amount")
    _assert_approved_refund_policy(
        session,
        policy_decision_id=policy_decision_id,
        payment_id=payment_id,
    )

    refund = Payment(
        checkout_session_id=original_payment.checkout_session_id,
        invoice_id=original_payment.invoice_id,
        amount=-amount,
        currency=currency,
        status="refunded",
        source="refund",
        payment_provider="simulated",
        provider_reference=f"simulated-refund-{uuid4()}",
        settlement_time=datetime.now(UTC),
        idempotency_key=idempotency_key,
    )
    session.add(refund)
    session.flush()
    append_ledger_entry(
        session,
        type="audit.payment.refunded",
        amount=refund.amount,
        currency=refund.currency,
        reference_type="payment",
        reference_id=refund.id,
        actor=actor,
        metadata={
            "original_payment_id": original_payment.id,
            "reason": reason,
            "policy_decision_id": policy_decision_id,
        },
    )
    return IdempotencyResponseReference(
        response_reference_type="payment",
        response_reference_id=refund.id,
    )


def _assert_approved_refund_policy(
    session: Session,
    *,
    policy_decision_id: str,
    payment_id: str,
) -> None:
    decision = session.get(PolicyDecision, policy_decision_id)
    if (
        decision is None
        or decision.action_type != "refund"
        or decision.decision != "approve"
        or decision.request_reference_type != "payment"
        or decision.request_reference_id != payment_id
    ):
        raise PaymentRefundPolicyError("refund requires an approved policy decision")


def _payment_by_provider_event(
    session: Session,
    *,
    payment_provider: str,
    provider_event_id: str,
) -> Payment | None:
    return session.scalar(
        select(Payment).where(
            Payment.payment_provider == payment_provider,
            Payment.provider_reference == provider_event_id,
        )
    )


def _checkout_session_by_provider_reference(
    session: Session,
    *,
    payment_provider: str,
    provider_reference: str,
) -> CheckoutSession | None:
    return session.scalar(
        select(CheckoutSession).where(
            CheckoutSession.payment_provider == payment_provider,
            CheckoutSession.provider_reference == provider_reference,
        )
    )


def _normalize_payment_status(status: str) -> str:
    if status not in {"confirmed", "settled"}:
        raise PaymentConfirmationError("provider confirmation status is unsupported")
    return status


def _record_invalid_confirmation_alert(
    session: Session,
    *,
    actor: str,
    checkout_session: CheckoutSession | None,
    provider_event_id: str,
    reason: str,
) -> None:
    emit_alert(
        session,
        alert_type="invalid_payment_confirmation",
        severity="high",
        actor=actor,
        reference_type="checkout_session",
        reference_id=checkout_session.id if checkout_session is not None else "unknown",
        metadata={
            "reason": reason,
            "provider_event_id": provider_event_id,
        },
    )


def _wallet_by_type_and_currency(
    session: Session,
    *,
    wallet_type: str,
    currency: str,
) -> Wallet | None:
    return session.scalar(
        select(Wallet).where(Wallet.type == wallet_type, Wallet.currency == currency)
    )


def _credit_revenue_wallet_for_settlement(
    session: Session,
    *,
    payment: Payment,
    revenue_wallet: Wallet,
    actor: str,
    idempotency_key: str,
) -> None:
    existing_entry = session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.type == "wallet.settlement.credit",
            LedgerEntry.reference_type == "payment",
            LedgerEntry.reference_id == payment.id,
            LedgerEntry.metadata_["idempotency_key"].as_string() == idempotency_key,
        )
    )
    if existing_entry is not None:
        return
    revenue_wallet.balance += payment.amount
    session.flush()
    append_ledger_entry(
        session,
        type="wallet.settlement.credit",
        amount=payment.amount,
        currency=payment.currency,
        reference_type="payment",
        reference_id=payment.id,
        actor=actor,
        metadata={
            "wallet_id": revenue_wallet.id,
            "idempotency_key": idempotency_key,
        },
    )


def _allocation_amounts_for_payment(
    session: Session,
    payment: Payment,
) -> dict[str, Decimal]:
    rule = session.scalar(
        select(PolicyRule)
        .where(PolicyRule.type == "revenue_allocation", PolicyRule.status == "active")
        .order_by(PolicyRule.priority.asc(), PolicyRule.created_at.asc())
    )
    if rule is None:
        raise PaymentConfirmationError("settlement requires revenue allocation policy")

    percentages = rule.configuration.get("wallet_percentages") or {}
    required_wallets = {"revenue", "operating", "reserve"}
    if set(percentages) != required_wallets:
        raise PaymentConfirmationError("revenue allocation policy must cover MVP wallets")

    amounts: dict[str, Decimal] = {}
    remaining = payment.amount
    for wallet_type in ["operating", "reserve"]:
        amount = (payment.amount * Decimal(str(percentages[wallet_type])) / Decimal("100"))
        amount = amount.quantize(Decimal("0.01"))
        amounts[wallet_type] = amount
        remaining -= amount
    amounts["revenue"] = remaining
    return amounts


__all__ = [
    "PAYMENT_CREATE_IDEMPOTENCY_SCOPE",
    "PAYMENT_CONFIRM_IDEMPOTENCY_SCOPE",
    "PAYMENT_REFUND_IDEMPOTENCY_SCOPE",
    "PaymentConfirmationError",
    "PaymentRefundError",
    "PaymentRefundPolicyError",
    "PaymentRequestError",
    "confirm_payment",
    "confirm_trusted_provider_payment",
    "create_refund",
    "create_payment_request",
    "settle_revenue_for_payment",
]
