from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ryan.autonomy.service import run_autonomy_cycle
from ryan.autonomy.wordpress import WordPressDraftPublisher
from ryan.config import Settings, get_settings
from ryan.db import get_session
from ryan.payments.router import _payment_provider_from_settings

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


class AutonomyCycleResponse(BaseModel):
    selected_offer_id: str | None
    selected_offer_name: str | None
    mrr: Decimal
    mrr_gate: Decimal
    second_offer_unlocked: bool
    checkout_session_id: str | None
    checkout_url: str | None
    blog_draft_id: str | None
    email_draft_id: str | None
    actions: tuple[str, ...]
    blockers: tuple[str, ...]


@router.post("/cycle", response_model=AutonomyCycleResponse)
def post_autonomy_cycle(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    result = run_autonomy_cycle(
        session,
        settings=settings,
        checkout_provider=_payment_provider_from_settings(settings),
        wordpress_publisher=_wordpress_publisher_from_settings(settings),
    )
    session.commit()
    return result


def _wordpress_publisher_from_settings(settings: Settings):
    if not settings.wordpress_drafts_enabled:
        return None
    if settings.wordpress_username is None or settings.wordpress_password is None:
        return None
    return WordPressDraftPublisher(
        site_url=settings.wordpress_site_url,
        username=settings.wordpress_username,
        password=settings.wordpress_password,
    )


__all__ = ["router"]
