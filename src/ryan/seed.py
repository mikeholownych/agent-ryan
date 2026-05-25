from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.config import Settings
from ryan.models import Agent, KillSwitchState, Lead, Offer, PolicyRule, Wallet

MVP_WALLET_TYPES = {"revenue", "operating", "reserve"}
SEED_ACTOR = "system.seed"


def seed_mvp_data(session: Session, settings: Settings) -> None:
    """Seed the minimum local data needed before service implementation."""
    _validate_mvp_seed_configuration(settings)

    _seed_agent(session, settings)
    _seed_offer(session, settings)
    _seed_demand_source_placeholders(session, settings)
    _seed_policy_rules(session, settings)
    _seed_wallets(session, settings)
    _seed_inactive_kill_switch(session)
    session.commit()


def _validate_mvp_seed_configuration(settings: Settings) -> None:
    if not settings.business_model.name or not settings.business_model.objective:
        raise ValueError("business_model name and objective are required for MVP seed")

    active_offers = [offer for offer in settings.offer_catalog if offer.status == "active"]
    if len(active_offers) != 1:
        raise ValueError("offer_catalog must contain exactly one active MVP offer")

    if not settings.approved_demand_sources:
        raise ValueError("approved_demand_sources must contain at least one source")

    if not settings.vendor_allowlist:
        raise ValueError("vendor_allowlist must contain at least one vendor")

    configured_wallets = set(settings.revenue_allocation.wallet_percentages)
    if configured_wallets != MVP_WALLET_TYPES:
        raise ValueError(
            "revenue allocation must include revenue, operating, and reserve wallets"
        )

    allocation_total = sum(
        settings.revenue_allocation.wallet_percentages.values(),
        Decimal("0"),
    )
    if allocation_total != Decimal("100"):
        raise ValueError("revenue allocation percentages must total 100 percent")


def _seed_agent(session: Session, settings: Settings) -> None:
    agent = session.scalar(
        select(Agent).where(Agent.name == settings.business_model.name)
    )
    if agent is None:
        agent = Agent(
            name=settings.business_model.name,
            status="active",
            current_objective=settings.business_model.objective,
            mode=settings.environment,
        )
        session.add(agent)
        return

    agent.status = "active"
    agent.current_objective = settings.business_model.objective
    agent.mode = settings.environment


def _seed_offer(session: Session, settings: Settings) -> None:
    offer_config = next(offer for offer in settings.offer_catalog if offer.status == "active")
    offer = session.get(Offer, offer_config.id)
    if offer is None:
        offer = Offer(
            id=offer_config.id,
            name=offer_config.name,
            price=offer_config.price,
            currency=offer_config.currency,
            status=offer_config.status,
            allowed_channels=offer_config.allowed_channels,
        )
        session.add(offer)
        return

    offer.name = offer_config.name
    offer.price = offer_config.price
    offer.currency = offer_config.currency
    offer.status = offer_config.status
    offer.allowed_channels = offer_config.allowed_channels


def _seed_demand_source_placeholders(session: Session, settings: Settings) -> None:
    for source_config in settings.approved_demand_sources:
        source_reference = f"seed:{source_config.name}"
        source = session.scalar(
            select(Lead).where(
                Lead.source == source_config.name,
                Lead.source_reference == source_reference,
            )
        )
        metadata = {
            "kind": source_config.kind,
            "configured_status": source_config.status,
            "seed_placeholder": True,
        }
        if source is None:
            session.add(
                Lead(
                    source=source_config.name,
                    source_reference=source_reference,
                    status="approved_source_placeholder",
                    metadata_=metadata,
                )
            )
            continue

        source.status = "approved_source_placeholder"
        source.metadata_ = metadata


def _seed_policy_rules(session: Session, settings: Settings) -> None:
    rules = [
        (
            "vendor_allowlist",
            {
                "vendors": [
                    {
                        "name": vendor.name,
                        "categories": vendor.categories,
                        "status": vendor.status,
                    }
                    for vendor in settings.vendor_allowlist
                ]
            },
        ),
        (
            "spend_threshold",
            {
                "per_transaction_cap": settings.spend_threshold.per_transaction_cap,
                "currency": settings.spend_threshold.currency,
            },
        ),
        (
            "category_budget",
            {
                "budgets": [
                    {
                        "category": budget.category,
                        "limit": budget.limit,
                        "currency": budget.currency,
                        "period": budget.period,
                    }
                    for budget in settings.category_budgets
                ]
            },
        ),
        (
            "time_window",
            {
                "windows": [
                    {
                        "name": window.name,
                        "start_hour_utc": window.start_hour_utc,
                        "end_hour_utc": window.end_hour_utc,
                        "days": window.days,
                        "timezone": window.timezone,
                    }
                    for window in settings.spend_time_windows
                ]
            },
        ),
        ("revenue_floor", {"amount": settings.revenue_floor}),
        ("reserve_minimum", {"amount": settings.reserve_minimum}),
        (
            "revenue_allocation",
            {"wallet_percentages": settings.revenue_allocation.wallet_percentages},
        ),
    ]

    for priority, (rule_type, configuration) in enumerate(rules, start=1):
        rule = session.scalar(
            select(PolicyRule).where(
                PolicyRule.type == rule_type,
                PolicyRule.created_by_actor == SEED_ACTOR,
            )
        )
        normalized_configuration = _json_safe(configuration)
        if rule is None:
            session.add(
                PolicyRule(
                    type=rule_type,
                    status="active",
                    configuration=normalized_configuration,
                    priority=priority,
                    created_by_actor=SEED_ACTOR,
                )
            )
            continue

        rule.status = "active"
        rule.configuration = normalized_configuration
        rule.priority = priority


def _seed_wallets(session: Session, settings: Settings) -> None:
    wallet_currency = _active_offer(settings).currency
    for wallet_type in sorted(MVP_WALLET_TYPES):
        wallet = session.scalar(
            select(Wallet).where(
                Wallet.type == wallet_type,
                Wallet.currency == wallet_currency,
            )
        )
        limits = _wallet_limits(wallet_type, settings)
        if wallet is None:
            session.add(
                Wallet(
                    type=wallet_type,
                    balance=Decimal("0.00"),
                    currency=wallet_currency,
                    locked=False,
                    limits=limits,
                )
            )
            continue

        wallet.limits = limits


def _seed_inactive_kill_switch(session: Session) -> None:
    existing_state = session.scalar(select(KillSwitchState))
    if existing_state is not None:
        return

    session.add(
        KillSwitchState(
            active=False,
            reason="MVP seed inactive state",
        )
    )


def _active_offer(settings: Settings):
    return next(offer for offer in settings.offer_catalog if offer.status == "active")


def _wallet_limits(wallet_type: str, settings: Settings) -> dict[str, Any]:
    if wallet_type == "operating":
        return _json_safe(
            {
                "spend_threshold": settings.spend_threshold.per_transaction_cap,
                "reserve_minimum": settings.reserve_minimum,
                "currency": settings.spend_threshold.currency,
            }
        )

    if wallet_type == "reserve":
        return _json_safe(
            {
                "minimum": settings.reserve_minimum,
                "currency": _active_offer(settings).currency,
            }
        )

    return _json_safe(
        {
            "revenue_floor": settings.revenue_floor,
            "currency": _active_offer(settings).currency,
        }
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


__all__ = ["seed_mvp_data"]
