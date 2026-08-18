from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.config import Settings
from ryan.exceptions import create_exception_record
from ryan.kill_switch import get_kill_switch_state
from ryan.ledger import append_ledger_entry
from ryan.models import CheckoutSession, LedgerEntry, Offer, Payment
from ryan.payments.service import PaymentRequestError, create_payment_request
from ryan.autonomy.wordpress import WordPressDraftPublisher

AUTONOMY_ACTOR = "agent:ryan.autonomy"
MRR_WINDOW_DAYS = 30
PREFERRED_CHECKOUT_CHANNELS = (
    "stripe_subscription",
    "checkout",
    "stripe_checkout",
    "sandbox_checkout",
)


@dataclass(frozen=True)
class AutonomyCycleResult:
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


def run_autonomy_cycle(
    session: Session,
    *,
    settings: Settings,
    checkout_provider=None,
    wordpress_publisher: WordPressDraftPublisher | None = None,
    now: datetime | None = None,
) -> AutonomyCycleResult:
    """Run one bounded autonomous business cycle.

    The cycle is intentionally deterministic and ledger-backed: choose one
    fastest-to-revenue offer, keep all other active offers paused until the MRR
    gate is reached, and create or reuse one checkout link for the selected
    offer.
    """

    cycle_time = now or datetime.now(UTC)
    mrr = calculate_mrr(session, now=cycle_time)
    mrr_gate = settings.autonomy_mrr_second_offer_gate
    second_offer_unlocked = mrr >= mrr_gate
    kill_switch = get_kill_switch_state(session)
    offers = _all_offers(session)
    actions: list[str] = []
    blockers: list[str] = []

    selected_offer = _select_fastest_to_revenue_offer(offers)
    if selected_offer is None:
        blockers.append("no offer exists for autonomous launch")
        create_exception_record(
            session,
            exception_type="autonomy_offer_selection_blocked",
            severity="critical",
            reason="Ryan cannot start the revenue loop without at least one offer",
            reference_type="autonomy_cycle",
            reference_id=cycle_time.isoformat(),
            actor=AUTONOMY_ACTOR,
        )
        cycle_entry = _append_cycle_entry(
            session,
            cycle_time=cycle_time,
            selected_offer=None,
            mrr=mrr,
            mrr_gate=mrr_gate,
            second_offer_unlocked=second_offer_unlocked,
            checkout_session=None,
            blog_draft=None,
            email_draft=None,
            actions=actions,
            blockers=blockers,
        )
        return _result_from_cycle(
            cycle_entry,
            selected_offer=None,
            mrr=mrr,
            mrr_gate=mrr_gate,
            second_offer_unlocked=second_offer_unlocked,
            checkout_session=None,
            blog_draft=None,
            email_draft=None,
            actions=actions,
            blockers=blockers,
        )

    actions.append(f"selected primary offer {selected_offer.id}")
    _ensure_selected_offer_active(selected_offer, actions)

    if second_offer_unlocked:
        actions.append("second offer work unlocked because MRR gate is reached")
    else:
        paused = _pause_non_primary_active_offers(session, selected_offer)
        if paused:
            actions.append(
                "paused non-primary active offers until MRR reaches "
                f"{_money(mrr_gate)}: {', '.join(paused)}"
            )
        else:
            actions.append("single-offer focus already satisfied")

    _append_offer_selection_entry(
        session,
        selected_offer=selected_offer,
        mrr=mrr,
        mrr_gate=mrr_gate,
        second_offer_unlocked=second_offer_unlocked,
    )

    checkout_session = None
    if kill_switch.active:
        blockers.append(f"kill switch active: {kill_switch.reason}")
        actions.append("skipped checkout creation while kill switch is active")
    else:
        checkout_session = _checkout_for_offer(session, selected_offer)
        if checkout_session is not None:
            actions.append(f"reused checkout session {checkout_session.id}")
        else:
            try:
                checkout_session = create_payment_request(
                    session,
                    offer_id=selected_offer.id,
                    channel=_preferred_channel(selected_offer),
                    actor=AUTONOMY_ACTOR,
                    idempotency_key=f"autonomy-launch:{selected_offer.id}",
                    provider=checkout_provider,
                )
                actions.append(f"created checkout session {checkout_session.id}")
            except PaymentRequestError as error:
                blockers.append(str(error))
                create_exception_record(
                    session,
                    exception_type="autonomy_checkout_blocked",
                    severity="high",
                    reason=str(error),
                    reference_type="offer",
                    reference_id=selected_offer.id,
                    actor=AUTONOMY_ACTOR,
                )

    blog_draft, blog_draft_created = _ensure_daily_blog_progress_draft(
        session,
        selected_offer=selected_offer,
        mrr=mrr,
        mrr_gate=mrr_gate,
        checkout_session=checkout_session,
        blockers=blockers,
        cycle_time=cycle_time,
        wordpress_publisher=wordpress_publisher,
    )
    actions.append(
        f"drafted build-in-public post {blog_draft.id}"
        if blog_draft_created
        else f"reused build-in-public post draft {blog_draft.id}"
    )
    email_draft, email_draft_created = _ensure_daily_agentmail_outreach_draft(
        session,
        settings=settings,
        selected_offer=selected_offer,
        checkout_session=checkout_session,
        blockers=blockers,
        cycle_time=cycle_time,
    )
    actions.append(
        f"drafted AgentMail outreach {email_draft.id}"
        if email_draft_created
        else f"reused AgentMail outreach draft {email_draft.id}"
    )

    _append_launch_plan_entry(
        session,
        selected_offer=selected_offer,
        mrr=mrr,
        mrr_gate=mrr_gate,
        checkout_session=checkout_session,
        blockers=blockers,
    )
    cycle_entry = _append_cycle_entry(
        session,
        cycle_time=cycle_time,
        selected_offer=selected_offer,
        mrr=mrr,
        mrr_gate=mrr_gate,
        second_offer_unlocked=second_offer_unlocked,
        checkout_session=checkout_session,
        blog_draft=blog_draft,
        email_draft=email_draft,
        actions=actions,
        blockers=blockers,
    )
    return _result_from_cycle(
        cycle_entry,
        selected_offer=selected_offer,
        mrr=mrr,
        mrr_gate=mrr_gate,
        second_offer_unlocked=second_offer_unlocked,
        checkout_session=checkout_session,
        blog_draft=blog_draft,
        email_draft=email_draft,
        actions=actions,
        blockers=blockers,
    )


