from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from ryan.catalog.service import (
    OfferNotUsableError,
    get_active_offer,
    list_approved_demand_sources,
    list_approved_offers,
    validate_offer_for_payment_creation,
)
from ryan.db import Base, create_database_engine
from ryan.models import Lead, Offer


@pytest.fixture()
def sqlite_session():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    try:
        with Session() as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)


def _create_offers(session):
    active = Offer(
        id="offer-active",
        name="MVP Support Sprint",
        price=Decimal("100.00"),
        currency="USD",
        status="active",
        allowed_channels=["checkout", "invoice"],
    )
    inactive = Offer(
        id="offer-inactive",
        name="Inactive Offer",
        price=Decimal("200.00"),
        currency="USD",
        status="inactive",
        allowed_channels=["checkout"],
    )
    session.add_all([inactive, active])
    session.flush()
    return active, inactive


def _create_demand_source_placeholders(session):
    approved = Lead(
        source="approved-marketplace",
        source_reference="seed:approved-marketplace",
        status="approved_source_placeholder",
        metadata_={
            "kind": "marketplace",
            "configured_status": "approved",
            "seed_placeholder": True,
        },
    )
    inactive = Lead(
        source="inactive-marketplace",
        source_reference="seed:inactive-marketplace",
        status="approved_source_placeholder",
        metadata_={
            "kind": "marketplace",
            "configured_status": "inactive",
            "seed_placeholder": True,
        },
    )
    detected = Lead(
        source="approved-marketplace",
        source_reference="lead:001",
        status="new",
        metadata_={"kind": "marketplace"},
    )
    session.add_all([inactive, detected, approved])
    session.flush()


def test_list_approved_offers_returns_only_active_offers(sqlite_session):
    _create_offers(sqlite_session)

    offers = list_approved_offers(sqlite_session)

    assert [offer.id for offer in offers] == ["offer-active"]


def test_get_active_offer_rejects_missing_or_inactive_offer(sqlite_session):
    _create_offers(sqlite_session)

    assert get_active_offer(sqlite_session, offer_id="offer-active").id == "offer-active"
    with pytest.raises(OfferNotUsableError):
        get_active_offer(sqlite_session, offer_id="offer-inactive")
    with pytest.raises(OfferNotUsableError):
        get_active_offer(sqlite_session, offer_id="missing-offer")


def test_validate_offer_for_payment_creation_requires_allowed_channel(
    sqlite_session,
):
    _create_offers(sqlite_session)

    offer = validate_offer_for_payment_creation(
        sqlite_session,
        offer_id="offer-active",
        channel="checkout",
    )

    assert offer.id == "offer-active"
    with pytest.raises(OfferNotUsableError):
        validate_offer_for_payment_creation(
            sqlite_session,
            offer_id="offer-active",
            channel="sms",
        )


def test_validate_offer_for_payment_creation_rejects_inactive_offer(
    sqlite_session,
):
    _create_offers(sqlite_session)

    with pytest.raises(OfferNotUsableError):
        validate_offer_for_payment_creation(
            sqlite_session,
            offer_id="offer-inactive",
            channel="checkout",
        )


def test_list_approved_demand_sources_returns_seeded_approved_sources(
    sqlite_session,
):
    _create_demand_source_placeholders(sqlite_session)

    demand_sources = list_approved_demand_sources(sqlite_session)

    assert [source.source for source in demand_sources] == ["approved-marketplace"]
    assert demand_sources[0].metadata_["kind"] == "marketplace"
