from decimal import Decimal

from ryan.payments.provider import ProviderCheckoutRequest, StripePaymentProvider


class FakeStripeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "cs_live_123",
            "url": "https://checkout.stripe.com/c/pay/cs_live_123",
        }


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    def post(self, url, *, data, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "data": data,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeStripeResponse()


def test_stripe_provider_creates_checkout_session_with_idempotency_key():
    http_client = FakeHttpClient()
    provider = StripePaymentProvider(
        api_key="sk_live_test",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
        http_client=http_client,
    )

    result = provider.create_checkout(
        ProviderCheckoutRequest(
            offer_id="offer-001",
            amount=Decimal("12.34"),
            currency="USD",
            channel="checkout",
            offer_name="Production offer",
            idempotency_key="payment-create-001",
        )
    )

    assert result.provider_name == "stripe"
    assert result.provider_reference == "cs_live_123"
    assert result.checkout_url == "https://checkout.stripe.com/c/pay/cs_live_123"
    call = http_client.calls[0]
    assert call["url"] == "https://api.stripe.com/v1/checkout/sessions"
    assert call["headers"]["Authorization"] == "Bearer sk_live_test"
    assert call["headers"]["Idempotency-Key"] == "payment-create-001"
    assert call["data"]["mode"] == "payment"
    assert call["data"]["success_url"] == "https://example.com/success"
    assert call["data"]["cancel_url"] == "https://example.com/cancel"
    assert call["data"]["line_items[0][price_data][unit_amount]"] == "1234"
    assert call["data"]["line_items[0][price_data][currency]"] == "usd"
    assert call["data"]["line_items[0][quantity]"] == "1"
    assert call["data"]["metadata[offer_id]"] == "offer-001"


def test_stripe_provider_creates_subscription_checkout_for_subscription_channel():
    http_client = FakeHttpClient()
    provider = StripePaymentProvider(
        api_key="sk_live_test",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
        http_client=http_client,
    )

    provider.create_checkout(
        ProviderCheckoutRequest(
            offer_id="offer-subscription",
            amount=Decimal("2000.00"),
            currency="USD",
            channel="stripe_subscription",
            offer_name="AI Agent Control Room",
            idempotency_key="subscription-create-001",
        )
    )

    call = http_client.calls[0]
    assert call["data"]["mode"] == "subscription"
    assert call["data"]["line_items[0][price_data][unit_amount]"] == "200000"
    assert call["data"]["line_items[0][price_data][recurring][interval]"] == "month"
    assert call["data"]["metadata[channel]"] == "stripe_subscription"
