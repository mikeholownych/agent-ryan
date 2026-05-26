from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.idempotency import IdempotencyResponseReference, run_idempotent
from ryan.ledger import append_ledger_entry
from ryan.models import BucketAllocation, Payment, PolicyDecision, Wallet, WalletTransfer
from ryan.telemetry import emit_freeze_event, emit_unfreeze_event, emit_wallet_event

MVP_WALLET_ORDER = {"revenue": 0, "operating": 1, "reserve": 2}
WALLET_TRANSFER_IDEMPOTENCY_SCOPE = "wallet_transfer"
REVENUE_ALLOCATION_IDEMPOTENCY_SCOPE = "revenue_allocation"
MVP_WALLET_TYPES = frozenset(MVP_WALLET_ORDER)


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


def allocate_settled_revenue(
    session: Session,
    *,
    payment_id: str,
    source_wallet_id: str,
    allocations: dict[str, Decimal],
    currency: str,
    actor: str,
    allocation_rule_reference: str,
    idempotency_key: str,
) -> list[BucketAllocation]:
    payload = {
        "payment_id": payment_id,
        "source_wallet_id": source_wallet_id,
        "allocations": {key: str(value) for key, value in sorted(allocations.items())},
        "currency": currency,
        "actor": actor,
        "allocation_rule_reference": allocation_rule_reference,
    }
    response = run_idempotent(
        session,
        scope=REVENUE_ALLOCATION_IDEMPOTENCY_SCOPE,
        key=idempotency_key,
        request_payload=payload,
        operation=lambda: _execute_settled_revenue_allocation(
            session,
            payment_id=payment_id,
            source_wallet_id=source_wallet_id,
            allocations=allocations,
            currency=currency,
            actor=actor,
            allocation_rule_reference=allocation_rule_reference,
            idempotency_key=idempotency_key,
        ),
    )
    return _list_bucket_allocations_for_payment(
        session,
        payment_id=response.response_reference_id,
        idempotency_key=idempotency_key,
    )


def _execute_settled_revenue_allocation(
    session: Session,
    *,
    payment_id: str,
    source_wallet_id: str,
    allocations: dict[str, Decimal],
    currency: str,
    actor: str,
    allocation_rule_reference: str,
    idempotency_key: str,
) -> IdempotencyResponseReference:
    payment = session.get(Payment, payment_id)
    if payment is None or payment.status != "settled" or payment.currency != currency:
        raise WalletTransferError("revenue allocation requires a settled payment")

    _assert_valid_revenue_allocation(payment, allocations)
    source_wallet = _get_wallet_or_raise(session, source_wallet_id)
    if source_wallet.type != "revenue" or source_wallet.currency != currency:
        raise WalletTransferError("revenue allocation source must be the revenue wallet")
    if source_wallet.locked:
        raise WalletTransferError("revenue allocation source wallet is frozen")

    destination_wallets = _wallets_by_type(session, currency=currency)
    missing_wallet_types = sorted(MVP_WALLET_TYPES - set(destination_wallets))
    if missing_wallet_types:
        raise WalletTransferError(
            "missing destination wallet for allocation: "
            + ", ".join(missing_wallet_types)
        )

    created_allocations: list[BucketAllocation] = []
    for wallet_type in sorted(allocations, key=MVP_WALLET_ORDER.__getitem__):
        destination_wallet = destination_wallets[wallet_type]
        if destination_wallet.locked:
            raise WalletTransferError("revenue allocation destination wallet is frozen")
        allocation = BucketAllocation(
            payment_id=payment.id,
            source_wallet_id=source_wallet.id,
            destination_wallet_id=destination_wallet.id,
            amount=allocations[wallet_type],
            currency=currency,
            allocation_rule_reference=allocation_rule_reference,
            idempotency_key=f"{idempotency_key}:{wallet_type}",
        )
        session.add(allocation)
        session.flush()
        _apply_bucket_allocation(
            session,
            allocation=allocation,
            source_wallet=source_wallet,
            destination_wallet=destination_wallet,
            actor=actor,
        )
        created_allocations.append(allocation)

    return IdempotencyResponseReference(
        response_reference_type="payment",
        response_reference_id=payment.id,
    )


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
    _assert_transfer_preserves_source_minimum(source_wallet, amount)

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


