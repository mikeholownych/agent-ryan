"""Multi-wallet module boundary."""
"""Wallet service boundary."""

from ryan.wallets.service import (
    WalletNotFoundError,
    freeze_wallet,
    list_wallets,
    unfreeze_wallet,
)

__all__ = [
    "WalletNotFoundError",
    "freeze_wallet",
    "list_wallets",
    "unfreeze_wallet",
]
