from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import CheckoutSession, LedgerEntry, Offer, Payment
from ryan.payments.provider import ProviderCheckoutResult
from ryan.payments.service import (
    PaymentConfirmationError,
    PaymentRequestError,
    confirm_payment,
    create_payment_request,
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


def _create_offers(session):
    active = Offer(
        id="offer-active",
        name="MVP Support Sprint",
        price=Decimal("100.00"),
        currency="USD",
        status="active",
        allowed_channels=["checkout", "invoice"],
    )
    inactive = Offer(
        id="offer-inactive",
        name="Inactive Offer",
        price=Decimal("200.00"),
        currency="USD",
        status="inactive",
        allowed_channels=["checkout"],
    )
    session.add_all([active, inactive])
    session.flush()
    return active, inactive


class FakeCheckoutProvider:
    name = "fake"

    def __init__(self):
        self.requests = []

    def create_checkout(self, request):
        self.requests.append(request)
        return ProviderCheckoutResult(
            provider_name=self.name,
            provider_reference="fake-checkout-001",
            checkout_url="https://checkout.example/fake-checkout-001",
        )


def test_create_payment_request_for_active_offer_creates_checkout_session(
    sqlite_session,
):
    active, _ = _create_offers(sqlite_session)

    checkout_session = create_payment_request(
        sqlite_session,
        offer_id=active.id,
        channel="checkout",
        actor="agent:ryan",
        idempotency_key="payment-create-001",
    )

    assert checkout_session.offer_id == active.id
    assert checkout_session.status == "created"
    assert checkout_session.amount == Decimal("100.00")
    assert checkout_session.currency == "USD"
    assert checkout_session.payment_provider == "simulated"
    assert checkout_session.provider_reference.startswith("simulated-checkout-")
    assert checkout_session.checkout_url.endswith(checkout_session.provider_reference)

    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reference_type == "checkout_session",
            LedgerEntry.reference_id == checkout_session.id,
            LedgerEntry.type == "audit.payment.checkout_created",
        )
    )
    assert audit_entry is not None
    assert audit_entry.actor == "agent:ryan"


def test_create_payment_request_replays_idempotently(sqlite_session):
    active, _ = _create_offers(sqlite_session)
    payload = {
        "offer_id": active.id,
        "channel": "checkout",
        "actor": "agent:ryan",
        "idempotency_key": "payment-create-001",
    }

    first_session = create_payment_request(sqlite_session, **payload)
    second_session = create_payment_request(sqlite_session, **payload)

    assert second_session.id == first_session.id
    assert sqlite_session.scalar(select(func.count(CheckoutSession.id))) == 1
    assert (
        sqlite_session.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.reference_type == "checkout_session",
                LedgerEntry.reference_id == first_session.id,
            )
        )
        == 1
    )


def test_create_payment_request_rejects_inactive_offer(sqlite_session):
    _, inactive = _create_offers(sqlite_session)

    with pytest.raises(PaymentRequestError):
        create_payment_request(
            sqlite_session,
            offer_id=inactive.id,
            channel="checkout",
            actor="agent:ryan",
            idempotency_key="payment-create-inactive",
        )

    assert sqlite_session.scalar(select(CheckoutSession)) is None


def test_create_payment_request_rejects_disallowed_channel(sqlite_session):
    active, _ = _create_offers(sqlite_session)

    with pytest.raises(PaymentRequestError):
        create_payment_request(
            sqlite_session,
            offer_id=active.id,
            channel="sms",
            actor="agent:ryan",
            idempotency_key="payment-create-disallowed-channel",
        )

    assert sqlite_session.scalar(select(CheckoutSession)) is None


def test_create_payment_request_accepts_injected_production_provider(sqlite_session):
    active, _ = _create_offers(sqlite_session)
    provider = FakeCheckoutProvider()

    checkout_session = create_payment_request(
        sqlite_session,
        offer_id=active.id,
        channel="checkout",
        actor="agent:ryan",
        idempotency_key="payment-create-provider",
        provider=provider,
    )

    assert checkout_session.payment_provider == "fake"
    assert checkout_session.provider_reference == "fake-checkout-001"
    assert provider.requests[0].offer_name == "MVP Support Sprint"
    assert provider.requests[0].idempotency_key == "payment-create-provider"