def calculate_mrr(session: Session, *, now: datetime | None = None) -> Decimal:
    window_end = now or datetime.now(UTC)
    window_start = window_end - timedelta(days=MRR_WINDOW_DAYS)
    payments = session.scalars(
        select(Payment).where(
            Payment.source == "customer",
            Payment.status == "settled",
            Payment.settlement_time >= window_start,
            Payment.settlement_time <= window_end,
        )
    )
    return sum((payment.amount for payment in payments), Decimal("0.00"))


def _all_offers(session: Session) -> list[Offer]:
    return list(session.scalars(select(Offer).order_by(Offer.id.asc())))


def _select_fastest_to_revenue_offer(offers: list[Offer]) -> Offer | None:
    if not offers:
        return None
    return max(offers, key=_offer_score)


def _offer_score(offer: Offer) -> tuple[int, Decimal, str]:
    score = 0
    if offer.status == "active":
        score += 100
    if "stripe_subscription" in offer.allowed_channels:
        score += 40
    if any(channel in offer.allowed_channels for channel in PREFERRED_CHECKOUT_CHANNELS):
        score += 25
    if Decimal("50.00") <= offer.price <= Decimal("500.00"):
        score += 10
    if offer.price > Decimal("0.00"):
        score += 1
    return score, -offer.price, offer.id


