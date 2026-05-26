"""Multi-wallet module boundary."""
"""Wallet service boundary."""

from ryan.wallets.service import (
    WalletPolicyError,
    WalletNotFoundError,
    WalletTransferError,
    freeze_wallet,
    list_wallets,
    transfer_between_wallets,
    unfreeze_wallet,
)

__all__ = [
    "WalletPolicyError",
    "WalletNotFoundError",
    "WalletTransferError",
    "freeze_wallet",
    "list_wallets",
    "transfer_between_wallets",
    "unfreeze_wallet",
]