def test_confirm_payment_verifies_provider_event_and_persists_payment(
    sqlite_session,
):
    active, _ = _create_offers(sqlite_session)
    checkout_session = create_payment_request(
        sqlite_session,
        offer_id=active.id,
        channel="checkout",
        actor="agent:ryan",
        idempotency_key="payment-create-001",
    )

    payment = confirm_payment(
        sqlite_session,
        checkout_provider_reference=checkout_session.provider_reference,
        provider_event_id="provider-event-001",
        amount=Decimal("100.00"),
        currency="USD",
        status="settled",
        verification_token="simulated-valid",
        actor="system:webhook",
        idempotency_key="payment-confirm-001",
    )

    assert payment.checkout_session_id == checkout_session.id
    assert payment.status == "settled"
    assert payment.provider_reference == "provider-event-001"
    assert payment.settlement_time is not None
    assert checkout_session.status == "settled"
    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reference_type == "payment",
            LedgerEntry.reference_id == payment.id,
            LedgerEntry.type == "audit.payment.confirmed",
        )
    )
    assert audit_entry is not None


def test_confirm_payment_duplicate_provider_event_returns_existing_payment(
    sqlite_session,
):
    active, _ = _create_offers(sqlite_session)
    checkout_session = create_payment_request(
        sqlite_session,
        offer_id=active.id,
        channel="checkout",
        actor="agent:ryan",
        idempotency_key="payment-create-001",
    )
    payload = {
        "checkout_provider_reference": checkout_session.provider_reference,
        "provider_event_id": "provider-event-001",
        "amount": Decimal("100.00"),
        "currency": "USD",
        "status": "settled",
        "verification_token": "simulated-valid",
        "actor": "system:webhook",
        "idempotency_key": "payment-confirm-001",
    }

    first_payment = confirm_payment(sqlite_session, **payload)
    second_payment = confirm_payment(sqlite_session, **payload)

    assert second_payment.id == first_payment.id
    assert sqlite_session.scalar(select(func.count(Payment.id))) == 1
    assert (
        sqlite_session.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.reference_type == "payment",
                LedgerEntry.reference_id == first_payment.id,
            )
        )
        == 1
    )


def test_confirm_payment_invalid_verification_logs_alert_without_payment(
    sqlite_session,
):
    active, _ = _create_offers(sqlite_session)
    checkout_session = create_payment_request(
        sqlite_session,
        offer_id=active.id,
        channel="checkout",
        actor="agent:ryan",
        idempotency_key="payment-create-001",
    )

    with pytest.raises(PaymentConfirmationError):
        confirm_payment(
            sqlite_session,
            checkout_provider_reference=checkout_session.provider_reference,
            provider_event_id="provider-event-invalid-token",
            amount=Decimal("100.00"),
            currency="USD",
            status="settled",
            verification_token="bad-token",
            actor="system:webhook",
            idempotency_key="payment-confirm-invalid-token",
        )

    assert sqlite_session.scalar(select(Payment)) is None
    alert_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.type == "alert.invalid_payment_confirmation"
        )
    )
    assert alert_entry is not None
    assert alert_entry.metadata_["provider_event_id"] == "provider-event-invalid-token"


def test_confirm_payment_amount_mismatch_logs_alert_without_payment(
    sqlite_session,
):
    active, _ = _create_offers(sqlite_session)
    checkout_session = create_payment_request(
        sqlite_session,
        offer_id=active.id,
        channel="checkout",
        actor="agent:ryan",
        idempotency_key="payment-create-001",
    )

    with pytest.raises(PaymentConfirmationError):
        confirm_payment(
            sqlite_session,
            checkout_provider_reference=checkout_session.provider_reference,
            provider_event_id="provider-event-wrong-amount",
            amount=Decimal("99.00"),
            currency="USD",
            status="settled",
            verification_token="simulated-valid",
            actor="system:webhook",
            idempotency_key="payment-confirm-wrong-amount",
        )

    assert sqlite_session.scalar(select(Payment)) is None
    alert_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.type == "alert.invalid_payment_confirmation"
        )
    )
    assert alert_entry is not None
    assert "amount or currency mismatch" in alert_entry.metadata_["reason"]