def _ensure_selected_offer_active(offer: Offer, actions: list[str]) -> None:
    if offer.status == "active":
        return
    offer.status = "active"
    actions.append(f"activated selected offer {offer.id}")


def _pause_non_primary_active_offers(session: Session, selected_offer: Offer) -> list[str]:
    paused: list[str] = []
    for offer in _all_offers(session):
        if offer.id == selected_offer.id or offer.status != "active":
            continue
        offer.status = "inactive"
        paused.append(offer.id)
        append_ledger_entry(
            session,
            type="audit.autonomy.offer_paused",
            amount=None,
            currency=None,
            reference_type="offer",
            reference_id=offer.id,
            actor=AUTONOMY_ACTOR,
            metadata={
                "reason": "single-offer focus until MRR gate is reached",
                "primary_offer_id": selected_offer.id,
            },
        )
    return paused


def _checkout_for_offer(session: Session, offer: Offer) -> CheckoutSession | None:
    return session.scalar(
        select(CheckoutSession)
        .where(
            CheckoutSession.offer_id == offer.id,
            CheckoutSession.status == "created",
        )
        .order_by(CheckoutSession.created_at.desc())
        .limit(1)
    )


def _preferred_channel(offer: Offer) -> str:
    for channel in PREFERRED_CHECKOUT_CHANNELS:
        if channel in offer.allowed_channels:
            return channel
    return offer.allowed_channels[0]


def _append_offer_selection_entry(
    session: Session,
    *,
    selected_offer: Offer,
    mrr: Decimal,
    mrr_gate: Decimal,
    second_offer_unlocked: bool,
) -> None:
    append_ledger_entry(
        session,
        type="audit.autonomy.offer_selected",
        amount=selected_offer.price,
        currency=selected_offer.currency,
        reference_type="offer",
        reference_id=selected_offer.id,
        actor=AUTONOMY_ACTOR,
        metadata=_json_safe(
            {
                "name": selected_offer.name,
                "allowed_channels": selected_offer.allowed_channels,
                "current_mrr": mrr,
                "second_offer_mrr_gate": mrr_gate,
                "second_offer_unlocked": second_offer_unlocked,
                "selection_rule": "fastest-to-revenue deterministic score",
            }
        ),
    )


def _append_launch_plan_entry(
    session: Session,
    *,
    selected_offer: Offer,
    mrr: Decimal,
    mrr_gate: Decimal,
    checkout_session: CheckoutSession | None,
    blockers: list[str],
) -> None:
    append_ledger_entry(
        session,
        type="audit.autonomy.launch_plan",
        amount=None,
        currency=selected_offer.currency,
        reference_type="offer",
        reference_id=selected_offer.id,
        actor=AUTONOMY_ACTOR,
        metadata=_json_safe(
            {
                "objective": "build, launch, and sell one offer as quickly as possible",
                "primary_offer": {
                    "id": selected_offer.id,
                    "name": selected_offer.name,
                    "price": selected_offer.price,
                    "currency": selected_offer.currency,
                    "checkout_url": checkout_session.checkout_url
                    if checkout_session is not None
                    else None,
                },
                "operating_rule": (
                    "do not work on a second offer until MRR is at least "
                    f"{_money(mrr_gate)}"
                ),
                "current_mrr": mrr,
                "required_next_actions": [
                    "keep checkout link live",
                    "drive demand only for the primary offer",
                    "record every customer payment through settlement",
                    "review blockers before expanding scope",
                ],
                "blockers": blockers,
            }
        ),
    )


