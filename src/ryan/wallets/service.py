from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.models import Wallet
from ryan.telemetry import emit_freeze_event, emit_unfreeze_event

MVP_WALLET_ORDER = {"revenue": 0, "operating": 1, "reserve": 2}


class WalletNotFoundError(ValueError):
    """Raised when a wallet operation targets a missing wallet."""


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


def _get_wallet_or_raise(session: Session, wallet_id: str) -> Wallet:
    wallet = session.get(Wallet, wallet_id)
    if wallet is None:
        raise WalletNotFoundError(f"wallet {wallet_id!r} was not found")
    return wallet


__all__ = [
    "WalletNotFoundError",
    "freeze_wallet",
    "list_wallets",
    "unfreeze_wallet",
]
