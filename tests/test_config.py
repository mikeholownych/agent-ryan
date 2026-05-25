from decimal import Decimal

import pytest
from pydantic import ValidationError

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


def test_sandbox_defaults_include_complete_non_production_policy_config():
    settings = Settings(_env_file=None)

    assert settings.environment == "sandbox"
    assert settings.business_model.name
    assert settings.business_model.production_ready is False

    assert len(settings.offer_catalog) == 1
    offer = settings.offer_catalog[0]
    assert offer.status == "active"
    assert offer.price > Decimal("0")
    assert offer.allowed_channels

    assert len(settings.approved_demand_sources) == 1
    assert settings.approved_demand_sources[0].status == "approved"

    assert len(settings.vendor_allowlist) == 1
    assert settings.vendor_allowlist[0].status == "approved"

    assert settings.spend_threshold.per_transaction_cap > Decimal("0")
    assert len(settings.category_budgets) == 1
    assert settings.category_budgets[0].limit > Decimal("0")
    assert len(settings.spend_time_windows) == 1
    assert settings.spend_time_windows[0].timezone == "UTC"
    assert settings.revenue_floor >= Decimal("0")
    assert settings.reserve_minimum >= Decimal("0")

    assert settings.revenue_allocation.wallet_percentages == {
        "revenue": Decimal("50"),
        "operating": Decimal("30"),
        "reserve": Decimal("20"),
    }


def test_revenue_allocation_requires_all_mvp_wallets_and_exactly_100_percent():
    RevenueAllocationConfig(
        wallet_percentages={
            "revenue": Decimal("50"),
            "operating": Decimal("30"),
            "reserve": Decimal("20"),
        }
    )

    with pytest.raises(ValidationError, match="revenue, operating, and reserve"):
        RevenueAllocationConfig(
            wallet_percentages={
                "revenue": Decimal("70"),
                "operating": Decimal("30"),
            }
        )

    with pytest.raises(ValidationError, match="total 100"):
        RevenueAllocationConfig(
            wallet_percentages={
                "revenue": Decimal("70"),
                "operating": Decimal("20"),
                "reserve": Decimal("20"),
            }
        )


def test_production_environment_fails_closed_when_launch_critical_policy_fields_are_missing():
    with pytest.raises(ValidationError, match="production requires explicit"):
        Settings(environment="production", _env_file=None)


def test_sandbox_can_use_defaults_while_production_requires_explicit_values():
    sandbox = Settings(_env_file=None)

    assert sandbox.environment == "sandbox"

    production = Settings(
        environment="production",
        business_model=BusinessModelConfig(
            name="Operator approved production business",
            objective="Serve one explicitly approved production niche",
            production_ready=True,
        ),
        offer_catalog=[
            OfferConfig(
                id="prod-offer-001",
                name="Approved production offer",
                price=Decimal("250.00"),
                currency="USD",
                status="active",
                allowed_channels=["approved_checkout"],
            )
        ],
        approved_demand_sources=[
            DemandSourceConfig(
                name="approved-production-source",
                kind="manual_import",
                status="approved",
            )
        ],
        vendor_allowlist=[
            VendorConfig(
                name="approved-production-vendor",
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
        _env_file=None,
    )

    assert production.environment == "production"