def _ensure_daily_blog_progress_draft(
    session: Session,
    *,
    selected_offer: Offer,
    mrr: Decimal,
    mrr_gate: Decimal,
    checkout_session: CheckoutSession | None,
    blockers: list[str],
    cycle_time: datetime,
    wordpress_publisher: WordPressDraftPublisher | None,
) -> tuple[LedgerEntry, bool]:
    existing = _existing_daily_entry(
        session,
        type="audit.autonomy.blog_draft",
        reference_id=selected_offer.id,
        cycle_time=cycle_time,
    )
    if existing is not None:
        return existing, False

    checkout_line = (
        f"The checkout path is live for the current offer: {checkout_session.checkout_url}."
        if checkout_session is not None and checkout_session.checkout_url is not None
        else "The checkout path is not public yet; Ryan is keeping launch blocked until that is resolved."
    )
    body = "\n\n".join(
        [
            f"Ryan is focusing on one offer: {selected_offer.name}.",
            (
                "The current operating rule is simple: no second offer work starts until "
                f"MRR reaches {_money(mrr_gate)}. Current measured MRR is {_money(mrr)}."
            ),
            checkout_line,
            (
                "This public log is for progress, learnings, and wins. It intentionally "
                "excludes secrets, customer data, wallet details, raw logs, and private "
                "infrastructure details."
            ),
            _blocker_sentence(blockers),
        ]
    )
    title = f"Building Ryan in public: focusing on {selected_offer.name}"
    wordpress_draft = None
    if wordpress_publisher is not None:
        try:
            wordpress_draft = wordpress_publisher.create_draft(title=title, body=body)
        except Exception as error:
            blockers.append(f"WordPress draft creation failed: {error}")

    entry = append_ledger_entry(
        session,
        type="audit.autonomy.blog_draft",
        amount=None,
        currency=selected_offer.currency,
        reference_type="offer",
        reference_id=selected_offer.id,
        actor=AUTONOMY_ACTOR,
        metadata={
            "destination": "https://agentryan.blog/",
            "workflow_status": "drafted",
            "review_required": True,
            "sanitize_required": True,
            "verify_required": True,
            "publish_required": True,
            "title": title,
            "body": body,
            "wordpress": {
                "post_id": wordpress_draft.post_id if wordpress_draft is not None else None,
                "status": wordpress_draft.status if wordpress_draft is not None else None,
                "link": wordpress_draft.link if wordpress_draft is not None else None,
                "edit_url": wordpress_draft.edit_url if wordpress_draft is not None else None,
            },
            "public_safety": {
                "contains_secrets": False,
                "contains_customer_data": False,
                "contains_private_infrastructure": False,
                "contains_wallet_details": False,
            },
        },
    )
    return entry, True


def _ensure_daily_agentmail_outreach_draft(
    session: Session,
    *,
    settings: Settings,
    selected_offer: Offer,
    checkout_session: CheckoutSession | None,
    blockers: list[str],
    cycle_time: datetime,
) -> tuple[LedgerEntry, bool]:
    existing = _existing_daily_entry(
        session,
        type="audit.autonomy.agentmail_draft",
        reference_id=selected_offer.id,
        cycle_time=cycle_time,
    )
    if existing is not None:
        return existing, False

    checkout_url = checkout_session.checkout_url if checkout_session is not None else None
    body_lines = [
        "Hi, I am Ryan, an autonomous business OS being built in public.",
        (
            f"I am currently focused on one offer: {selected_offer.name} "
            f"({_money(selected_offer.price)} {selected_offer.currency})."
        ),
        "I am looking for fast feedback from people who want a bounded, auditable agent business loop.",
    ]
    if checkout_url is not None:
        body_lines.append(f"Checkout is available here: {checkout_url}")
    if blockers:
        body_lines.append(
            "Approval or operator action is requested for these blockers: "
            + "; ".join(blockers)
        )
    body_lines.append("Reply with approval, changes, or the next required operator action.")

    entry = append_ledger_entry(
        session,
        type="audit.autonomy.agentmail_draft",
        amount=None,
        currency=selected_offer.currency,
        reference_type="offer",
        reference_id=selected_offer.id,
        actor=AUTONOMY_ACTOR,
        metadata={
            "from": settings.agentmail_inbox,
            "to": settings.operator_approval_email,
            "subject": f"Approval requested: Ryan launching {selected_offer.name}",
            "body": "\n\n".join(body_lines),
            "workflow_status": "drafted",
            "send_status": "blocked_until_review_sanitize_approval_and_provider",
            "review_required": settings.outbound_email_requires_review,
            "sanitize_required": settings.outbound_email_requires_sanitization,
            "approval_required": settings.outbound_email_requires_approval,
            "provider_required": True,
        },
    )
    return entry, True


