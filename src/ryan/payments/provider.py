from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4


@dataclass(frozen=True)
class ProviderCheckoutRequest:
    offer_id: str
    amount: Decimal
    currency: str
    channel: str


@dataclass(frozen=True)
class ProviderCheckoutResult:
    provider_name: str
    provider_reference: str
    checkout_url: str


@dataclass(frozen=True)
class ProviderConfirmationRequest:
    provider_event_id: str
    amount: Decimal
    currency: str
    status: str
    verification_token: str


@dataclass(frozen=True)
class ProviderConfirmationResult:
    provider_event_id: str
    amount: Decimal
    currency: str
    status: str
    verified: bool


class SimulatedPaymentProvider:
    name = "simulated"

    def create_checkout(
        self,
        request: ProviderCheckoutRequest,
    ) -> ProviderCheckoutResult:
        provider_reference = f"simulated-checkout-{uuid4()}"
        return ProviderCheckoutResult(
            provider_name=self.name,
            provider_reference=provider_reference,
            checkout_url=f"https://payments.local/checkout/{provider_reference}",
        )

    def verify_confirmation(
        self,
        request: ProviderConfirmationRequest,
    ) -> ProviderConfirmationResult:
        return ProviderConfirmationResult(
            provider_event_id=request.provider_event_id,
            amount=request.amount,
            currency=request.currency,
            status=request.status,
            verified=request.verification_token == "simulated-valid",
        )


__all__ = [
    "ProviderCheckoutRequest",
    "ProviderCheckoutResult",
    "ProviderConfirmationRequest",
    "ProviderConfirmationResult",
    "SimulatedPaymentProvider",
]
