from decimal import Decimal

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
from fastapi.testclient import TestClient

from ryan.app import create_app
from ryan.readiness.service import check_production_readiness


def _production_settings():
    return Settings(
        environment="production",
        database_url="postgresql+psycopg://ryan:secret@db.example.com/ryan",
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
        secret_backend="aws_secrets_manager",
        hosting_environment="container",
        _env_file=None,
    )


def test_production_readiness_rejects_sandbox_defaults():
    result = check_production_readiness(Settings(_env_file=None))

    assert result.ready is False
    assert "environment must be production" in result.blockers


def test_production_readiness_accepts_explicit_production_configuration():
    result = check_production_readiness(_production_settings())

    assert result.ready is True
    assert result.blockers == []
    assert result.decisions["payment_rail"] == "stripe"
    assert result.decisions["secret_backend"] == "aws_secrets_manager"
    assert result.decisions["hosting_environment"] == "container"


def test_production_readiness_endpoint_returns_ready_state_for_operator():
    settings = _production_settings()
    client = TestClient(create_app(settings))

    response = client.get(
        "/api/production/readiness",
        headers={
            "X-Ryan-Role": "operator",
            "X-Ryan-Api-Key": "operator-production-key-32-bytes",
        },
    )

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["blockers"] == []
