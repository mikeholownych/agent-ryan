from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
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
from ryan.kill_switch import activate_kill_switch
from ryan.models import Agent, ExceptionRecord, ExpenseRequest, LedgerEntry, Offer, Wallet
from ryan.policy import create_policy_rule


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'agent-api.sqlite3'}")
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
    engine = create_database_engine(f"sqlite:///{tmp_path / 'agent-prod.sqlite3'}")
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
            name="Production business",
            objective="Serve approved production niche",
            production_ready=True,
        ),
        offer_catalog=[
            OfferConfig(
                id="prod-offer-001",
                name="Production offer",
                price=Decimal("250.00"),
                currency="USD",
                status="active",
                allowed_channels=["checkout"],
            )
        ],
        approved_demand_sources=[
            DemandSourceConfig(
                name="agentryan@agentmail.to",
                kind="agentmail_inbox",
                status="approved",
            )
        ],
        vendor_allowlist=[
            VendorConfig(
                name="approved-vendor",
                categories=["software"],
                status="approved",
            )
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
                days=["mon", "tue", "wed", "thu", "fri"],
            )
        ],
        revenue_floor=Decimal("10.00"),
        reserve_minimum=Decimal("5.00"),
        revenue_allocation=RevenueAllocationConfig(
            wallet_percentages={
                "revenue": Decimal("50"),
                "operating": Decimal("30"),
                "reserve": Decimal("20"),
            }
        ),
        operator_api_key="operator-production-key-32-bytes",
        agent_api_key="agent-production-key-32-bytes",
        payment_rail="stripe",
        stripe_api_key="sk_live_test_value_for_validation",
        stripe_webhook_secret="whsec_test_value_for_validation",
        stripe_success_url="https://example.com/success",
        stripe_cancel_url="https://example.com/cancel",
        outbound_payment_rail="bank",
        outbound_payment_provider="example-business-bank",
        treasury_account_reference="treasury-account-001",
        outbound_live_validation_approved=True,
        secret_backend="aws_secrets_manager",
        hosting_environment="container",
        _env_file=None,
    )


