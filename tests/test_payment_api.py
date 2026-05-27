from decimal import Decimal
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.config import (
    BusinessModelConfig,
    CategoryBudgetConfig,
    DemandSourceConfig,
    OfferConfig,
    RevenueAllocationConfig,
    Settings,
    SpendThresholdConfig,
    TimeWindowConfig,
    VendorConfig,
)
from ryan.db import Base, create_database_engine, get_session
from ryan.models import BucketAllocation, CheckoutSession, Offer, Payment, PolicyDecision, PolicyRule, Wallet


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'payment-api.sqlite3'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = create_app()

    def override_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), Session()


def _production_client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'stripe-webhook.sqlite3'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = create_app(_production_settings())

    def override_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), Session()


def _production_settings():
    return Settings(
        environment="production",
        database_url="postgresql+psycopg://prod.example/ryan",
        business_model=BusinessModelConfig(
            name="Operator approved production business",
            objective="Serve one explicitly approved production niche",
            production_ready=True,
        ),
        offer_catalog=[
            OfferConfig(
                id="prod-offer-001",
                name="Approved production offer",
                price=Decimal("100.00"),
                currency="USD",
                status="active",
                allowed_channels=["checkout"],
            )
        ],
        approved_demand_sources=[
            DemandSourceConfig(name="manual", kind="manual_import", status="approved")
        ],
        vendor_allowlist=[
            VendorConfig(name="vendor", categories=["software"], status="approved")
        ],
        spend_threshold=SpendThresholdConfig(
            per_transaction_cap=Decimal("25.00"),
            currency="USD",
        ),
        category_budgets=[
            CategoryBudgetConfig(
                category="software",
                limit=Decimal("100.00"),
                currency="USD",
                period="monthly",
            )
        ],
        spend_time_windows=[
            TimeWindowConfig(
                name="business-hours",
                start_hour_utc=9,
                end_hour_utc=17,
                days=["mon"],
            )
        ],
        revenue_floor=Decimal("0.00"),
        reserve_minimum=Decimal("0.00"),
        revenue_allocation=RevenueAllocationConfig(
            wallet_percentages={"revenue": Decimal("20"), "operating": Decimal("60"), "reserve": Decimal("20")}
        ),
        operator_api_key="operator-production-key-32-bytes",
        agent_api_key="agent-production-key-32-bytes",
        payment_rail="stripe",
        stripe_api_key="sk_live_test_value_for_validation",
        stripe_webhook_secret="whsec_test_secret",
        stripe_success_url="https://api.agentryan.blog/payments/success",
        stripe_cancel_url="https://api.agentryan.blog/payments/cancel",
        secret_backend="aws_secrets_manager",
        hosting_environment="aws_ecs",
        _env_file=None,
    )


def _create_offer(session):
    offer = Offer(
        id="offer-active",
        name="MVP Support Sprint",
        price=Decimal("100.00"),
        currency="USD",
        status="active",
        allowed_channels=["checkout"],
    )
    session.add(offer)
    session.commit()
    return offer


def _create_wallets_and_allocation_policy(session):
    wallets = [
        Wallet(
            type="revenue",
            balance=Decimal("0.00"),
            currency="USD",
            locked=False,
            limits={},
        ),
        Wallet(
            type="operating",
            balance=Decimal("0.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "0.00"},
        ),
        Wallet(
            type="reserve",
            balance=Decimal("0.00"),
            currency="USD",
            locked=False,
            limits={},
        ),
    ]
    session.add_all(wallets)
    session.add(
        PolicyRule(
            type="revenue_allocation",
            status="active",
            configuration={
                "wallet_percentages": {
                    "revenue": "20",
                    "operating": "60",
                    "reserve": "20",
                }
            },
            priority=1,
            created_by_actor="operator:test",
        )
    )
    session.commit()
    return {wallet.type: wallet for wallet in wallets}


def _create_stripe_checkout_session(session):
    checkout = CheckoutSession(
        offer_id="offer-active",
        status="created",
        payment_provider="stripe",
        provider_reference="cs_live_123",
        checkout_url="https://checkout.stripe.com/c/pay/cs_live_123",
        amount=Decimal("100.00"),
        currency="USD",
        idempotency_key="stripe-create-001",
    )
    session.add(checkout)
    session.commit()
    return checkout


def _stripe_payload(event_id="evt_checkout_completed"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_live_123",
                "amount_total": 10000,
                "currency": "usd",
                "payment_status": "paid",
            }
        },
    }


