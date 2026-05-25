from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.models import KillSwitchState
from ryan.telemetry import emit_kill_switch_event


READ_ONLY_ACTION_TYPES = frozenset(
    {
        "plan",
        "read",
        "status",
        "report",
        "list_wallets",
    }
)


class KillSwitchActiveError(PermissionError):
    """Raised when the global kill switch blocks an external action."""

    def __init__(
        self,
        *,
        action_type: str,
        kill_switch_state_id: str,
        reason: str,
    ) -> None:
        self.action_type = action_type
        self.kill_switch_state_id = kill_switch_state_id
        self.reason = reason
        super().__init__(
            "kill switch is active; "
            f"blocked action {action_type!r} for reason: {reason}"
        )


def get_kill_switch_state(session: Session) -> KillSwitchState:
    state = session.scalar(
        select(KillSwitchState)
        .order_by(KillSwitchState.active.desc(), KillSwitchState.activated_at.desc())
        .limit(1)
    )
    if state is not None:
        return state

    state = KillSwitchState(active=False, reason="default inactive state")
    session.add(state)
    session.flush()
    return state


def activate_kill_switch(
    session: Session,
    *,
    actor: str,
    reason: str,
    timestamp: datetime | None = None,
) -> KillSwitchState:
    occurred_at = timestamp or datetime.now(UTC)
    state = get_kill_switch_state(session)
    for existing_state in session.scalars(select(KillSwitchState)).all():
        existing_state.active = False
    state.active = True
    state.reason = reason
    state.activated_by_actor = actor
    state.activated_at = occurred_at
    state.deactivated_by_actor = None
    state.deactivated_at = None
    session.flush()

    emit_kill_switch_event(
        session,
        event_name="activated",
        kill_switch_state_id=state.id,
        actor=actor,
        metadata={"reason": reason, "active": True},
        timestamp=occurred_at,
    )
    return state


def deactivate_kill_switch(
    session: Session,
    *,
    actor: str,
    reason: str,
    timestamp: datetime | None = None,
) -> KillSwitchState:
    occurred_at = timestamp or datetime.now(UTC)
    state = get_kill_switch_state(session)
    for existing_state in session.scalars(select(KillSwitchState)).all():
        existing_state.active = False
        existing_state.reason = reason
        existing_state.deactivated_by_actor = actor
        existing_state.deactivated_at = occurred_at
    session.flush()

    emit_kill_switch_event(
        session,
        event_name="deactivated",
        kill_switch_state_id=state.id,
        actor=actor,
        metadata={"reason": reason, "active": False},
        timestamp=occurred_at,
    )
    return state


def assert_external_action_allowed(session: Session, *, action_type: str) -> None:
    state = get_kill_switch_state(session)
    if not state.active or action_type in READ_ONLY_ACTION_TYPES:
        return

    raise KillSwitchActiveError(
        action_type=action_type,
        kill_switch_state_id=state.id,
        reason=state.reason,
    )


__all__ = [
    "KillSwitchActiveError",
    "READ_ONLY_ACTION_TYPES",
    "activate_kill_switch",
    "assert_external_action_allowed",
    "deactivate_kill_switch",
    "get_kill_switch_state",
]
