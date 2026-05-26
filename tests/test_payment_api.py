from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.db import Base, create_database_engine, get_session
from ryan.models import BucketAllocation, Offer, Payment, PolicyRule, Wallet


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