def _stripe_signature(payload: bytes, secret: str, timestamp: int | None = None):
    timestamp = timestamp or int(time.time())
    signed_payload = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _create_checkout(client, offer_id="offer-active"):
    response = client.post(
        "/api/payments/create",
        json={
            "offer_id": offer_id,
            "channel": "checkout",
            "actor": "agent:ryan",
            "idempotency_key": "payment-create-api-001",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_payments_api_creates_and_gets_payment_request(tmp_path):
    client, session = _client_with_session(tmp_path)
    offer = _create_offer(session)

    payload = _create_checkout(client, offer.id)

    assert payload["status"] == "created"
    assert payload["offer_id"] == offer.id
    assert payload["amount"] == "100.00"

    get_response = client.get(f"/api/payments/{payload['id']}")

    assert get_response.status_code == 200
    assert get_response.json()["kind"] == "checkout_session"
    session.close()


def test_payments_api_confirm_settlement_allocates_revenue_once(tmp_path):
    client, session = _client_with_session(tmp_path)
    _create_offer(session)
    wallets = _create_wallets_and_allocation_policy(session)
    checkout = _create_checkout(client)

    response = client.post(
        "/api/payments/confirm",
        json={
            "checkout_provider_reference": checkout["provider_reference"],
            "provider_event_id": "provider-event-api-001",
            "amount": "100.00",
            "currency": "USD",
            "status": "settled",
            "verification_token": "simulated-valid",
            "actor": "system:webhook",
            "idempotency_key": "payment-confirm-api-001",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "settled"
    session.expire_all()
    assert session.get(Wallet, wallets["revenue"].id).balance == Decimal("20.00")
    assert session.get(Wallet, wallets["operating"].id).balance == Decimal("60.00")
    assert session.get(Wallet, wallets["reserve"].id).balance == Decimal("20.00")
    assert session.scalar(select(func.count(BucketAllocation.id))) == 3

    replay_response = client.post(
        "/api/payments/confirm",
        json={
            "checkout_provider_reference": checkout["provider_reference"],
            "provider_event_id": "provider-event-api-001",
            "amount": "100.00",
            "currency": "USD",
            "status": "settled",
            "verification_token": "simulated-valid",
            "actor": "system:webhook",
            "idempotency_key": "payment-confirm-api-001",
        },
    )

    assert replay_response.status_code == 200
    session.expire_all()
    assert session.get(Wallet, wallets["revenue"].id).balance == Decimal("20.00")
    assert session.get(Wallet, wallets["operating"].id).balance == Decimal("60.00")
    assert session.get(Wallet, wallets["reserve"].id).balance == Decimal("20.00")
    assert session.scalar(select(func.count(BucketAllocation.id))) == 3
    assert session.scalar(select(func.count(Payment.id))) == 1
    session.close()


def test_payments_api_invalid_confirmation_does_not_allocate(tmp_path):
    client, session = _client_with_session(tmp_path)
    _create_offer(session)
    wallets = _create_wallets_and_allocation_policy(session)
    checkout = _create_checkout(client)

    response = client.post(
        "/api/payments/confirm",
        json={
            "checkout_provider_reference": checkout["provider_reference"],
            "provider_event_id": "provider-event-api-invalid",
            "amount": "99.00",
            "currency": "USD",
            "status": "settled",
            "verification_token": "simulated-valid",
            "actor": "system:webhook",
            "idempotency_key": "payment-confirm-api-invalid",
        },
    )

    assert response.status_code == 400
    session.expire_all()
    assert session.get(Wallet, wallets["revenue"].id).balance == Decimal("0.00")
    assert session.get(Wallet, wallets["operating"].id).balance == Decimal("0.00")
    assert session.get(Wallet, wallets["reserve"].id).balance == Decimal("0.00")
    assert session.scalar(select(Payment)) is None
    session.close()


def test_stripe_webhook_settles_signed_checkout_completion_without_ryan_api_key(tmp_path):
    client, session = _production_client_with_session(tmp_path)
    _create_offer(session)
    wallets = _create_wallets_and_allocation_policy(session)
    _create_stripe_checkout_session(session)
    payload = json.dumps(_stripe_payload(), separators=(",", ":")).encode()

    response = client.post(
        "/api/payments/stripe/webhook",
        content=payload,
        headers={
            "Stripe-Signature": _stripe_signature(payload, "whsec_test_secret"),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    session.expire_all()
    assert session.scalar(select(func.count(Payment.id))) == 1
    payment = session.scalar(select(Payment))
    assert payment.payment_provider == "stripe"
    assert payment.provider_reference == "evt_checkout_completed"
    assert payment.status == "settled"
    assert session.get(Wallet, wallets["revenue"].id).balance == Decimal("20.00")
    assert session.get(Wallet, wallets["operating"].id).balance == Decimal("60.00")
    assert session.get(Wallet, wallets["reserve"].id).balance == Decimal("20.00")
    assert session.scalar(select(func.count(BucketAllocation.id))) == 3
    session.close()


def test_stripe_webhook_rejects_invalid_signature_without_mutation(tmp_path):
    client, session = _production_client_with_session(tmp_path)
    _create_offer(session)
    wallets = _create_wallets_and_allocation_policy(session)
    _create_stripe_checkout_session(session)
    payload = json.dumps(_stripe_payload(), separators=(",", ":")).encode()

    response = client.post(
        "/api/payments/stripe/webhook",
        content=payload,
        headers={
            "Stripe-Signature": "t=123,v1=invalid",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    session.expire_all()
    assert session.scalar(select(Payment)) is None
    assert session.get(Wallet, wallets["revenue"].id).balance == Decimal("0.00")
    assert session.get(Wallet, wallets["operating"].id).balance == Decimal("0.00")
    assert session.get(Wallet, wallets["reserve"].id).balance == Decimal("0.00")
    session.close()


def test_payments_api_refund_requires_approved_policy_decision(tmp_path):
    client, session = _client_with_session(tmp_path)
    _create_offer(session)
    _create_wallets_and_allocation_policy(session)
    checkout = _create_checkout(client)
    confirm_response = client.post(
        "/api/payments/confirm",
        json={
            "checkout_provider_reference": checkout["provider_reference"],
            "provider_event_id": "provider-event-api-001",
            "amount": "100.00",
            "currency": "USD",
            "status": "settled",
            "verification_token": "simulated-valid",
            "actor": "system:webhook",
            "idempotency_key": "payment-confirm-api-001",
        },
    )
    payment_id = confirm_response.json()["id"]

    response = client.post(
        "/api/payments/refund",
        json={
            "payment_id": payment_id,
            "amount": "10.00",
            "currency": "USD",
            "actor": "operator:test",
            "reason": "customer requested refund",
            "policy_decision_id": "missing-policy-decision",
            "idempotency_key": "refund-api-missing-policy",
        },
    )

    assert response.status_code == 403
    assert (
        session.scalar(
            select(func.count(Payment.id)).where(Payment.source == "refund")
        )
        == 0
    )
    session.close()


def test_payments_api_creates_policy_approved_refund_idempotently(tmp_path):
    client, session = _client_with_session(tmp_path)
    _create_offer(session)
    _create_wallets_and_allocation_policy(session)
    checkout = _create_checkout(client)
    confirm_response = client.post(
        "/api/payments/confirm",
        json={
            "checkout_provider_reference": checkout["provider_reference"],
            "provider_event_id": "provider-event-api-001",
            "amount": "100.00",
            "currency": "USD",
            "status": "settled",
            "verification_token": "simulated-valid",
            "actor": "system:webhook",
            "idempotency_key": "payment-confirm-api-001",
        },
    )
    payment_id = confirm_response.json()["id"]
    decision = PolicyDecision(
        action_type="refund",
        decision="approve",
        reason="operator approved refund",
        rule_results={"operator_review": {"decision": "approve"}},
        request_reference_type="payment",
        request_reference_id=payment_id,
        actor="operator:test",
    )
    session.add(decision)
    session.commit()
    payload = {
        "payment_id": payment_id,
        "amount": "10.00",
        "currency": "USD",
        "actor": "operator:test",
        "reason": "customer requested refund",
        "policy_decision_id": decision.id,
        "idempotency_key": "refund-api-approved",
    }

    response = client.post("/api/payments/refund", json=payload)
    replay_response = client.post("/api/payments/refund", json=payload)

    assert response.status_code == 201
    assert replay_response.status_code == 201
    assert replay_response.json()["id"] == response.json()["id"]
    assert response.json()["status"] == "refunded"
    assert response.json()["amount"] == "-10.00"
    assert (
        session.scalar(
            select(func.count(Payment.id)).where(Payment.source == "refund")
        )
        == 1
    )
    session.close()
