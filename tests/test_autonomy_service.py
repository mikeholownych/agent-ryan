from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.autonomy import AUTONOMY_ACTOR, calculate_mrr, run_autonomy_cycle
from ryan.config import Settings
from ryan.db import Base, create_database_engine
from ryan.models import CheckoutSession, LedgerEntry, Offer, Payment
from ryan.payments.provider import ProviderCheckoutResult
from ryan.autonomy.wordpress import WordPressDraft


def _session():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


class FakeCheckoutProvider:
    name = "fake"

    def create_checkout(self, request):
        return ProviderCheckoutResult(
            provider_name="fake",
            provider_reference=f"fake-{request.offer_id}",
            checkout_url=f"https://checkout.example/{request.offer_id}",
        )


class FakeWordPressPublisher:
    def __init__(self):
        self.requests = []

    def create_draft(self, *, title: str, body: str) -> WordPressDraft:
        self.requests.append({"title": title, "body": body})
        return WordPressDraft(
            post_id=42,
            status="draft",
            link="https://agentryan.blog/?p=42",
            edit_url="https://agentryan.blog/wp-admin/post.php?post=42&action=edit",
        )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        autonomy_mrr_second_offer_gate=Decimal("20000.00"),
    )


def _add_offer(
    session,
    *,
    id: str,
    name: str,
    price: str,
    status: str = "active",
    channels=None,
) -> Offer:
    offer = Offer(
        id=id,
        name=name,
        price=Decimal(price),
        currency="USD",
        status=status,
        allowed_channels=channels or ["checkout"],
    )
    session.add(offer)
    session.flush()
    return offer


