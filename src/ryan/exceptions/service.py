from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.models import ExceptionRecord
from ryan.telemetry import emit_exception_event

ALLOWED_EXCEPTION_TYPES = frozenset(
    {
        "policy_rejection",
        "policy_escalation",
        "budget_exhaustion",
        "invalid_payment_confirmation",
        "duplicate_event",
        "policy_uncertainty",
        "payment_uncertainty",
        "frozen_spend",
        "kill_switch_blocked",
        "outbound_email_blocked",
        "autonomy_offer_selection_blocked",
        "autonomy_checkout_blocked",
    }
)
ALLOWED_EXCEPTION_STATUSES = frozenset(
    {
        "open",
        "in_review",
        "resolved",
        "dismissed",
    }
)
RESOLVED_STATUSES = frozenset({"resolved", "dismissed"})


class ExceptionRecordError(ValueError):
    """Raised when an exception queue operation is invalid."""


def create_exception_record(
    session: Session,
    *,
    exception_type: str,
    severity: str,
    reason: str,
    reference_type: str,
    reference_id: str,
    actor: str,
    policy_decision_id: str | None = None,
    assigned_to: str | None = None,
) -> ExceptionRecord:
    _assert_allowed_exception_type(exception_type)
    exception = ExceptionRecord(
        type=exception_type,
        severity=severity,
        status="open",
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        policy_decision_id=policy_decision_id,
        assigned_to=assigned_to,
    )
    session.add(exception)
    session.flush()
    emit_exception_event(
        session,
        event_name="created",
        exception_id=exception.id,
        actor=actor,
        metadata={
            "type": exception_type,
            "severity": severity,
            "reason": reason,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "policy_decision_id": policy_decision_id,
        },
    )
    return exception


def list_exception_records(
    session: Session,
    *,
    status: str | None = "open",
) -> list[ExceptionRecord]:
    statement = select(ExceptionRecord)
    if status is not None:
        statement = statement.where(ExceptionRecord.status == status)
    return list(
        session.scalars(
            statement.order_by(ExceptionRecord.created_at.asc(), ExceptionRecord.id.asc())
        )
    )


def transition_exception_status(
    session: Session,
    *,
    exception_id: str,
    status: str,
    actor: str,
    reason: str,
) -> ExceptionRecord:
    if status not in ALLOWED_EXCEPTION_STATUSES:
        raise ExceptionRecordError(f"unsupported exception status {status!r}")
    exception = session.get(ExceptionRecord, exception_id)
    if exception is None:
        raise ExceptionRecordError(f"exception {exception_id!r} was not found")

    exception.status = status
    if status in RESOLVED_STATUSES:
        exception.resolved_at = datetime.now(UTC)
    session.flush()
    emit_exception_event(
        session,
        event_name="status_changed",
        exception_id=exception.id,
        actor=actor,
        metadata={
            "status": status,
            "reason": reason,
        },
    )
    return exception


def _assert_allowed_exception_type(exception_type: str) -> None:
    if exception_type not in ALLOWED_EXCEPTION_TYPES:
        raise ExceptionRecordError(f"unsupported exception type {exception_type!r}")


__all__ = [
    "ALLOWED_EXCEPTION_STATUSES",
    "ALLOWED_EXCEPTION_TYPES",
    "ExceptionRecordError",
    "create_exception_record",
    "list_exception_records",
    "transition_exception_status",
]
