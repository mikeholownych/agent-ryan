from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.models import Lead, Offer


class OfferNotUsableError(ValueError):
    """Raised when an offer cannot be used for payment creation."""


def list_approved_offers(session: Session) -> list[Offer]:
    return list(
        session.scalars(
            select(Offer)
            .where(Offer.status == "active")
            .order_by(Offer.id.asc())
        )
    )


def get_active_offer(session: Session, *, offer_id: str) -> Offer:
    offer = session.get(Offer, offer_id)
    if offer is None or offer.status != "active":
        raise OfferNotUsableError(f"offer {offer_id!r} is not active")
    return offer


def validate_offer_for_payment_creation(
    session: Session,
    *,
    offer_id: str,
    channel: str,
) -> Offer:
    offer = get_active_offer(session, offer_id=offer_id)
    if channel not in offer.allowed_channels:
        raise OfferNotUsableError(
            f"offer {offer_id!r} is not allowed on channel {channel!r}"
        )
    return offer


def list_approved_demand_sources(session: Session) -> list[Lead]:
    return list(
        session.scalars(
            select(Lead)
            .where(
                Lead.status == "approved_source_placeholder",
                Lead.metadata_["configured_status"].as_string() == "approved",
            )
            .order_by(Lead.source.asc(), Lead.source_reference.asc())
        )
    )


__all__ = [
    "OfferNotUsableError",
    "get_active_offer",
    "list_approved_demand_sources",
    "list_approved_offers",
    "validate_offer_for_payment_creation",
]
