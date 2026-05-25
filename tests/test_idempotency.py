from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.idempotency import (
    IdempotencyConflictError,
    IdempotencyResponseReference,
    run_idempotent,
)
from ryan.models import IdempotencyRecord


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


def test_first_call_creates_completed_record_and_executes_callback_once(sqlite_session):
    calls: list[str] = []

    def create_generic_money_mutation() -> IdempotencyResponseReference:
        calls.append("executed")
        return IdempotencyResponseReference(
            response_reference_type="generic_money_mutation",
            response_reference_id="mutation-1",
        )

    result = run_idempotent(
        sqlite_session,
        scope="payments.confirm",
        key="request-123",
        request_payload={"amount": "100.00", "currency": "USD"},
        operation=create_generic_money_mutation,
    )

    assert result == IdempotencyResponseReference(
        response_reference_type="generic_money_mutation",
        response_reference_id="mutation-1",
    )
    assert calls == ["executed"]

    record = sqlite_session.scalar(select(IdempotencyRecord))
    assert record is not None
    assert record.scope == "payments.confirm"
    assert record.idempotency_key == "request-123"
    assert record.status == "completed"
    assert record.response_reference_type == "generic_money_mutation"
    assert record.response_reference_id == "mutation-1"


def test_replay_with_same_payload_returns_stored_reference_without_callback(
    sqlite_session,
):
    calls: list[str] = []
    payload = {"currency": "USD", "amount": "100.00", "metadata": {"b": 2, "a": 1}}

    def create_generic_money_mutation() -> IdempotencyResponseReference:
        calls.append("executed")
        return IdempotencyResponseReference(
            response_reference_type="generic_money_mutation",
            response_reference_id="mutation-1",
        )

    first = run_idempotent(
        sqlite_session,
        scope="wallets.transfer",
        key="request-123",
        request_payload=payload,
        operation=create_generic_money_mutation,
    )
    replay = run_idempotent(
        sqlite_session,
        scope="wallets.transfer",
        key="request-123",
        request_payload={
            "metadata": {"a": 1, "b": 2},
            "amount": "100.00",
            "currency": "USD",
        },
        operation=lambda: pytest.fail("replay must not execute the mutation callback"),
    )

    records = sqlite_session.scalars(select(IdempotencyRecord)).all()
    assert replay == first
    assert calls == ["executed"]
    assert len(records) == 1


def test_same_scope_key_with_different_payload_fails_closed(sqlite_session):
    run_idempotent(
        sqlite_session,
        scope="ledger.append",
        key="request-123",
        request_payload={"reference_id": "payment-1"},
        operation=lambda: IdempotencyResponseReference(
            response_reference_type="ledger_entry",
            response_reference_id="ledger-1",
        ),
    )

    with pytest.raises(IdempotencyConflictError, match="request payload does not match"):
        run_idempotent(
            sqlite_session,
            scope="ledger.append",
            key="request-123",
            request_payload={"reference_id": "payment-2"},
            operation=lambda: pytest.fail("conflicting request must fail before callback"),
        )


def test_same_key_in_different_scope_is_allowed(sqlite_session):
    first = run_idempotent(
        sqlite_session,
        scope="payments.create",
        key="request-123",
        request_payload={"offer_id": "offer-1"},
        operation=lambda: IdempotencyResponseReference(
            response_reference_type="checkout_session",
            response_reference_id="checkout-1",
        ),
    )
    second = run_idempotent(
        sqlite_session,
        scope="payments.confirm",
        key="request-123",
        request_payload={"provider_reference": "provider-1"},
        operation=lambda: IdempotencyResponseReference(
            response_reference_type="payment",
            response_reference_id="payment-1",
        ),
    )

    assert first.response_reference_id == "checkout-1"
    assert second.response_reference_id == "payment-1"
    assert len(sqlite_session.scalars(select(IdempotencyRecord)).all()) == 2


def test_failed_callback_does_not_store_completed_success(sqlite_session):
    def fail_after_starting_mutation() -> IdempotencyResponseReference:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        run_idempotent(
            sqlite_session,
            scope="payments.confirm",
            key="request-123",
            request_payload={"provider_reference": "provider-1"},
            operation=fail_after_starting_mutation,
        )

    record = sqlite_session.scalar(select(IdempotencyRecord))
    assert record is not None
    assert record.status == "failed"
    assert record.response_reference_type is None
    assert record.response_reference_id is None


def test_run_idempotent_leaves_transaction_boundary_to_caller(sqlite_session):
    run_idempotent(
        sqlite_session,
        scope="payments.confirm",
        key="request-123",
        request_payload={"provider_reference": "provider-1"},
        operation=lambda: IdempotencyResponseReference(
            response_reference_type="payment",
            response_reference_id="payment-1",
        ),
    )

    sqlite_session.rollback()

    assert sqlite_session.scalars(select(IdempotencyRecord)).all() == []


def test_request_hash_uses_deterministic_canonical_json(sqlite_session):
    payload_a: dict[str, Any] = {
        "metadata": {"b": [2, 1], "a": {"nested": True}},
        "amount": "100.00",
    }
    payload_b: dict[str, Any] = {
        "amount": "100.00",
        "metadata": {"a": {"nested": True}, "b": [2, 1]},
    }

    run_idempotent(
        sqlite_session,
        scope="payments.confirm",
        key="request-123",
        request_payload=payload_a,
        operation=lambda: IdempotencyResponseReference(
            response_reference_type="payment",
            response_reference_id="payment-1",
        ),
    )

    replay = run_idempotent(
        sqlite_session,
        scope="payments.confirm",
        key="request-123",
        request_payload=payload_b,
        operation=lambda: pytest.fail("canonical JSON replay must not run callback"),
    )

    assert replay.response_reference_id == "payment-1"
