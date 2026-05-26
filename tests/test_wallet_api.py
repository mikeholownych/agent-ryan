from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.db import Base, create_database_engine, get_session
from ryan.models import PolicyDecision, Wallet, WalletTransfer


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'wallet-api.sqlite3'}")
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


def _create_wallets(session):
    wallets = [
        Wallet(
            type="revenue",
            balance=Decimal("100.00"),
            currency="USD",
            locked=False,
            limits={},
        ),
        Wallet(
            type="operating",
            balance=Decimal("50.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "5.00"},
        ),
        Wallet(
            type="reserve",
            balance=Decimal("25.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "10.00"},
        ),
    ]
    session.add_all(wallets)
    session.commit()
    return {wallet.type: wallet for wallet in wallets}


def _approved_transfer_policy(session, *, reference_id="wallet-transfer-api-001"):
    decision = PolicyDecision(
        action_type="wallet_transfer",
        decision="approve",
        reason="operator approved wallet transfer",
        rule_results={"operator_review": {"decision": "approve"}},
        request_reference_type="wallet_transfer",
        request_reference_id=reference_id,
        actor="operator:test",
    )
    session.add(decision)
    session.commit()
    return decision


def test_wallets_api_lists_mvp_wallets(tmp_path):
    client, session = _client_with_session(tmp_path)
    _create_wallets(session)

    response = client.get("/api/wallets")

    assert response.status_code == 200
    assert [wallet["type"] for wallet in response.json()] == [
        "revenue",
        "operating",
        "reserve",
    ]
    assert response.json()[1]["balance"] == "50.00"
    session.close()


def test_wallets_api_freezes_and_unfreezes_wallet(tmp_path):
    client, session = _client_with_session(tmp_path)
    wallets = _create_wallets(session)

    freeze_response = client.post(
        "/api/wallets/freeze",
        json={
            "wallet_id": wallets["operating"].id,
            "actor": "operator:test",
            "reason": "manual review",
        },
    )

    assert freeze_response.status_code == 200
    assert freeze_response.json()["locked"] is True

    unfreeze_response = client.post(
        "/api/wallets/unfreeze",
        json={
            "wallet_id": wallets["operating"].id,
            "actor": "operator:test",
            "reason": "review complete",
        },
    )

    assert unfreeze_response.status_code == 200
    assert unfreeze_response.json()["locked"] is False
    session.close()


def test_wallets_api_executes_policy_approved_transfer(tmp_path):
    client, session = _client_with_session(tmp_path)
    wallets = _create_wallets(session)
    decision = _approved_transfer_policy(session)

    response = client.post(
        "/api/wallets/transfer",
        json={
            "source_wallet_id": wallets["operating"].id,
            "destination_wallet_id": wallets["reserve"].id,
            "amount": "10.00",
            "currency": "USD",
            "actor": "operator:test",
            "reason": "increase reserve",
            "policy_decision_id": decision.id,
            "idempotency_key": "wallet-transfer-api-001",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "executed"
    assert payload["amount"] == "10.00"

    session.expire_all()
    operating = session.get(Wallet, wallets["operating"].id)
    reserve = session.get(Wallet, wallets["reserve"].id)
    assert operating.balance == Decimal("40.00")
    assert reserve.balance == Decimal("35.00")
    session.close()


def test_wallets_api_rejects_transfer_without_approved_policy(tmp_path):
    client, session = _client_with_session(tmp_path)
    wallets = _create_wallets(session)

    response = client.post(
        "/api/wallets/transfer",
        json={
            "source_wallet_id": wallets["operating"].id,
            "destination_wallet_id": wallets["reserve"].id,
            "amount": "10.00",
            "currency": "USD",
            "actor": "operator:test",
            "reason": "missing approval",
            "policy_decision_id": "missing-policy-decision",
            "idempotency_key": "wallet-transfer-policy-missing",
        },
    )

    assert response.status_code == 403
    assert session.scalar(select(WalletTransfer)) is None
    session.expire_all()
    assert session.get(Wallet, wallets["operating"].id).balance == Decimal("50.00")
    assert session.get(Wallet, wallets["reserve"].id).balance == Decimal("25.00")
    session.close()
