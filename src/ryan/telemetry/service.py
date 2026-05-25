from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ryan.ledger import append_ledger_entry
from ryan.models import LedgerEntry


@dataclass(frozen=True)
class ActionEvent:
    domain: str
    event_name: str
    actor: str
    reference_type: str
    reference_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None


@dataclass(frozen=True)
class AlertEvent:
    alert_type: str
    severity: str
    actor: str
    reference_type: str
    reference_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime | None = None


def emit_action_event(
    session: Session,
    *,
    domain: str,
    event_name: str,
    actor: str,
    reference_type: str,
    reference_id: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    event = ActionEvent(
        domain=domain,
        event_name=event_name,
        actor=actor,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata or {},
        timestamp=timestamp,
    )
    event_metadata = dict(event.metadata)
    event_metadata.update(
        {
            "telemetry_kind": "action",
            "domain": event.domain,
            "event_name": event.event_name,
        }
    )
    return append_ledger_entry(
        session,
        type=f"audit.{event.domain}.{event.event_name}",
        amount=None,
        currency=None,
        reference_type=event.reference_type,
        reference_id=event.reference_id,
        actor=event.actor,
        metadata=event_metadata,
        timestamp=event.timestamp,
    )


def emit_alert(
    session: Session,
    *,
    alert_type: str,
    severity: str,
    actor: str,
    reference_type: str,
    reference_id: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    event = AlertEvent(
        alert_type=alert_type,
        severity=severity,
        actor=actor,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata or {},
        timestamp=timestamp,
    )
    event_metadata = dict(event.metadata)
    event_metadata.update(
        {
            "telemetry_kind": "alert",
            "alert_type": event.alert_type,
            "severity": event.severity,
            "requires_operator_review": True,
        }
    )
    return append_ledger_entry(
        session,
        type=f"alert.{event.alert_type}",
        amount=None,
        currency=None,
        reference_type=event.reference_type,
        reference_id=event.reference_id,
        actor=event.actor,
        metadata=event_metadata,
        timestamp=event.timestamp,
    )


def emit_policy_event(
    session: Session,
    *,
    event_name: str,
    policy_decision_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="policy",
        event_name=event_name,
        actor=actor,
        reference_type="policy_decision",
        reference_id=policy_decision_id,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_payment_event(
    session: Session,
    *,
    event_name: str,
    payment_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="payment",
        event_name=event_name,
        actor=actor,
        reference_type="payment",
        reference_id=payment_id,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_wallet_event(
    session: Session,
    *,
    event_name: str,
    wallet_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="wallet",
        event_name=event_name,
        actor=actor,
        reference_type="wallet",
        reference_id=wallet_id,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_expense_event(
    session: Session,
    *,
    event_name: str,
    expense_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="expense",
        event_name=event_name,
        actor=actor,
        reference_type="expense",
        reference_id=expense_id,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_exception_event(
    session: Session,
    *,
    event_name: str,
    exception_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="exception",
        event_name=event_name,
        actor=actor,
        reference_type="exception",
        reference_id=exception_id,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_kill_switch_event(
    session: Session,
    *,
    event_name: str,
    kill_switch_state_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="kill_switch",
        event_name=event_name,
        actor=actor,
        reference_type="kill_switch",
        reference_id=kill_switch_state_id,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_freeze_event(
    session: Session,
    *,
    wallet_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_wallet_event(
        session,
        event_name="freeze",
        wallet_id=wallet_id,
        actor=actor,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_unfreeze_event(
    session: Session,
    *,
    wallet_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_wallet_event(
        session,
        event_name="unfreeze",
        wallet_id=wallet_id,
        actor=actor,
        metadata=metadata,
        timestamp=timestamp,
    )


def emit_report_event(
    session: Session,
    *,
    event_name: str,
    report_id: str,
    actor: str,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> LedgerEntry:
    return emit_action_event(
        session,
        domain="report",
        event_name=event_name,
        actor=actor,
        reference_type="report",
        reference_id=report_id,
        metadata=metadata,
        timestamp=timestamp,
    )


__all__ = [
    "ActionEvent",
    "AlertEvent",
    "emit_action_event",
    "emit_alert",
    "emit_exception_event",
    "emit_expense_event",
    "emit_freeze_event",
    "emit_kill_switch_event",
    "emit_payment_event",
    "emit_policy_event",
    "emit_report_event",
    "emit_unfreeze_event",
    "emit_wallet_event",
]
