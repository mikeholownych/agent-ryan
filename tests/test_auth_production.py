from decimal import Decimal

from fastapi.testclient import TestClient

from ryan.app import create_app
from ryan.config import (
    AllocationTarget,
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


def _production_settings():
    return Settings(
        environment="production",
        database_url="sqlite:///:memory:",
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
                name="approved-source",
                kind="manual_import",
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
        revenue_floor=Decimal("500.00"),
        reserve_minimum=Decimal("250.00"),
        revenue_allocation=RevenueAllocationConfig(
            wallet_percentages={
                AllocationTarget.REVENUE: Decimal("50"),
                AllocationTarget.OPERATING: Decimal("30"),
                AllocationTarget.RESERVE: Decimal("20"),
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


def test_production_requires_authentication_for_operator_routes():
    client = TestClient(create_app(_production_settings()))

    response = client.get("/api/operator/console")

    assert response.status_code == 401


def test_production_allows_operator_role_with_operator_key():
    client = TestClient(create_app(_production_settings()))

    response = client.get(
        "/api/operator/console",
        headers={
            "X-Ryan-Role": "operator",
            "X-Ryan-Api-Key": "operator-production-key-32-bytes",
        },
    )

    assert response.status_code != 401
    assert response.status_code != 403


def test_production_blocks_agent_key_from_operator_routes():
    client = TestClient(create_app(_production_settings()))

    response = client.get(
        "/api/operator/console",
        headers={
            "X-Ryan-Role": "agent",
            "X-Ryan-Api-Key": "agent-production-key-32-bytes",
        },
    )

    assert response.status_code == 403


def test_production_allows_agent_role_for_agent_plan():
    client = TestClient(create_app(_production_settings()))

    response = client.post(
        "/api/plan",
        json={"actor": "agent:ryan", "objective": "plan only"},
        headers={
            "X-Ryan-Role": "agent",
            "X-Ryan-Api-Key": "agent-production-key-32-bytes",
        },
    )

    assert response.status_code != 401
    assert response.status_code != 403
