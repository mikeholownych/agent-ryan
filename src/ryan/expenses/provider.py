from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import uuid4


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


__all__ = [
    "OutboundPaymentProvider",
    "OutboundPaymentRequest",
    "OutboundPaymentResult",
    "SimulatedOutboundPaymentProvider",
]
