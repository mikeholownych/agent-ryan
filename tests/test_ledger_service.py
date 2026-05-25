from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import LedgerEntry


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


def test_append_ledger_entry_persists_financial_event_fields(sqlite_session):
    from ryan.ledger.service import append_ledger_entry

    occurred_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)

    entry = append_ledger_entry(
        sqlite_session,
        type="payment_settled",
        amount=Decimal("125.50"),
        currency="USD",
        reference_type="payment",
        reference_id="payment-123",
        actor="payments-service",
        metadata={"provider": "sandbox", "provider_reference": "provider-123"},
        timestamp=occurred_at,
    )

    persisted = sqlite_session.get(LedgerEntry, entry.id)
    assert persisted is not None
    assert persisted.type == "payment_settled"
    assert persisted.amount == Decimal("125.50")
    assert persisted.currency == "USD"
    assert persisted.reference_type == "payment"
    assert persisted.reference_id == "payment-123"
    assert persisted.actor == "payments-service"
    assert persisted.metadata_ == {
        "provider": "sandbox",
        "provider_reference": "provider-123",
    }
    assert persisted.timestamp == occurred_at


@pytest.mark.parametrize(
    ("reference_type", "reference_id"),
    [
        ("payment", "payment-123"),
        ("wallet", "wallet-123"),
        ("policy_decision", "policy-decision-123"),
        ("expense", "expense-123"),
        ("exception", "exception-123"),
        ("report", "report-123"),
        ("operator_action", "operator-action-123"),
    ],
)
def test_append_ledger_entry_supports_required_generic_reference_links(
    sqlite_session,
    reference_type,
    reference_id,
):
    from ryan.ledger.service import append_ledger_entry

    entry = append_ledger_entry(
        sqlite_session,
        type=f"{reference_type}_recorded",
        amount=None,
        currency=None,
        reference_type=reference_type,
        reference_id=reference_id,
        actor="system",
        metadata={},
    )

    assert entry.reference_type == reference_type
    assert entry.reference_id == reference_id


def test_list_ledger_entries_orders_by_timestamp_and_filters(sqlite_session):
    from ryan.ledger.service import append_ledger_entry, list_ledger_entries

    base_time = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    newer = append_ledger_entry(
        sqlite_session,
        type="wallet_transfer",
        amount=Decimal("10.00"),
        currency="USD",
        reference_type="wallet",
        reference_id="wallet-1",
        actor="wallet-service",
        metadata={},
        timestamp=base_time + timedelta(minutes=5),
    )
    older = append_ledger_entry(
        sqlite_session,
        type="payment_settled",
        amount=Decimal("125.50"),
        currency="USD",
        reference_type="payment",
        reference_id="payment-1",
        actor="payments-service",
        metadata={},
        timestamp=base_time,
    )
    middle = append_ledger_entry(
        sqlite_session,
        type="payment_settled",
        amount=Decimal("25.00"),
        currency="USD",
        reference_type="payment",
        reference_id="payment-2",
        actor="payments-service",
        metadata={},
        timestamp=base_time + timedelta(minutes=2),
    )

    assert [entry.id for entry in list_ledger_entries(sqlite_session)] == [
        older.id,
        middle.id,
        newer.id,
    ]
    assert [
        entry.id
        for entry in list_ledger_entries(
            sqlite_session,
            reference_type="payment",
            type="payment_settled",
            actor="payments-service",
        )
    ] == [older.id, middle.id]
    assert [
        entry.id
        for entry in list_ledger_entries(
            sqlite_session,
            reference_type="payment",
            reference_id="payment-2",
        )
    ] == [middle.id]


def test_append_compensating_entry_links_to_original_without_mutating_it(sqlite_session):
    from ryan.ledger.service import append_compensating_entry, append_ledger_entry

    original = append_ledger_entry(
        sqlite_session,
        type="expense_executed",
        amount=Decimal("40.00"),
        currency="USD",
        reference_type="expense",
        reference_id="expense-123",
        actor="expense-service",
        metadata={"vendor": "approved-vendor"},
        timestamp=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
    )
    original_snapshot = {
        "type": original.type,
        "amount": original.amount,
        "currency": original.currency,
        "reference_type": original.reference_type,
        "reference_id": original.reference_id,
        "actor": original.actor,
        "metadata": dict(original.metadata_),
    }

    compensation = append_compensating_entry(
        sqlite_session,
        original_entry_id=original.id,
        type="expense_correction",
        amount=Decimal("-40.00"),
        currency="USD",
        actor="operator:ops@example.com",
        metadata={"reason": "duplicate expense reversal"},
        timestamp=datetime(2026, 5, 25, 13, 0, tzinfo=UTC),
    )

    refreshed_original = sqlite_session.get(LedgerEntry, original.id)
    assert refreshed_original is not None
    assert {
        "type": refreshed_original.type,
        "amount": refreshed_original.amount,
        "currency": refreshed_original.currency,
        "reference_type": refreshed_original.reference_type,
        "reference_id": refreshed_original.reference_id,
        "actor": refreshed_original.actor,
        "metadata": refreshed_original.metadata_,
    } == original_snapshot
    assert compensation.id != original.id
    assert compensation.reference_type == "ledger_entry"
    assert compensation.reference_id == original.id
    assert compensation.amount == Decimal("-40.00")
    assert compensation.currency == "USD"
    assert compensation.metadata_ == {
        "compensates_ledger_entry_id": original.id,
        "original_reference_type": "expense",
        "original_reference_id": "expense-123",
        "reason": "duplicate expense reversal",
    }


def test_ledger_service_does_not_expose_update_or_delete_helpers():
    import ryan.ledger.service as ledger_service

    assert not hasattr(ledger_service, "update_ledger_entry")
    assert not hasattr(ledger_service, "delete_ledger_entry")


def test_append_ledger_entry_flushes_without_committing(sqlite_session):
    from ryan.ledger.service import append_ledger_entry

    entry = append_ledger_entry(
        sqlite_session,
        type="payment_created",
        amount=Decimal("25.00"),
        currency="USD",
        reference_type="payment",
        reference_id="payment-123",
        actor="payments-service",
        metadata={},
    )

    assert entry.id is not None
    sqlite_session.rollback()

    assert sqlite_session.scalars(select(LedgerEntry)).all() == []
