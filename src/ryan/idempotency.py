from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.models import IdempotencyRecord


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key cannot be safely replayed."""


@dataclass(frozen=True)
class IdempotencyResponseReference:
    response_reference_type: str
    response_reference_id: str


def run_idempotent(
    session: Session,
    *,
    scope: str,
    key: str,
    request_payload: Any,
    operation: Callable[[], IdempotencyResponseReference],
) -> IdempotencyResponseReference:
    request_hash = hash_request_payload(request_payload)
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == key,
        )
    )

    if record is not None:
        return _resolve_existing_record(record, request_hash)

    record = IdempotencyRecord(
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
        status="in_progress",
    )
    session.add(record)
    session.flush()

    try:
        response_reference = operation()
    except Exception:
        record.status = "failed"
        record.response_reference_type = None
        record.response_reference_id = None
        session.flush()
        raise

    record.status = "completed"
    record.response_reference_type = response_reference.response_reference_type
    record.response_reference_id = response_reference.response_reference_id
    session.flush()
    return response_reference


def hash_request_payload(request_payload: Any) -> str:
    canonical_payload = json.dumps(
        request_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _resolve_existing_record(
    record: IdempotencyRecord,
    request_hash: str,
) -> IdempotencyResponseReference:
    if record.request_hash != request_hash:
        raise IdempotencyConflictError(
            "idempotency request payload does not match the original request"
        )

    if (
        record.status == "completed"
        and record.response_reference_type is not None
        and record.response_reference_id is not None
    ):
        return IdempotencyResponseReference(
            response_reference_type=record.response_reference_type,
            response_reference_id=record.response_reference_id,
        )

    raise IdempotencyConflictError(
        f"idempotency record is not replayable while status is {record.status!r}"
    )


__all__ = [
    "IdempotencyConflictError",
    "IdempotencyResponseReference",
    "hash_request_payload",
    "run_idempotent",
]
