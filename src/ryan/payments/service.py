from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.catalog import OfferNotUsableError, validate_offer_for_payment_creation
from ryan.idempotency import IdempotencyResponseReference, run_idempotent
from ryan.ledger import append_ledger_entry
from ryan.models import CheckoutSession, Payment
from ryan.payments.provider import (
    ProviderCheckoutRequest,
    ProviderConfirmationRequest,
    SimulatedPaymentProvider,
)
from ryan.telemetry import emit_alert

PAYMENT_CREATE_IDEMPOTENCY_SCOPE = "payment_create"
PAYMENT_CONFIRM_IDEMPOTENCY_SCOPE = "payment_confirm"


class PaymentRequestError(ValueError):
    """Raised when a payment request cannot be created safely."""


class PaymentConfirmationError(ValueError):
    """Raised when provider confirmation cannot be trusted."""


def create_payment_request(
    session: Session,
    *,
    offer_id: str,
    channel: str,
    actor: str,
    idempotency_key: str,
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


def _create_payment_request_once(
    session: Session,
    *,
    offer_id: str,
    channel: str,
    actor: str,
    idempotency_key: str,
) -> IdempotencyResponseReference:
    try:
        offer = validate_offer_for_payment_creation(
            session,
            offer_id=offer_id,
            channel=channel,
        )
    except OfferNotUsableError as error:
        raise PaymentRequestError(str(error)) from error

    provider = SimulatedPaymentProvider()
    provider_result = provider.create_checkout(
        ProviderCheckoutRequest(
            offer_id=offer.id,
            amount=offer.price,
            currency=offer.currency,
            channel=channel,
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
    existing_payment = _payment_by_provider_event(session, provider_event_id)
    if existing_payment is not None:
        return IdempotencyResponseReference(
            response_reference_type="payment",
            response_reference_id=existing_payment.id,
        )

    checkout_session = _checkout_session_by_provider_reference(
        session,
        checkout_provider_reference,
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


def _payment_by_provider_event(
    session: Session,
    provider_event_id: str,
) -> Payment | None:
    return session.scalar(
        select(Payment).where(
            Payment.payment_provider == "simulated",
            Payment.provider_reference == provider_event_id,
        )
    )


def _checkout_session_by_provider_reference(
    session: Session,
    provider_reference: str,
) -> CheckoutSession | None:
    return session.scalar(
        select(CheckoutSession).where(
            CheckoutSession.payment_provider == "simulated",
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


__all__ = [
    "PAYMENT_CREATE_IDEMPOTENCY_SCOPE",
    "PAYMENT_CONFIRM_IDEMPOTENCY_SCOPE",
    "PaymentConfirmationError",
    "PaymentRequestError",
    "confirm_payment",
    "create_payment_request",
]