def test_autonomy_selects_one_offer_creates_checkout_and_pauses_second_offer():
    engine, session = _session()
    try:
        primary = _add_offer(
            session,
            id="proof-loop",
            name="Proof-of-loop package",
            price="100.00",
        )
        secondary = _add_offer(
            session,
            id="slow-enterprise",
            name="Slow enterprise package",
            price="5000.00",
        )

        result = run_autonomy_cycle(
            session,
            settings=_settings(),
            checkout_provider=FakeCheckoutProvider(),
            wordpress_publisher=FakeWordPressPublisher(),
        )
        session.commit()

        assert result.selected_offer_id == primary.id
        assert result.second_offer_unlocked is False
        assert result.checkout_url == "https://checkout.example/proof-loop"
        assert session.get(Offer, primary.id).status == "active"
        assert session.get(Offer, secondary.id).status == "inactive"
        assert result.blog_draft_id is not None
        assert result.email_draft_id is not None

        checkout = session.scalar(select(CheckoutSession))
        assert checkout.offer_id == primary.id
        assert checkout.idempotency_key == "autonomy-launch:proof-loop"

        cycle_entry = session.scalar(
            select(LedgerEntry).where(LedgerEntry.type == "audit.autonomy.cycle")
        )
        assert cycle_entry.actor == AUTONOMY_ACTOR
        assert cycle_entry.metadata_["selected_offer_id"] == primary.id
        assert cycle_entry.metadata_["blog_draft_id"] == result.blog_draft_id
        assert cycle_entry.metadata_["email_draft_id"] == result.email_draft_id

        blog_draft = session.get(LedgerEntry, result.blog_draft_id)
        assert blog_draft.type == "audit.autonomy.blog_draft"
        assert "Building Ryan in public" in blog_draft.metadata_["title"]
        assert blog_draft.metadata_["destination"] == "https://agentryan.blog/"
        assert blog_draft.metadata_["wordpress"]["post_id"] == 42
        assert blog_draft.metadata_["wordpress"]["status"] == "draft"

        email_draft = session.get(LedgerEntry, result.email_draft_id)
        assert email_draft.type == "audit.autonomy.agentmail_draft"
        assert email_draft.metadata_["from"] == "agentryan@agentmail.to"
        assert email_draft.metadata_["to"] == "mike.holownych@aisyndicate.io"
        assert email_draft.metadata_["subject"].startswith("Approval requested")
        assert email_draft.metadata_["send_status"].startswith("blocked_until")
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_autonomy_reuses_existing_checkout():
    engine, session = _session()
    try:
        offer = _add_offer(
            session,
            id="proof-loop",
            name="Proof-of-loop package",
            price="100.00",
        )
        existing = CheckoutSession(
            offer_id=offer.id,
            status="created",
            payment_provider="fake",
            provider_reference="existing",
            checkout_url="https://checkout.example/existing",
            amount=offer.price,
            currency=offer.currency,
            idempotency_key="manual",
        )
        session.add(existing)
        session.flush()

        result = run_autonomy_cycle(
            session,
            settings=_settings(),
            checkout_provider=FakeCheckoutProvider(),
        )
        session.commit()

        assert result.checkout_session_id == existing.id
        assert result.checkout_url == existing.checkout_url
        assert len(session.scalars(select(CheckoutSession)).all()) == 1
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_autonomy_reuses_daily_blog_and_email_drafts():
    engine, session = _session()
    try:
        _add_offer(
            session,
            id="proof-loop",
            name="Proof-of-loop package",
            price="100.00",
        )
        now = datetime(2026, 6, 2, 5, 0, tzinfo=UTC)

        wordpress = FakeWordPressPublisher()
        first = run_autonomy_cycle(
            session,
            settings=_settings(),
            checkout_provider=FakeCheckoutProvider(),
            wordpress_publisher=wordpress,
            now=now,
        )
        second = run_autonomy_cycle(
            session,
            settings=_settings(),
            checkout_provider=FakeCheckoutProvider(),
            wordpress_publisher=wordpress,
            now=now + timedelta(minutes=15),
        )
        session.commit()

        assert second.blog_draft_id == first.blog_draft_id
        assert second.email_draft_id == first.email_draft_id
        assert any(
            action.startswith("reused build-in-public post draft")
            for action in second.actions
        )
        assert any(
            action.startswith("reused AgentMail outreach draft")
            for action in second.actions
        )
        assert (
            len(
                session.scalars(
                    select(LedgerEntry).where(
                        LedgerEntry.type == "audit.autonomy.blog_draft"
                    )
                ).all()
            )
            == 1
        )
        assert len(wordpress.requests) == 1
        assert (
            len(
                session.scalars(
                    select(LedgerEntry).where(
                        LedgerEntry.type == "audit.autonomy.agentmail_draft"
                    )
                ).all()
            )
            == 1
        )
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_second_offer_unlocks_after_mrr_gate():
    engine, session = _session()
    try:
        primary = _add_offer(
            session,
            id="proof-loop",
            name="Proof-of-loop package",
            price="100.00",
        )
        secondary = _add_offer(
            session,
            id="second-offer",
            name="Second offer",
            price="200.00",
        )
        session.add(
            Payment(
                amount=Decimal("20000.00"),
                currency="USD",
                status="settled",
                source="customer",
                payment_provider="stripe",
                provider_reference="evt-20k",
                settlement_time=datetime.now(UTC) - timedelta(days=1),
                idempotency_key="mrr-20k",
            )
        )
        session.flush()

        result = run_autonomy_cycle(
            session,
            settings=_settings(),
            checkout_provider=FakeCheckoutProvider(),
        )
        session.commit()

        assert calculate_mrr(session) == Decimal("20000.00")
        assert result.second_offer_unlocked is True
        assert session.get(Offer, primary.id).status == "active"
        assert session.get(Offer, secondary.id).status == "active"
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_autonomy_prefers_subscription_offer_over_one_time_seed_offer():
    engine, session = _session()
    try:
        _add_offer(
            session,
            id="seed-100",
            name="Ryan $100 Seed Offer",
            price="100.00",
            channels=["stripe_checkout"],
        )
        subscription = _add_offer(
            session,
            id="ai-control-room-2000",
            name="AI Agent Control Room",
            price="2000.00",
            channels=["stripe_subscription"],
        )

        result = run_autonomy_cycle(
            session,
            settings=_settings(),
            checkout_provider=FakeCheckoutProvider(),
        )
        session.commit()

        assert result.selected_offer_id == subscription.id
        assert result.checkout_url == "https://checkout.example/ai-control-room-2000"
    finally:
        session.close()
        Base.metadata.drop_all(engine)
