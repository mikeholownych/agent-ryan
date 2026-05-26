from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ryan.config import Settings, get_settings
from ryan.db import get_session
from ryan.models import CheckoutSession, Payment
from ryan.payments.service import (
    PaymentConfirmationError,
    PaymentRefundError,
    PaymentRefundPolicyError,
    PaymentRequestError,
    confirm_payment,
    create_refund,
    create_payment_request,
    settle_revenue_for_payment,
)
from ryan.payments.provider import SimulatedPaymentProvider, StripePaymentProvider

router = APIRouter(prefix="/api/payments", tags=["payments"])


class PaymentCreateRequest(BaseModel):
    offer_id: str
    channel: str
    actor: str
    idempotency_key: str


class CheckoutSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    offer_id: str
    status: str
    payment_provider: str | None
    provider_reference: str | None
    checkout_url: str | None
    amount: Decimal
    currency: str
    idempotency_key: str | None


class PaymentConfirmRequest(BaseModel):
    checkout_provider_reference: str
    provider_event_id: str
    amount: Decimal
    currency: str
    status: Literal["confirmed", "settled"]
    verification_token: str
    actor: str
    idempotency_key: str


class PaymentRefundRequest(BaseModel):
    payment_id: str
    amount: Decimal
    currency: str
    actor: str
    reason: str
    policy_decision_id: str
    idempotency_key: str


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    checkout_session_id: str | None
    invoice_id: str | None
    amount: Decimal
    currency: str
    status: str
    source: str
    payment_provider: str | None
    provider_reference: str | None
    settlement_time: datetime | None
    idempotency_key: str | None


class PaymentLookupResponse(BaseModel):
    kind: str
    record: CheckoutSessionResponse | PaymentResponse


@router.post(
    "/create",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_payment_create(
    payload: PaymentCreateRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    try:
        checkout_session = create_payment_request(
            session,
            offer_id=payload.offer_id,
            channel=payload.channel,
            actor=payload.actor,
            idempotency_key=payload.idempotency_key,
            provider=_payment_provider_from_settings(settings),
        )
    except PaymentRequestError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    session.commit()
    session.refresh(checkout_session)
    return checkout_session


def _payment_provider_from_settings(settings: Settings):
    if settings.payment_rail == "stripe":
        if (
            settings.stripe_api_key is None
            or settings.stripe_success_url is None
            or settings.stripe_cancel_url is None
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stripe payment rail is not fully configured",
            )
        return StripePaymentProvider(
            api_key=settings.stripe_api_key,
            success_url=settings.stripe_success_url,
            cancel_url=settings.stripe_cancel_url,
            http_client=httpx.Client(),
        )
    return SimulatedPaymentProvider()


@router.post("/confirm", response_model=PaymentResponse)
def post_payment_confirm(
    payload: PaymentConfirmRequest,
    session: Session = Depends(get_session),
):
    try:
        payment = confirm_payment(
            session,
            checkout_provider_reference=payload.checkout_provider_reference,
            provider_event_id=payload.provider_event_id,
            amount=payload.amount,
            currency=payload.currency,
            status=payload.status,
            verification_token=payload.verification_token,
            actor=payload.actor,
            idempotency_key=payload.idempotency_key,
        )
        settle_revenue_for_payment(
            session,
            payment=payment,
            actor=payload.actor,
            idempotency_key=payload.idempotency_key,
        )
    except PaymentConfirmationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    session.commit()
    session.refresh(payment)
    return payment


@router.post(
    "/refund",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_payment_refund(
    payload: PaymentRefundRequest,
    session: Session = Depends(get_session),
):
    try:
        refund = create_refund(
            session,
            payment_id=payload.payment_id,
            amount=payload.amount,
            currency=payload.currency,
            actor=payload.actor,
            reason=payload.reason,
            policy_decision_id=payload.policy_decision_id,
            idempotency_key=payload.idempotency_key,
        )
    except PaymentRefundPolicyError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except PaymentRefundError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    session.commit()
    session.refresh(refund)
    return refund


@router.get("/{payment_id}", response_model=PaymentLookupResponse)
def get_payment(payment_id: str, session: Session = Depends(get_session)):
    payment = session.get(Payment, payment_id)
    if payment is not None:
        return PaymentLookupResponse(kind="payment", record=payment)

    checkout_session = session.get(CheckoutSession, payment_id)
    if checkout_session is not None:
        return PaymentLookupResponse(kind="checkout_session", record=checkout_session)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"payment or checkout session {payment_id!r} was not found",
    )


__all__ = ["router"]
