from __future__ import annotations

from sqlalchemy.orm import Session

from ryan.catalog import OfferNotUsableError, validate_offer_for_payment_creation
from ryan.idempotency import IdempotencyResponseReference, run_idempotent
from ryan.ledger import append_ledger_entry
from ryan.models import CheckoutSession
from ryan.payments.provider import ProviderCheckoutRequest, SimulatedPaymentProvider

PAYMENT_CREATE_IDEMPOTENCY_SCOPE = "payment_create"


class PaymentRequestError(ValueError):
    """Raised when a payment request cannot be created safely."""


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


__all__ = [
    "PAYMENT_CREATE_IDEMPOTENCY_SCOPE",
    "PaymentRequestError",
    "create_payment_request",
]
