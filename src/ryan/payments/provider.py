from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import uuid4


STRIPE_CHECKOUT_SESSIONS_URL = "https://api.stripe.com/v1/checkout/sessions"


@dataclass(frozen=True)
class ProviderCheckoutRequest:
    offer_id: str
    amount: Decimal
    currency: str
    channel: str
    offer_name: str | None = None
    idempotency_key: str | None = None


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


class StripeHttpClient(Protocol):
    def post(self, url: str, *, data: dict[str, str], headers: dict[str, str], timeout: int):
        ...


class StripePaymentProvider:
    name = "stripe"

    def __init__(
        self,
        *,
        api_key: str,
        success_url: str,
        cancel_url: str,
        http_client: StripeHttpClient,
    ) -> None:
        self.api_key = api_key
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.http_client = http_client

    def create_checkout(
        self,
        request: ProviderCheckoutRequest,
    ) -> ProviderCheckoutResult:
        data = {
            "mode": _stripe_checkout_mode(request.channel),
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "line_items[0][price_data][currency]": request.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(
                _minor_units(request.amount)
            ),
            "line_items[0][price_data][product_data][name]": (
                request.offer_name or request.offer_id
            ),
            "line_items[0][quantity]": "1",
            "metadata[offer_id]": request.offer_id,
            "metadata[channel]": request.channel,
        }
        if data["mode"] == "subscription":
            data["line_items[0][price_data][recurring][interval]"] = "month"

        response = self.http_client.post(
            STRIPE_CHECKOUT_SESSIONS_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Idempotency-Key": request.idempotency_key or str(uuid4()),
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return ProviderCheckoutResult(
            provider_name=self.name,
            provider_reference=payload["id"],
            checkout_url=payload["url"],
        )


def _minor_units(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1")))


def _stripe_checkout_mode(channel: str) -> str:
    if channel == "stripe_subscription":
        return "subscription"
    return "payment"


__all__ = [
    "ProviderCheckoutRequest",
    "ProviderCheckoutResult",
    "ProviderConfirmationRequest",
    "ProviderConfirmationResult",
    "SimulatedPaymentProvider",
    "StripePaymentProvider",
]