def _seed_agent_state(session):
    session.add(
        Agent(
            name="Ryan",
            status="active",
            current_objective="Sell the approved MVP offer",
            mode="sandbox",
        )
    )
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
                balance=Decimal("100.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
            Wallet(
                type="operating",
                balance=Decimal("100.00"),
                currency="USD",
                locked=False,
                limits={"minimum": "5.00"},
            ),
            Wallet(
                type="reserve",
                balance=Decimal("25.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
        ]
    )
    _seed_policy_rules(session)
    session.commit()


def _seed_policy_rules(session):
    create_policy_rule(
        session,
        rule_type="vendor_allowlist",
        configuration={
            "vendors": [
                {
                    "name": "approved-vendor",
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


def test_plan_api_is_read_only_and_persists_proposed_actions(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.post(
        "/api/plan",
        json={"actor": "agent:ryan", "objective": "Find one approved expense"},
    )

    assert response.status_code == 200
    assert response.json()["plan_id"] is not None
    assert response.json()["read_only"] is False
    assert response.json()["proposed_actions"]
    assert session.scalar(select(ExpenseRequest)) is None
    plan_entry = session.get(LedgerEntry, response.json()["plan_id"])
    assert plan_entry.type == "audit.agent.planned"
    session.close()


def test_execute_api_routes_expense_through_policy(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.post(
        "/api/execute",
        json={
            "action_type": "expense_request",
            "vendor": "approved-vendor",
            "category": "software",
            "amount": "10.00",
            "currency": "USD",
            "rationale": "required software subscription",
            "actor": "agent:ryan",
            "idempotency_key": "agent-expense-001",
            "timestamp": "2026-05-25T12:00:00+00:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "executed"
    expense = session.scalar(select(ExpenseRequest))
    assert expense.policy_status == "approved"
    assert expense.execution_status == "executed"
    session.close()


def test_production_execute_blocks_expense_when_outbound_provider_has_no_adapter(tmp_path):
    client, session = _production_client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.post(
        "/api/execute",
        headers={
            "X-Ryan-Role": "agent",
            "X-Ryan-Api-Key": "agent-production-key-32-bytes",
        },
        json={
            "action_type": "expense_request",
            "vendor": "approved-vendor",
            "category": "software",
            "amount": "10.00",
            "currency": "USD",
            "rationale": "required software subscription",
            "actor": "agent:ryan",
            "idempotency_key": "agent-prod-expense-no-adapter",
            "timestamp": "2026-05-25T12:00:00+00:00",
        },
    )

    assert response.status_code == 400
    assert "implemented production adapter" in response.json()["detail"]
    assert session.scalar(select(ExpenseRequest)) is None
    operating_wallet = session.scalar(select(Wallet).where(Wallet.type == "operating"))
    assert operating_wallet.balance == Decimal("100.00")
    session.close()


def test_execute_api_blocks_outbound_email_without_draft_controls(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.post(
        "/api/execute",
        json={
            "action_type": "email_send",
            "actor": "agent:ryan",
            "idempotency_key": "agent-email-001",
            "email_from": "agentryan@agentmail.to",
            "email_to": "prospect@example.com",
            "subject": "Approved offer",
            "body": "Would you like to buy this?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "blocked"
    assert payload["policy_status"] == "rejected"
    assert "draft" in payload["reason"]
    exception = session.scalar(select(ExceptionRecord))
    assert exception.type == "outbound_email_blocked"
    assert session.scalar(select(ExpenseRequest)) is None
    assert session.scalar(
        select(LedgerEntry).where(LedgerEntry.type == "audit.email.blocked")
    )
    session.close()


def test_execute_api_blocks_email_from_unapproved_identity(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.post(
        "/api/execute",
        json={
            "action_type": "email_reply",
            "actor": "agent:ryan",
            "idempotency_key": "agent-email-identity",
            "email_from": "other@agentmail.to",
            "email_to": "sender@example.com",
            "subject": "Re: question",
            "body": "Thanks.",
            "draft_status": "drafted",
            "review_status": "reviewed",
            "sanitize_status": "sanitized",
            "approval_status": "approved",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "blocked"
    assert "approved email identity" in response.json()["reason"]
    session.close()


def test_execute_api_respects_kill_switch_read_only_mode(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)
    activate_kill_switch(session, actor="operator:test", reason="pause execution")
    session.commit()

    plan_response = client.post(
        "/api/plan",
        json={"actor": "agent:ryan", "objective": "Plan only"},
    )
    execute_response = client.post(
        "/api/execute",
        json={
            "action_type": "expense_request",
            "vendor": "approved-vendor",
            "category": "software",
            "amount": "10.00",
            "currency": "USD",
            "rationale": "required software subscription",
            "actor": "agent:ryan",
            "idempotency_key": "agent-expense-kill-switch",
            "timestamp": "2026-05-25T12:00:00+00:00",
        },
    )

    assert plan_response.status_code == 200
    assert plan_response.json()["read_only"] is True
    assert execute_response.status_code == 200
    assert execute_response.json()["outcome"] == "blocked"
    exception = session.scalar(select(ExceptionRecord))
    assert exception.type == "kill_switch_blocked"
    session.close()


def test_status_api_returns_agent_console_state(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_objective"] == "Sell the approved MVP offer"
    assert payload["active_offers"][0]["id"] == "offer-active"
    assert payload["wallet_budget_state"]["operating"]["balance"] == "100.00"
    assert payload["kill_switch"]["active"] is False
    session.close()


def test_agent_console_api_returns_required_display_state(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_agent_state(session)

    response = client.get("/api/agent/console")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_objective"] == "Sell the approved MVP offer"
    assert payload["approved_offer_set"][0]["id"] == "offer-active"
    assert payload["allowed_spend"]["currency"] == "USD"
    assert payload["allowed_spend"]["available"] == "95.00"
    assert payload["budget_state"]["operating"]["balance"] == "100.00"
    assert payload["pending_tasks"] == []
    assert payload["kill_switch"]["active"] is False
    session.close()
