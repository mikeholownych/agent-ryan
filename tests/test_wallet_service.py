from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import LedgerEntry, Wallet
from ryan.wallets.service import (
    WalletNotFoundError,
    freeze_wallet,
    list_wallets,
    unfreeze_wallet,
)


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


def _create_wallets(session):
    wallets = [
        Wallet(
            type="revenue",
            balance=Decimal("100.00"),
            currency="USD",
            locked=False,
            limits={"allocation": "revenue"},
        ),
        Wallet(
            type="operating",
            balance=Decimal("50.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "5.00"},
        ),
        Wallet(
            type="reserve",
            balance=Decimal("25.00"),
            currency="USD",
            locked=False,
            limits={"minimum": "10.00"},
        ),
    ]
    session.add_all(wallets)
    session.flush()
    return {wallet.type: wallet for wallet in wallets}


def test_list_wallets_returns_mvp_wallets_in_stable_order(sqlite_session):
    _create_wallets(sqlite_session)

    wallets = list_wallets(sqlite_session)

    assert [wallet.type for wallet in wallets] == ["revenue", "operating", "reserve"]
    assert [wallet.currency for wallet in wallets] == ["USD", "USD", "USD"]


def test_freeze_wallet_locks_wallet_and_emits_audit_event(sqlite_session):
    wallets = _create_wallets(sqlite_session)

    frozen = freeze_wallet(
        sqlite_session,
        wallet_id=wallets["operating"].id,
        actor="operator:test",
        reason="suspected duplicate charge",
    )

    assert frozen.locked is True
    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reference_type == "wallet",
            LedgerEntry.reference_id == frozen.id,
            LedgerEntry.type == "audit.wallet.freeze",
        )
    )
    assert audit_entry is not None
    assert audit_entry.actor == "operator:test"
    assert audit_entry.metadata_["reason"] == "suspected duplicate charge"


def test_unfreeze_wallet_unlocks_wallet_and_emits_audit_event(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    wallets["operating"].locked = True
    sqlite_session.flush()

    unfrozen = unfreeze_wallet(
        sqlite_session,
        wallet_id=wallets["operating"].id,
        actor="operator:test",
        reason="review complete",
    )

    assert unfrozen.locked is False
    audit_entry = sqlite_session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.reference_type == "wallet",
            LedgerEntry.reference_id == unfrozen.id,
            LedgerEntry.type == "audit.wallet.unfreeze",
        )
    )
    assert audit_entry is not None
    assert audit_entry.actor == "operator:test"
    assert audit_entry.metadata_["reason"] == "review complete"


def test_freeze_unknown_wallet_fails_closed(sqlite_session):
    with pytest.raises(WalletNotFoundError):
        freeze_wallet(
            sqlite_session,
            wallet_id="missing-wallet",
            actor="operator:test",
            reason="unknown wallet should fail closed",
        )