def _assert_valid_revenue_allocation(
    payment: Payment,
    allocations: dict[str, Decimal],
) -> None:
    if set(allocations) != MVP_WALLET_TYPES:
        raise WalletTransferError("revenue allocation must include all MVP wallets")
    total = Decimal("0.00")
    for amount in allocations.values():
        _assert_valid_transfer_amount(amount)
        total += amount
    if total != payment.amount:
        raise WalletTransferError("revenue allocation must equal settled payment amount")


def _wallets_by_type(session: Session, *, currency: str) -> dict[str, Wallet]:
    return {
        wallet.type: wallet
        for wallet in session.scalars(select(Wallet).where(Wallet.currency == currency))
    }


def _apply_bucket_allocation(
    session: Session,
    *,
    allocation: BucketAllocation,
    source_wallet: Wallet,
    destination_wallet: Wallet,
    actor: str,
) -> None:
    if destination_wallet.id == source_wallet.id:
        _append_allocation_ledger_entry(
            session,
            allocation=allocation,
            wallet=destination_wallet,
            type="wallet.allocation.retained",
            amount=allocation.amount,
            actor=actor,
        )
        return

    if source_wallet.balance < allocation.amount:
        raise WalletTransferError("revenue allocation source has insufficient funds")
    source_wallet.balance -= allocation.amount
    destination_wallet.balance += allocation.amount
    session.flush()
    _append_allocation_ledger_entry(
        session,
        allocation=allocation,
        wallet=source_wallet,
        type="wallet.allocation.debit",
        amount=-allocation.amount,
        actor=actor,
    )
    _append_allocation_ledger_entry(
        session,
        allocation=allocation,
        wallet=destination_wallet,
        type="wallet.allocation.credit",
        amount=allocation.amount,
        actor=actor,
    )


def _append_allocation_ledger_entry(
    session: Session,
    *,
    allocation: BucketAllocation,
    wallet: Wallet,
    type: str,
    amount: Decimal,
    actor: str,
) -> None:
    append_ledger_entry(
        session,
        type=type,
        amount=amount,
        currency=allocation.currency,
        reference_type="bucket_allocation",
        reference_id=allocation.id,
        actor=actor,
        metadata={
            "payment_id": allocation.payment_id,
            "source_wallet_id": allocation.source_wallet_id,
            "destination_wallet_id": allocation.destination_wallet_id,
            "wallet_id": wallet.id,
            "allocation_rule_reference": allocation.allocation_rule_reference,
        },
    )


def _list_bucket_allocations_for_payment(
    session: Session,
    *,
    payment_id: str,
    idempotency_key: str,
) -> list[BucketAllocation]:
    allocations = list(
        session.scalars(
            select(BucketAllocation).where(
                BucketAllocation.payment_id == payment_id,
                BucketAllocation.idempotency_key.in_(
                    [
                        f"{idempotency_key}:{wallet_type}"
                        for wallet_type in MVP_WALLET_TYPES
                    ]
                ),
            )
        )
    )
    return sorted(
        allocations,
        key=lambda allocation: MVP_WALLET_ORDER[
            session.get(Wallet, allocation.destination_wallet_id).type
        ],
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


def _assert_transfer_preserves_source_minimum(
    source_wallet: Wallet,
    amount: Decimal,
) -> None:
    minimum = _decimal_limit(source_wallet.limits.get("minimum"))
    if minimum is None:
        return
    if source_wallet.balance - amount < minimum:
        raise WalletTransferError("wallet transfer would violate source wallet minimum")


def _decimal_limit(value: Any) -> Decimal | None:
    if value is None:
        return None
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < Decimal("0"):
        raise WalletTransferError("wallet minimum limit is invalid")
    return parsed


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
    "REVENUE_ALLOCATION_IDEMPOTENCY_SCOPE",
    "WALLET_TRANSFER_IDEMPOTENCY_SCOPE",
    "WalletPolicyError",
    "WalletNotFoundError",
    "WalletTransferError",
    "allocate_settled_revenue",
    "freeze_wallet",
    "list_wallets",
    "transfer_between_wallets",
    "unfreeze_wallet",
]
