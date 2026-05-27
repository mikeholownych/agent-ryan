from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from ryan.config import Settings


@dataclass(frozen=True)
class OutboundPaymentRequest:
    expense_id: str
    vendor: str
    category: str
    amount: Decimal
    currency: str
    rationale: str
    idempotency_key: str


@dataclass(frozen=True)
class OutboundPaymentResult:
    provider_name: str
    provider_reference: str
    status: str


class OutboundPaymentProvider(Protocol):
    name: str

    def submit_payment(self, request: OutboundPaymentRequest) -> OutboundPaymentResult:
        ...


class SimulatedOutboundPaymentProvider:
    name = "simulated_outbound"

    def submit_payment(self, request: OutboundPaymentRequest) -> OutboundPaymentResult:
        return OutboundPaymentResult(
            provider_name=self.name,
            provider_reference=f"simulated-outbound-{uuid4()}",
            status="submitted",
        )


class OutboundPaymentProviderConfigurationError(ValueError):
    """Raised when configured outbound payment rails are not executable."""


PRODUCTION_OUTBOUND_PROVIDER_FACTORIES = {}


def implemented_outbound_provider_names() -> frozenset[str]:
    return frozenset(PRODUCTION_OUTBOUND_PROVIDER_FACTORIES)


def outbound_provider_from_settings(settings: "Settings") -> OutboundPaymentProvider:
    if settings.environment != "production":
        return SimulatedOutboundPaymentProvider()

    provider_name = settings.outbound_payment_provider
    if not provider_name or provider_name not in PRODUCTION_OUTBOUND_PROVIDER_FACTORIES:
        raise OutboundPaymentProviderConfigurationError(
            "outbound payment provider must have an implemented production adapter"
        )
    return PRODUCTION_OUTBOUND_PROVIDER_FACTORIES[provider_name](settings)


__all__ = [
    "OutboundPaymentProvider",
    "OutboundPaymentProviderConfigurationError",
    "OutboundPaymentRequest",
    "OutboundPaymentResult",
    "SimulatedOutboundPaymentProvider",
    "implemented_outbound_provider_names",
    "outbound_provider_from_settings",
]
