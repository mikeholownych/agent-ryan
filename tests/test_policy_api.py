from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.db import Base, create_database_engine, get_session
from ryan.models import Wallet
from ryan.policy import create_policy_rule


def _create_required_policy_state(session):
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
            limits={},
        ),
        Wallet(
            type="reserve",
            balance=Decimal("25.00"),
            currency="USD",
            locked=False,
            limits={},
        ),
    ]
    session.add_all(wallets)
    create_policy_rule(
        session,
        rule_type="vendor_allowlist",
        configuration={
            "vendors": [
                {
                    "name": "sandbox-approved-vendor",
                    "categories": ["software"],
                    "status": "approved",
                }
            ]
        },
        actor="operator:test",
        priority=1,
    )
    create_policy_rule(
        session,
        rule_type="spend_threshold",
        configuration={"per_transaction_cap": "25.00", "currency": "USD"},
        actor="operator:test",
        priority=2,
    )
    create_policy_rule(
        session,
        rule_type="category_budget",
        configuration={
            "budgets": [
                {
                    "category": "software",
                    "limit": "100.00",
                    "currency": "USD",
                    "period": "monthly",
                }
            ]
        },
        actor="operator:test",
        priority=3,
    )
    create_policy_rule(
        session,
        rule_type="time_window",
        configuration={
            "windows": [
                {
                    "name": "weekday-business-hours",
                    "start_hour_utc": 9,
                    "end_hour_utc": 17,
                    "days": ["mon", "tue", "wed", "thu", "fri"],
                    "timezone": "UTC",
                }
            ]
        },
        actor="operator:test",
        priority=4,
    )
    create_policy_rule(
        session,
        rule_type="revenue_floor",
        configuration={"amount": "10.00", "currency": "USD"},
        actor="operator:test",
        priority=5,
    )
    create_policy_rule(
        session,
        rule_type="reserve_minimum",
        configuration={"amount": "5.00", "currency": "USD"},
        actor="operator:test",
        priority=6,
    )
    session.commit()


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'policy-api.sqlite3'}")
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


def test_policy_rules_api_creates_and_lists_rules(tmp_path):
    client, session = _client_with_session(tmp_path)

    create_response = client.post(
        "/api/policy/rules",
        json={
            "type": "vendor_allowlist",
            "status": "active",
            "priority": 1,
            "actor": "operator:test",
            "configuration": {"vendors": []},
        },
    )

    assert create_response.status_code == 201
    assert create_response.json()["type"] == "vendor_allowlist"

    list_response = client.get("/api/policy/rules")

    assert list_response.status_code == 200
    assert [rule["type"] for rule in list_response.json()] == ["vendor_allowlist"]
    session.close()


def test_policy_evaluate_api_persists_decision_with_reason(tmp_path):
    client, session = _client_with_session(tmp_path)
    _create_required_policy_state(session)

    response = client.post(
        "/api/policy/evaluate",
        json={
            "action_type": "expense_execute",
            "vendor": "sandbox-approved-vendor",
            "category": "software",
            "amount": "10.00",
            "currency": "USD",
            "actor": "agent:ryan",
            "request_reference_type": "expense",
            "request_reference_id": "expense-api-001",
            "source_wallet_type": "operating",
            "irreversible": False,
            "timestamp": "2026-05-25T12:00:00+00:00",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["decision"] == "approve"
    assert payload["reason"] == "approved by deterministic policy evaluation"
    assert payload["request_reference_id"] == "expense-api-001"
    session.close()
