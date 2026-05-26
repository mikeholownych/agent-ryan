from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import LedgerEntry, PolicyDecision, Wallet, WalletTransfer
from ryan.wallets.service import (
    WalletPolicyError,
    WalletTransferError,
    WalletNotFoundError,
    freeze_wallet,
    list_wallets,
    transfer_between_wallets,
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


def _approved_transfer_policy(session, *, reference_id="wallet-transfer-001"):
    decision = PolicyDecision(
        action_type="wallet_transfer",
        decision="approve",
        reason="operator approved wallet transfer",
        rule_results={"operator_review": {"decision": "approve"}},
        request_reference_type="wallet_transfer",
        request_reference_id=reference_id,
        actor="operator:test",
    )
    session.add(decision)
    session.flush()
    return decision


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


def test_policy_approved_transfer_mutates_wallets_and_appends_ledger(
    sqlite_session,
):
    wallets = _create_wallets(sqlite_session)
    decision = _approved_transfer_policy(sqlite_session)

    transfer = transfer_between_wallets(
        sqlite_session,
        source_wallet_id=wallets["operating"].id,
        destination_wallet_id=wallets["reserve"].id,
        amount=Decimal("10.00"),
        currency="USD",
        actor="operator:test",
        reason="increase reserve",
        policy_decision_id=decision.id,
        idempotency_key="wallet-transfer-001",
    )

    assert transfer.status == "executed"
    assert wallets["operating"].balance == Decimal("40.00")
    assert wallets["reserve"].balance == Decimal("35.00")

    ledger_entries = list(
        sqlite_session.scalars(
            select(LedgerEntry)
            .where(
                LedgerEntry.reference_type == "wallet_transfer",
                LedgerEntry.reference_id == transfer.id,
            )
            .order_by(LedgerEntry.type.asc())
        )
    )
    assert [entry.type for entry in ledger_entries] == [
        "wallet.transfer.credit",
        "wallet.transfer.debit",
    ]
    assert {entry.amount for entry in ledger_entries} == {
        Decimal("10.00"),
        Decimal("-10.00"),
    }


def test_transfer_requires_approved_policy_decision(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    decision = PolicyDecision(
        action_type="wallet_transfer",
        decision="reject",
        reason="operator rejected wallet transfer",
        rule_results={},
        request_reference_type="wallet_transfer",
        request_reference_id="wallet-transfer-rejected",
        actor="operator:test",
    )
    sqlite_session.add(decision)
    sqlite_session.flush()

    with pytest.raises(WalletPolicyError):
        transfer_between_wallets(
            sqlite_session,
            source_wallet_id=wallets["operating"].id,
            destination_wallet_id=wallets["reserve"].id,
            amount=Decimal("10.00"),
            currency="USD",
            actor="operator:test",
            reason="rejected transfer",
            policy_decision_id=decision.id,
            idempotency_key="wallet-transfer-rejected",
        )

    assert wallets["operating"].balance == Decimal("50.00")
    assert wallets["reserve"].balance == Decimal("25.00")
    assert sqlite_session.scalar(select(WalletTransfer)) is None


def test_transfer_from_frozen_wallet_rejects_without_mutating(sqlite_session):
    wallets = _create_wallets(sqlite_session)
    wallets["operating"].locked = True
    decision = _approved_transfer_policy(
        sqlite_session,
        reference_id="wallet-transfer-frozen",
    )

    with pytest.raises(WalletTransferError):
        transfer_between_wallets(
            sqlite_session,
            source_wallet_id=wallets["operating"].id,
            destination_wallet_id=wallets["reserve"].id,
            amount=Decimal("10.00"),
            currency="USD",
            actor="operator:test",
            reason="frozen source",
            policy_decision_id=decision.id,
            idempotency_key="wallet-transfer-frozen",
        )

    assert wallets["operating"].balance == Decimal("50.00")
    assert wallets["reserve"].balance == Decimal("25.00")
    assert sqlite_session.scalar(select(WalletTransfer)) is None


def test_transfer_replay_does_not_duplicate_balance_or_ledger_mutation(
    sqlite_session,
):
    wallets = _create_wallets(sqlite_session)
    decision = _approved_transfer_policy(sqlite_session)
    payload = {
        "source_wallet_id": wallets["operating"].id,
        "destination_wallet_id": wallets["reserve"].id,
        "amount": Decimal("10.00"),
        "currency": "USD",
        "actor": "operator:test",
        "reason": "increase reserve",
        "policy_decision_id": decision.id,
        "idempotency_key": "wallet-transfer-001",
    }

    first_transfer = transfer_between_wallets(sqlite_session, **payload)
    second_transfer = transfer_between_wallets(sqlite_session, **payload)

    assert second_transfer.id == first_transfer.id
    assert wallets["operating"].balance == Decimal("40.00")
    assert wallets["reserve"].balance == Decimal("35.00")
    assert sqlite_session.scalar(select(func.count(WalletTransfer.id))) == 1
    assert (
        sqlite_session.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.reference_type == "wallet_transfer",
                LedgerEntry.reference_id == first_transfer.id,
            )
        )
        == 2
    )
