from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.db import Base, create_database_engine, get_session
from ryan.models import ExceptionRecord, LedgerEntry, Offer, PolicyRule, Wallet


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'bdd.sqlite3'}")
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


def _seed_business(session, *, operating_balance=Decimal("100.00")):
    session.add(
        Offer(
            id="offer-active",
            name="MVP Support Sprint",
            price=Decimal("100.00"),
            currency="USD",
            status="active",
            allowed_channels=["checkout"],
        )
    )
    session.add_all(
        [
            Wallet(
                type="revenue",
                balance=Decimal("0.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
            Wallet(
                type="operating",
                balance=operating_balance,
                currency="USD",
                locked=False,
                limits={"minimum": "5.00"},
            ),
            Wallet(
                type="reserve",
                balance=Decimal("0.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
        ]
    )
    _seed_policy(session)
    session.commit()


def _seed_policy(session):
    rules = [
        (
            "vendor_allowlist",
            {
                "vendors": [
                    {
                        "name": "approved-vendor",
                        "categories": ["software"],
                        "status": "approved",
                    }
                ]
            },
        ),
        ("spend_threshold", {"per_transaction_cap": "25.00", "currency": "USD"}),
        (
            "category_budget",
            {
                "budgets": [
                    {
                        "category": "software",
                        "limit": "100.00",
                        "currency": "USD",
                        "period": "monthly",
                    }
                ]
            },
        ),
        (
            "time_window",
            {
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
        ),
        ("revenue_floor", {"amount": "0.00", "currency": "USD"}),
        ("reserve_minimum", {"amount": "5.00", "currency": "USD"}),
        (
            "revenue_allocation",
            {"wallet_percentages": {"revenue": "20", "operating": "60", "reserve": "20"}},
        ),
    ]
    for priority, (rule_type, configuration) in enumerate(rules, start=1):
        session.add(
            PolicyRule(
                type=rule_type,
                status="active",
                configuration=configuration,
                priority=priority,
                created_by_actor="operator:test",
            )
        )


def _purchase_offer(client):
    checkout = client.post(
        "/api/payments/create",
        json={
            "offer_id": "offer-active",
            "channel": "checkout",
            "actor": "agent:ryan",
            "idempotency_key": "bdd-payment-create",
        },
    ).json()
    return client.post(
        "/api/payments/confirm",
        json={
            "checkout_provider_reference": checkout["provider_reference"],
            "provider_event_id": "bdd-provider-event",
            "amount": "100.00",
            "currency": "USD",
            "status": "settled",
            "verification_token": "simulated-valid",
            "actor": "system:webhook",
            "idempotency_key": "bdd-payment-confirm",
        },
    )


def _execute_expense(client, *, vendor="approved-vendor", idempotency_key="bdd-expense"):
    return client.post(
        "/api/execute",
        json={
            "action_type": "expense_request",
            "vendor": vendor,
            "category": "software",
            "amount": "10.00",
            "currency": "USD",
            "rationale": "required software",
            "actor": "agent:ryan",
            "idempotency_key": idempotency_key,
            "timestamp": "2026-05-25T12:00:00+00:00",
        },
    )


def test_bdd_customer_purchases_approved_offer(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_business(session)

    response = _purchase_offer(client)

    assert response.status_code == 200
    session.expire_all()
    wallets = {wallet.type: wallet for wallet in session.scalars(select(Wallet))}
    assert wallets["revenue"].balance == Decimal("20.00")
    assert wallets["operating"].balance == Decimal("160.00")
    assert wallets["reserve"].balance == Decimal("20.00")
    assert session.scalar(
        select(LedgerEntry).where(LedgerEntry.type == "wallet.settlement.credit")
    )
    report = client.get(
        "/api/reports/daily",
        params={"date": "2026-05-26", "actor": "operator:test"},
    )
    assert report.status_code == 200
    assert client.get("/api/operator/console").json()["wallets"]
    session.close()


def test_bdd_agent_executes_allowlisted_expense_under_threshold(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_business(session)

    response = _execute_expense(client)

    assert response.status_code == 200
    assert response.json()["outcome"] == "executed"
    assert session.scalar(select(Wallet).where(Wallet.type == "operating")).balance == Decimal(
        "90.00"
    )
    assert session.scalar(select(LedgerEntry).where(LedgerEntry.type == "wallet.expense.debit"))
    session.close()


def test_bdd_agent_unapproved_expense_creates_exception_without_execution(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_business(session)

    response = _execute_expense(
        client,
        vendor="unapproved-vendor",
        idempotency_key="bdd-expense-unapproved",
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "blocked"
    assert session.scalar(select(ExceptionRecord)).type == "policy_rejection"
    assert session.scalar(select(Wallet).where(Wallet.type == "operating")).balance == Decimal(
        "100.00"
    )
    session.close()


def test_bdd_operator_kill_switch_blocks_execution(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_business(session)
    client.post(
        "/api/operator/kill-switch/activate",
        json={"actor": "operator:test", "reason": "stop"},
    )

    response = _execute_expense(client, idempotency_key="bdd-expense-kill-switch")

    assert response.status_code == 200
    assert response.json()["outcome"] == "blocked"
    assert session.scalar(select(ExceptionRecord)).type == "kill_switch_blocked"
    assert client.get("/api/agent/console").json()["kill_switch"]["active"] is True
    session.close()


def test_bdd_operating_budget_depletion_blocks_spend(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_business(session, operating_balance=Decimal("12.00"))

    response = _execute_expense(client, idempotency_key="bdd-expense-budget")

    assert response.status_code == 200
    assert response.json()["outcome"] == "blocked"
    assert session.scalar(select(ExceptionRecord)).type == "budget_exhaustion"
    assert session.scalar(select(LedgerEntry).where(LedgerEntry.type == "alert.budget_exhaustion"))
    session.close()
