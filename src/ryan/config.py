from functools import lru_cache
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AllocationTarget(str, Enum):
    REVENUE = "revenue"
    OPERATING = "operating"
    RESERVE = "reserve"


class BusinessModelConfig(BaseModel):
    name: str
    objective: str
    production_ready: bool = False


class OfferConfig(BaseModel):
    id: str
    name: str
    price: Decimal = Field(gt=Decimal("0"))
    currency: str = "USD"
    status: Literal["active", "inactive"] = "active"
    allowed_channels: list[str] = Field(min_length=1)


class DemandSourceConfig(BaseModel):
    name: str
    kind: str
    status: Literal["approved", "inactive"] = "approved"


class VendorConfig(BaseModel):
    name: str
    categories: list[str] = Field(min_length=1)
    status: Literal["approved", "inactive"] = "approved"


class SpendThresholdConfig(BaseModel):
    per_transaction_cap: Decimal = Field(gt=Decimal("0"))
    currency: str = "USD"


class CategoryBudgetConfig(BaseModel):
    category: str
    limit: Decimal = Field(gt=Decimal("0"))
    currency: str = "USD"
    period: Literal["daily", "weekly", "monthly"]


class TimeWindowConfig(BaseModel):
    name: str
    start_hour_utc: int = Field(ge=0, le=23)
    end_hour_utc: int = Field(ge=1, le=24)
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = Field(
        min_length=1
    )
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_hour_window(self) -> "TimeWindowConfig":
        if self.start_hour_utc >= self.end_hour_utc:
            raise ValueError("time window start_hour_utc must be before end_hour_utc")
        return self


class RevenueAllocationConfig(BaseModel):
    wallet_percentages: dict[str, Decimal]

    @field_validator("wallet_percentages", mode="before")
    @classmethod
    def normalize_wallet_keys(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                key.value if isinstance(key, AllocationTarget) else key: percentage
                for key, percentage in value.items()
            }
        return value

    @model_validator(mode="after")
    def validate_mvp_wallet_allocation(self) -> "RevenueAllocationConfig":
        required_wallets = {target.value for target in AllocationTarget}
        configured_wallets = set(self.wallet_percentages)
        if configured_wallets != required_wallets:
            raise ValueError(
                "revenue allocation must include revenue, operating, and reserve wallets"
            )

        if sum(self.wallet_percentages.values(), Decimal("0")) != Decimal("100"):
            raise ValueError("revenue allocation percentages must total 100 percent")

        for wallet, percentage in self.wallet_percentages.items():
            if percentage < Decimal("0"):
                raise ValueError(f"{wallet} allocation percentage cannot be negative")

        return self


def _default_business_model() -> BusinessModelConfig:
    return BusinessModelConfig(
        name="Sandbox micro-business",
        objective="Validate one bounded sandbox revenue loop",
        production_ready=False,
    )


def _default_offer_catalog() -> list[OfferConfig]:
    return [
        OfferConfig(
            id="sandbox-offer-001",
            name="Sandbox approved offer",
            price=Decimal("100.00"),
            currency="USD",
            status="active",
            allowed_channels=["sandbox_checkout"],
        )
    ]


def _default_demand_sources() -> list[DemandSourceConfig]:
    return [
        DemandSourceConfig(
            name="agentryan@agentmail.to",
            kind="agentmail_inbox",
            status="approved",
        )
    ]


def _default_vendor_allowlist() -> list[VendorConfig]:
    return [
        VendorConfig(
            name="sandbox-approved-vendor",
            categories=["software"],
            status="approved",
        )
    ]


def _default_spend_threshold() -> SpendThresholdConfig:
    return SpendThresholdConfig(
        per_transaction_cap=Decimal("25.00"),
        currency="USD",
    )


def _default_category_budgets() -> list[CategoryBudgetConfig]:
    return [
        CategoryBudgetConfig(
            category="software",
            limit=Decimal("100.00"),
            currency="USD",
            period="monthly",
        )
    ]


def _default_spend_time_windows() -> list[TimeWindowConfig]:
    return [
        TimeWindowConfig(
            name="sandbox-business-hours",
            start_hour_utc=9,
            end_hour_utc=17,
            days=["mon", "tue", "wed", "thu", "fri"],
        )
    ]


def _default_revenue_allocation() -> RevenueAllocationConfig:
    return RevenueAllocationConfig(
        wallet_percentages={
            AllocationTarget.REVENUE: Decimal("50"),
            AllocationTarget.OPERATING: Decimal("30"),
            AllocationTarget.RESERVE: Decimal("20"),
        }
    )


