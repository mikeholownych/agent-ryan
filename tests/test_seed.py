from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.config import OfferConfig, RevenueAllocationConfig, Settings
from ryan.db import Base, create_database_engine
from ryan.models import Agent, KillSwitchState, Lead, Offer, PolicyRule, Wallet
from ryan.seed import seed_mvp_data


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


@pytest.fixture()
def sandbox_settings():
    return Settings(_env_file=None)


def count_rows(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_seed_mvp_data_creates_required_sandbox_records(
    sqlite_session,
    sandbox_settings,
):
    seed_mvp_data(sqlite_session, sandbox_settings)

    agent = sqlite_session.scalar(select(Agent))
    assert agent.name == sandbox_settings.business_model.name
    assert agent.current_objective == sandbox_settings.business_model.objective
    assert agent.status == "active"
    assert agent.mode == "sandbox"

    offer = sqlite_session.get(Offer, sandbox_settings.offer_catalog[0].id)
    assert offer is not None
    assert offer.name == sandbox_settings.offer_catalog[0].name
    assert offer.status == "active"
    assert offer.allowed_channels == sandbox_settings.offer_catalog[0].allowed_channels

    demand_sources = sqlite_session.scalars(select(Lead)).all()
    assert len(demand_sources) == len(sandbox_settings.approved_demand_sources)
    assert {source.source for source in demand_sources} == {
        source.name for source in sandbox_settings.approved_demand_sources
    }
    assert all(source.status == "approved_source_placeholder" for source in demand_sources)

    policy_rules = sqlite_session.scalars(select(PolicyRule)).all()
    assert {rule.type for rule in policy_rules} == {
        "vendor_allowlist",
        "spend_threshold",
        "category_budget",
        "time_window",
        "revenue_floor",
        "reserve_minimum",
        "revenue_allocation",
    }
    assert all(rule.status == "active" for rule in policy_rules)

    wallets = sqlite_session.scalars(select(Wallet)).all()
    assert {wallet.type for wallet in wallets} == {"revenue", "operating", "reserve"}
    assert all(wallet.balance == Decimal("0.00") for wallet in wallets)
    assert all(wallet.currency == "USD" for wallet in wallets)
    assert all(wallet.locked is False for wallet in wallets)

    kill_switch = sqlite_session.scalar(select(KillSwitchState))
    assert kill_switch.active is False
    assert kill_switch.reason == "MVP seed inactive state"


def test_seed_mvp_data_is_idempotent(sqlite_session, sandbox_settings):
    seed_mvp_data(sqlite_session, sandbox_settings)
    counts_after_first_seed = {
        model.__tablename__: count_rows(sqlite_session, model)
        for model in (Agent, Offer, Lead, PolicyRule, Wallet, KillSwitchState)
    }

    seed_mvp_data(sqlite_session, sandbox_settings)

    assert {
        model.__tablename__: count_rows(sqlite_session, model)
        for model in (Agent, Offer, Lead, PolicyRule, Wallet, KillSwitchState)
    } == counts_after_first_seed


def test_seed_deactivates_active_offers_removed_from_configuration(
    sqlite_session,
    sandbox_settings,
):
    stale_offer = Offer(
        id="stale-seed",
        name="Stale Seed Offer",
        price=Decimal("100.00"),
        currency="USD",
        status="active",
        allowed_channels=["stripe_checkout"],
    )
    sqlite_session.add(stale_offer)
    replacement_settings = sandbox_settings.model_copy(
        update={
            "offer_catalog": [
                OfferConfig(
                    id="ai-control-room-2000",
                    name="AI Agent Control Room",
                    price=Decimal("2000.00"),
                    currency="USD",
                    status="active",
                    allowed_channels=["stripe_subscription"],
                )
            ]
        }
    )

    seed_mvp_data(sqlite_session, replacement_settings)

    assert sqlite_session.get(Offer, "stale-seed").status == "inactive"
    assert sqlite_session.get(Offer, "ai-control-room-2000").status == "active"


def test_seed_validation_fails_closed_when_offer_catalog_is_empty(
    sqlite_session,
    sandbox_settings,
):
    invalid_settings = sandbox_settings.model_copy(update={"offer_catalog": []})

    with pytest.raises(ValueError, match="offer_catalog"):
        seed_mvp_data(sqlite_session, invalid_settings)


def test_seed_validation_fails_closed_when_mvp_wallet_allocation_is_missing(
    sqlite_session,
    sandbox_settings,
):
    invalid_allocation = RevenueAllocationConfig.model_construct(
        wallet_percentages={
            "revenue": Decimal("70"),
            "operating": Decimal("30"),
        }
    )
    invalid_settings = sandbox_settings.model_copy(
        update={"revenue_allocation": invalid_allocation}
    )

    with pytest.raises(ValueError, match="revenue, operating, and reserve"):
        seed_mvp_data(sqlite_session, invalid_settings)


def test_seed_validation_fails_closed_without_approved_sources_or_vendors(
    sqlite_session,
    sandbox_settings,
):
    inactive_source_settings = sandbox_settings.model_copy(
        update={
            "approved_demand_sources": [
                source.model_copy(update={"status": "inactive"})
                for source in sandbox_settings.approved_demand_sources
            ]
        }
    )
    with pytest.raises(ValueError, match="approved_demand_sources"):
        seed_mvp_data(sqlite_session, inactive_source_settings)

    inactive_vendor_settings = sandbox_settings.model_copy(
        update={
            "vendor_allowlist": [
                vendor.model_copy(update={"status": "inactive"})
                for vendor in sandbox_settings.vendor_allowlist
            ]
        }
    )
    with pytest.raises(ValueError, match="vendor_allowlist"):
        seed_mvp_data(sqlite_session, inactive_vendor_settings)


def test_seed_mvp_data_leaves_transaction_commit_to_caller(
    sqlite_session,
    sandbox_settings,
):
    seed_mvp_data(sqlite_session, sandbox_settings)

    assert sqlite_session.in_transaction()