def _existing_daily_entry(
    session: Session,
    *,
    type: str,
    reference_id: str,
    cycle_time: datetime,
) -> LedgerEntry | None:
    day_start = cycle_time.replace(hour=0, minute=0, second=0, microsecond=0)
    return session.scalar(
        select(LedgerEntry)
        .where(
            LedgerEntry.type == type,
            LedgerEntry.reference_type == "offer",
            LedgerEntry.reference_id == reference_id,
            LedgerEntry.timestamp >= day_start,
        )
        .order_by(LedgerEntry.timestamp.desc())
        .limit(1)
    )


def _append_cycle_entry(
    session: Session,
    *,
    cycle_time: datetime,
    selected_offer: Offer | None,
    mrr: Decimal,
    mrr_gate: Decimal,
    second_offer_unlocked: bool,
    checkout_session: CheckoutSession | None,
    blog_draft: LedgerEntry | None,
    email_draft: LedgerEntry | None,
    actions: list[str],
    blockers: list[str],
) -> LedgerEntry:
    return append_ledger_entry(
        session,
        type="audit.autonomy.cycle",
        amount=None,
        currency=selected_offer.currency if selected_offer is not None else None,
        reference_type="autonomy_cycle",
        reference_id=cycle_time.isoformat(),
        actor=AUTONOMY_ACTOR,
        metadata=_json_safe(
            {
                "selected_offer_id": selected_offer.id if selected_offer is not None else None,
                "selected_offer_name": selected_offer.name if selected_offer is not None else None,
                "current_mrr": mrr,
                "second_offer_mrr_gate": mrr_gate,
                "second_offer_unlocked": second_offer_unlocked,
                "checkout_session_id": checkout_session.id
                if checkout_session is not None
                else None,
                "checkout_url": checkout_session.checkout_url
                if checkout_session is not None
                else None,
                "blog_draft_id": blog_draft.id if blog_draft is not None else None,
                "email_draft_id": email_draft.id if email_draft is not None else None,
                "actions": actions,
                "blockers": blockers,
            }
        ),
        timestamp=cycle_time,
    )


def _result_from_cycle(
    cycle_entry: LedgerEntry,
    *,
    selected_offer: Offer | None,
    mrr: Decimal,
    mrr_gate: Decimal,
    second_offer_unlocked: bool,
    checkout_session: CheckoutSession | None,
    blog_draft: LedgerEntry | None,
    email_draft: LedgerEntry | None,
    actions: list[str],
    blockers: list[str],
) -> AutonomyCycleResult:
    return AutonomyCycleResult(
        selected_offer_id=selected_offer.id if selected_offer is not None else None,
        selected_offer_name=selected_offer.name if selected_offer is not None else None,
        mrr=mrr,
        mrr_gate=mrr_gate,
        second_offer_unlocked=second_offer_unlocked,
        checkout_session_id=checkout_session.id if checkout_session is not None else None,
        checkout_url=checkout_session.checkout_url if checkout_session is not None else None,
        blog_draft_id=blog_draft.id if blog_draft is not None else None,
        email_draft_id=email_draft.id if email_draft is not None else None,
        actions=tuple(actions),
        blockers=tuple(blockers),
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def _blocker_sentence(blockers: list[str]) -> str:
    if not blockers:
        return "No current launch blockers were found in this cycle."
    return "Current blockers: " + "; ".join(blockers) + "."


__all__ = [
    "AUTONOMY_ACTOR",
    "AutonomyCycleResult",
    "calculate_mrr",
    "run_autonomy_cycle",
]
