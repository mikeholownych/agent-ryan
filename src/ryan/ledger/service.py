from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.models import LedgerEntry


class LedgerEntryNotFoundError(ValueError):
    """Raised when a compensating entry targets a missing ledger entry."""


def append_ledger_entry(
    session: Session,
    *,
    type: str,
    amount: Decimal | None,
    currency: str | None,
    reference_type: str,
    reference_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    entry = LedgerEntry(
        type=type,
        amount=amount,
        currency=currency,
        reference_type=reference_type,
        reference_id=reference_id,
        actor=actor,
        metadata_=metadata or {},
        timestamp=timestamp or datetime.now(UTC),
    )
    session.add(entry)
    session.flush()
    return entry


def list_ledger_entries(
    session: Session,
    *,
    reference_type: str | None = None,
    reference_id: str | None = None,
    type: str | None = None,
    actor: str | None = None,
) -> list[LedgerEntry]:
    query = select(LedgerEntry)
    if reference_type is not None:
        query = query.where(LedgerEntry.reference_type == reference_type)
    if reference_id is not None:
        query = query.where(LedgerEntry.reference_id == reference_id)
    if type is not None:
        query = query.where(LedgerEntry.type == type)
    if actor is not None:
        query = query.where(LedgerEntry.actor == actor)

    query = query.order_by(LedgerEntry.timestamp.asc(), LedgerEntry.id.asc())
    return list(session.scalars(query).all())


def append_compensating_entry(
    session: Session,
    *,
    original_entry_id: str,
    type: str,
    actor: str,
    amount: Decimal | None = None,
    currency: str | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    original = session.get(LedgerEntry, original_entry_id)
    if original is None:
        raise LedgerEntryNotFoundError(
            f"ledger entry {original_entry_id!r} was not found"
        )

    correction_metadata: dict[str, Any] = {
        "compensates_ledger_entry_id": original.id,
        "original_reference_type": original.reference_type,
        "original_reference_id": original.reference_id,
    }
    correction_metadata.update(metadata or {})

    return append_ledger_entry(
        session,
        type=type,
        amount=amount if amount is not None else _negate_amount(original.amount),
        currency=currency if currency is not None else original.currency,
        reference_type="ledger_entry",
        reference_id=original.id,
        actor=actor,
        metadata=correction_metadata,
        timestamp=timestamp,
    )


def _negate_amount(amount: Decimal | None) -> Decimal | None:
    if amount is None:
        return None
    return -amount


__all__ = [
    "LedgerEntryNotFoundError",
    "append_compensating_entry",
    "append_ledger_entry",
    "list_ledger_entries",
]
