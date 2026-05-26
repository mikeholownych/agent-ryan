from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.idempotency import IdempotencyResponseReference, run_idempotent
from ryan.ledger import append_ledger_entry
from ryan.models import PolicyDecision, Wallet, WalletTransfer
from ryan.telemetry import emit_freeze_event, emit_unfreeze_event, emit_wallet_event

MVP_WALLET_ORDER = {"revenue": 0, "operating": 1, "reserve": 2}
WALLET_TRANSFER_IDEMPOTENCY_SCOPE = "wallet_transfer"


class WalletNotFoundError(ValueError):
    """Raised when a wallet operation targets a missing wallet."""


class WalletPolicyError(PermissionError):
    """Raised when a wallet mutation is not covered by an approval decision."""


class WalletTransferError(ValueError):
    """Raised when a wallet transfer cannot be executed safely."""


def list_wallets(session: Session) -> list[Wallet]:
    wallets = list(session.scalars(select(Wallet)).all())
    return sorted(
        wallets,
        key=lambda wallet: (
            MVP_WALLET_ORDER.get(wallet.type, len(MVP_WALLET_ORDER)),
            wallet.currency,
            wallet.id,
        ),
    )


def freeze_wallet(
    session: Session,
    *,
    wallet_id: str,
    actor: str,
    reason: str,
) -> Wallet:
    wallet = _get_wallet_or_raise(session, wallet_id)
    wallet.locked = True
    session.flush()
    emit_freeze_event(
        session,
        wallet_id=wallet.id,
        actor=actor,
        metadata={"reason": reason},
    )
    return wallet


def unfreeze_wallet(
    session: Session,
    *,
    wallet_id: str,
    actor: str,
    reason: str,
) -> Wallet:
    wallet = _get_wallet_or_raise(session, wallet_id)
    wallet.locked = False
    session.flush()
    emit_unfreeze_event(
        session,
        wallet_id=wallet.id,
        actor=actor,
        metadata={"reason": reason},
    )
    return wallet


def transfer_between_wallets(
    session: Session,
    *,
    source_wallet_id: str,
    destination_wallet_id: str,
    amount: Decimal,
    currency: str,
    actor: str,
    reason: str,
    policy_decision_id: str,
    idempotency_key: str,
) -> WalletTransfer:
    payload = {
        "source_wallet_id": source_wallet_id,
        "destination_wallet_id": destination_wallet_id,
        "amount": str(amount),
        "currency": currency,
        "actor": actor,
        "reason": reason,
        "policy_decision_id": policy_decision_id,
    }

    response = run_idempotent(
        session,
        scope=WALLET_TRANSFER_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _execute_transfer(
            session,
            source_wallet_id=source_wallet_id,
            destination_wallet_id=destination_wallet_id,
            amount=amount,
            currency=currency,
            actor=actor,
            reason=reason,
            policy_decision_id=policy_decision_id,
            idempotency_key=idempotency_key,
        ),
    )
    transfer = session.get(WalletTransfer, response.response_reference_id)
    if transfer is None:
        raise WalletTransferError("idempotent wallet transfer reference is missing")
    return transfer


def _execute_transfer(
    session: Session,
    *,
    source_wallet_id: str,
    destination_wallet_id: str,
    amount: Decimal,
    currency: str,
    actor: str,
    reason: str,
    policy_decision_id: str,
    idempotency_key: str,
) -> IdempotencyResponseReference:
    _assert_approved_transfer_policy(
        session,
        policy_decision_id=policy_decision_id,
        idempotency_key=idempotency_key,
    )
    _assert_valid_transfer_amount(amount)
    if source_wallet_id == destination_wallet_id:
        raise WalletTransferError("wallet transfer source and destination must differ")

    source_wallet = _get_wallet_or_raise(session, source_wallet_id)
    destination_wallet = _get_wallet_or_raise(session, destination_wallet_id)
    if source_wallet.currency != currency or destination_wallet.currency != currency:
        raise WalletTransferError("wallet transfer currency must match both wallets")
    if source_wallet.locked or destination_wallet.locked:
        raise WalletTransferError("wallet transfer cannot involve a frozen wallet")
    if source_wallet.balance < amount:
        raise WalletTransferError("wallet transfer source has insufficient funds")

    transfer = WalletTransfer(
        source_wallet_id=source_wallet.id,
        destination_wallet_id=destination_wallet.id,
        amount=amount,
        currency=currency,
        status="executed",
        reason=reason,
        policy_decision_id=policy_decision_id,
        idempotency_key=idempotency_key,
    )
    session.add(transfer)
    session.flush()

    source_wallet.balance -= amount
    destination_wallet.balance += amount
    session.flush()

    _append_transfer_ledger_entries(
        session,
        transfer=transfer,
        source_wallet=source_wallet,
        destination_wallet=destination_wallet,
        actor=actor,
        reason=reason,
    )
    emit_wallet_event(
        session,
        event_name="transfer",
        wallet_id=source_wallet.id,
        actor=actor,
        metadata={
            "reason": reason,
            "wallet_transfer_id": transfer.id,
            "destination_wallet_id": destination_wallet.id,
            "amount": str(amount),
            "currency": currency,
        },
    )
    return IdempotencyResponseReference(
        response_reference_type="wallet_transfer",
        response_reference_id=transfer.id,
    )


def _assert_approved_transfer_policy(
    session: Session,
    *,
    policy_decision_id: str,
    idempotency_key: str,
) -> None:
    decision = session.get(PolicyDecision, policy_decision_id)
    if (
        decision is None
        or decision.action_type != "wallet_transfer"
        or decision.decision != "approve"
        or decision.request_reference_type != "wallet_transfer"
        or decision.request_reference_id != idempotency_key
    ):
        raise WalletPolicyError("wallet transfer requires an approved policy decision")


def _assert_valid_transfer_amount(amount: Decimal) -> None:
    if not amount.is_finite() or amount <= Decimal("0"):
        raise WalletTransferError("wallet transfer amount must be positive and finite")


def _append_transfer_ledger_entries(
    session: Session,
    *,
    transfer: WalletTransfer,
    source_wallet: Wallet,
    destination_wallet: Wallet,
    actor: str,
    reason: str,
) -> None:
    common_metadata: dict[str, Any] = {
        "reason": reason,
        "source_wallet_id": source_wallet.id,
        "destination_wallet_id": destination_wallet.id,
        "wallet_transfer_id": transfer.id,
    }
    append_ledger_entry(
        session,
        type="wallet.transfer.debit",
        amount=-transfer.amount,
        currency=transfer.currency,
        reference_type="wallet_transfer",
        reference_id=transfer.id,
        actor=actor,
        metadata={**common_metadata, "wallet_id": source_wallet.id},
    )
    append_ledger_entry(
        session,
        type="wallet.transfer.credit",
        amount=transfer.amount,
        currency=transfer.currency,
        reference_type="wallet_transfer",
        reference_id=transfer.id,
        actor=actor,
        metadata={**common_metadata, "wallet_id": destination_wallet.id},
    )


def _get_wallet_or_raise(session: Session, wallet_id: str) -> Wallet:
    wallet = session.get(Wallet, wallet_id)
    if wallet is None:
        raise WalletNotFoundError(f"wallet {wallet_id!r} was not found")
    return wallet


__all__ = [
    "WalletPolicyError",
    "WalletNotFoundError",
    "WalletTransferError",
    "freeze_wallet",
    "list_wallets",
    "transfer_between_wallets",
    "unfreeze_wallet",
]
