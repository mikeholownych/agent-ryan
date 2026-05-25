from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import KillSwitchState, LedgerEntry


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@pytest.fixture()
def sqlite_session():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    try:
        with Session() as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)


def test_get_kill_switch_state_returns_existing_seeded_state(sqlite_session):
    from ryan.kill_switch import get_kill_switch_state

    seeded = KillSwitchState(active=False, reason="MVP seed inactive state")
    sqlite_session.add(seeded)
    sqlite_session.flush()

    state = get_kill_switch_state(sqlite_session)

    assert state.id == seeded.id
    assert state.active is False
    assert state.reason == "MVP seed inactive state"


def test_get_kill_switch_state_creates_inactive_default_when_absent(sqlite_session):
    from ryan.kill_switch import get_kill_switch_state

    state = get_kill_switch_state(sqlite_session)

    assert state.id is not None
    assert state.active is False
    assert state.reason == "default inactive state"
    assert state.activated_by_actor is None
    assert state.activated_at is None
    assert sqlite_session.get(KillSwitchState, state.id) is not None


def test_activate_kill_switch_marks_active_and_appends_audit_event(sqlite_session):
    from ryan.kill_switch import activate_kill_switch

    occurred_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)

    state = activate_kill_switch(
        sqlite_session,
        actor="operator:ops@example.com",
        reason="duplicate charge investigation",
        timestamp=occurred_at,
    )

    assert state.active is True
    assert state.reason == "duplicate charge investigation"
    assert state.activated_by_actor == "operator:ops@example.com"
    assert state.activated_at == occurred_at

    entries = sqlite_session.scalars(select(LedgerEntry)).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.type == "audit.kill_switch.activated"
    assert entry.amount is None
    assert entry.currency is None
    assert entry.reference_type == "kill_switch"
    assert entry.reference_id == state.id
    assert entry.actor == "operator:ops@example.com"
    assert _as_utc(entry.timestamp) == occurred_at
    assert entry.metadata_ == {
        "telemetry_kind": "action",
        "domain": "kill_switch",
        "event_name": "activated",
        "reason": "duplicate charge investigation",
        "active": True,
    }


def test_deactivate_kill_switch_marks_inactive_and_appends_audit_event(
    sqlite_session,
):
    from ryan.kill_switch import activate_kill_switch, deactivate_kill_switch

    activate_kill_switch(
        sqlite_session,
        actor="operator:ops@example.com",
        reason="duplicate charge investigation",
        timestamp=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
    )
    occurred_at = datetime(2026, 5, 25, 13, 0, tzinfo=UTC)

    state = deactivate_kill_switch(
        sqlite_session,
        actor="operator:ops@example.com",
        reason="investigation complete",
        timestamp=occurred_at,
    )

    assert state.active is False
    assert state.reason == "investigation complete"
    assert state.deactivated_by_actor == "operator:ops@example.com"
    assert state.deactivated_at == occurred_at

    entries = sqlite_session.scalars(
        select(LedgerEntry).order_by(LedgerEntry.timestamp.asc())
    ).all()
    assert [entry.type for entry in entries] == [
        "audit.kill_switch.activated",
        "audit.kill_switch.deactivated",
    ]
    deactivation = entries[-1]
    assert deactivation.reference_type == "kill_switch"
    assert deactivation.reference_id == state.id
    assert deactivation.actor == "operator:ops@example.com"
    assert _as_utc(deactivation.timestamp) == occurred_at
    assert deactivation.metadata_ == {
        "telemetry_kind": "action",
        "domain": "kill_switch",
        "event_name": "deactivated",
        "reason": "investigation complete",
        "active": False,
    }


@pytest.mark.parametrize(
    "action_type",
    ["plan", "read", "status", "report", "list_wallets"],
)
def test_kill_switch_guard_permits_read_only_actions_while_active(
    sqlite_session,
    action_type,
):
    from ryan.kill_switch import activate_kill_switch, assert_external_action_allowed

    activate_kill_switch(
        sqlite_session,
        actor="operator:ops@example.com",
        reason="operator stop",
    )

    assert_external_action_allowed(sqlite_session, action_type=action_type)


@pytest.mark.parametrize(
    "action_type",
    [
        "external_spend",
        "external_send",
        "payment_create",
        "payment_refund",
        "wallet_transfer",
        "expense_execute",
    ],
)
def test_kill_switch_guard_blocks_external_actions_while_active(
    sqlite_session,
    action_type,
):
    from ryan.kill_switch import (
        KillSwitchActiveError,
        activate_kill_switch,
        assert_external_action_allowed,
    )

    state = activate_kill_switch(
        sqlite_session,
        actor="operator:ops@example.com",
        reason="operator stop",
    )

    with pytest.raises(KillSwitchActiveError) as exc_info:
        assert_external_action_allowed(sqlite_session, action_type=action_type)

    assert exc_info.value.kill_switch_state_id == state.id
    assert exc_info.value.action_type == action_type
    assert "operator stop" in str(exc_info.value)


def test_kill_switch_guard_allows_external_actions_when_inactive(sqlite_session):
    from ryan.kill_switch import assert_external_action_allowed

    assert_external_action_allowed(sqlite_session, action_type="wallet_transfer")


def test_kill_switch_service_flushes_without_committing(sqlite_session):
    from ryan.kill_switch import activate_kill_switch

    state = activate_kill_switch(
        sqlite_session,
        actor="operator:ops@example.com",
        reason="operator stop",
    )

    assert state.id is not None
    assert sqlite_session.scalars(select(LedgerEntry)).all()

    sqlite_session.rollback()

    assert sqlite_session.scalars(select(KillSwitchState)).all() == []
    assert sqlite_session.scalars(select(LedgerEntry)).all() == []