_PRODUCTION_REQUIRED_POLICY_FIELDS = {
    "business_model",
    "offer_catalog",
    "approved_demand_sources",
    "vendor_allowlist",
    "spend_threshold",
    "category_budgets",
    "spend_time_windows",
    "revenue_floor",
    "reserve_minimum",
    "revenue_allocation",
    "outbound_payment_rail",
    "outbound_payment_provider",
    "treasury_account_reference",
    "outbound_live_validation_approved",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RYAN_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: str = "ryan"
    environment: Literal["sandbox", "test", "production"] = "sandbox"
    database_url: str = Field(default="sqlite:///./ryan.sqlite3")
    business_model: BusinessModelConfig = Field(default_factory=_default_business_model)
    offer_catalog: list[OfferConfig] = Field(
        default_factory=_default_offer_catalog,
        min_length=1,
    )
    approved_demand_sources: list[DemandSourceConfig] = Field(
        default_factory=_default_demand_sources,
        min_length=1,
    )
    vendor_allowlist: list[VendorConfig] = Field(
        default_factory=_default_vendor_allowlist,
        min_length=1,
    )
    spend_threshold: SpendThresholdConfig = Field(
        default_factory=_default_spend_threshold
    )
    category_budgets: list[CategoryBudgetConfig] = Field(
        default_factory=_default_category_budgets,
        min_length=1,
    )
    spend_time_windows: list[TimeWindowConfig] = Field(
        default_factory=_default_spend_time_windows,
        min_length=1,
    )
    revenue_floor: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    reserve_minimum: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    revenue_allocation: RevenueAllocationConfig = Field(
        default_factory=_default_revenue_allocation
    )
    operator_api_key: str | None = None
    agent_api_key: str | None = None
    payment_rail: Literal["simulated", "stripe"] = "simulated"
    stripe_api_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_success_url: str | None = None
    stripe_cancel_url: str | None = None
    outbound_payment_rail: Literal["simulated", "bank", "treasury", "bill_pay"] = "simulated"
    outbound_payment_provider: str | None = None
    treasury_account_reference: str | None = None
    outbound_live_validation_approved: bool = False
    agentmail_inbox: str = "agentryan@agentmail.to"
    outbound_email_requires_draft: bool = True
    outbound_email_requires_review: bool = True
    outbound_email_requires_sanitization: bool = True
    outbound_email_requires_approval: bool = True
    secret_backend: Literal["environment", "aws_secrets_manager"] = "environment"
    hosting_environment: Literal["local", "container", "aws_ecs"] = "local"

    @model_validator(mode="after")
    def fail_closed_for_missing_production_policy(self) -> "Settings":
        if self.environment != "production":
            return self

        missing = sorted(
            field
            for field in _PRODUCTION_REQUIRED_POLICY_FIELDS
            if field not in self.model_fields_set
        )
        if missing:
            raise ValueError(
                "production requires explicit launch-critical policy configuration: "
                + ", ".join(missing)
            )

        if not self.business_model.production_ready:
            raise ValueError("production business model must be marked production_ready")

        if not self.operator_api_key or not self.agent_api_key:
            raise ValueError("production requires operator_api_key and agent_api_key")

        if self.payment_rail != "stripe":
            raise ValueError("production payment rail must be stripe")

        if (
            not self.stripe_api_key
            or not self.stripe_webhook_secret
            or not self.stripe_success_url
            or not self.stripe_cancel_url
        ):
            raise ValueError(
                "production requires Stripe API key, webhook secret, success URL, and cancel URL"
            )

        if self.outbound_payment_rail == "simulated":
            raise ValueError("production outbound_payment_rail must be bank, treasury, or bill_pay")

        if not self.outbound_payment_provider:
            raise ValueError("production requires outbound_payment_provider")

        if not self.treasury_account_reference:
            raise ValueError("production requires treasury_account_reference")

        if not self.outbound_live_validation_approved:
            raise ValueError("production requires operator-approved outbound live validation")

        if self.secret_backend == "environment":
            raise ValueError("production requires external secret_backend")

        if self.hosting_environment == "local":
            raise ValueError("production requires non-local hosting_environment")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "AllocationTarget",
    "BusinessModelConfig",
    "CategoryBudgetConfig",
    "DemandSourceConfig",
    "OfferConfig",
    "RevenueAllocationConfig",
    "Settings",
    "SpendThresholdConfig",
    "TimeWindowConfig",
    "VendorConfig",
    "get_settings",
]
