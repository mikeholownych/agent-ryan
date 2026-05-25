from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from ryan.db import Base, create_database_engine
from ryan.models import IdempotencyRecord, LedgerEntry, Payment, Wallet


EXPECTED_TABLES = {
    "agents",
    "offers",
    "leads",
    "customers",
    "checkout_sessions",
    "invoices",
    "payments",
    "expense_requests",
    "policy_rules",
    "policy_decisions",
    "wallets",
    "bucket_allocations",
    "wallet_transfers",
    "ledger_entries",
    "exceptions",
    "reports",
    "kill_switch_states",
    "idempotency_records",
}


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


def test_metadata_contains_required_schema_tables():
    assert EXPECTED_TABLES.issubset(Base.metadata.tables)


def test_schema_create_and_drop_works_in_sqlite():
    engine = create_database_engine("sqlite:///:memory:")

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))

    Base.metadata.drop_all(engine)
    inspector = inspect(engine)
    assert not EXPECTED_TABLES.intersection(inspector.get_table_names())


def test_wallet_type_constraint_rejects_non_mvp_wallet_type(sqlite_session):
    sqlite_session.add(
        Wallet(
            type="marketing",
            balance=Decimal("0.00"),
            currency="USD",
            locked=False,
            limits={},
        )
    )

    with pytest.raises(IntegrityError):
        sqlite_session.commit()


def test_idempotency_key_is_unique_within_scope(sqlite_session):
    first = IdempotencyRecord(
        idempotency_key="request-123",
        scope="payments.confirm",
        request_hash="same-request",
        status="completed",
    )
    duplicate = IdempotencyRecord(
        idempotency_key="request-123",
        scope="payments.confirm",
        request_hash="same-request",
        status="completed",
    )
    different_scope = IdempotencyRecord(
        idempotency_key="request-123",
        scope="payments.create",
        request_hash="same-request",
        status="completed",
    )

    sqlite_session.add_all([first, different_scope])
    sqlite_session.commit()

    sqlite_session.add(duplicate)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()


def test_payment_provider_reference_is_unique_when_present(sqlite_session):
    first = Payment(
        amount=Decimal("100.00"),
        currency="USD",
        status="settled",
        source="checkout",
        payment_provider="sandbox",
        provider_reference="provider-payment-123",
    )
    duplicate = Payment(
        amount=Decimal("100.00"),
        currency="USD",
        status="settled",
        source="checkout",
        payment_provider="sandbox",
        provider_reference="provider-payment-123",
    )
    no_provider_reference_a = Payment(
        amount=Decimal("100.00"),
        currency="USD",
        status="created",
        source="checkout",
        payment_provider="sandbox",
    )
    no_provider_reference_b = Payment(
        amount=Decimal("100.00"),
        currency="USD",
        status="created",
        source="checkout",
        payment_provider="sandbox",
    )

    sqlite_session.add_all([first, no_provider_reference_a, no_provider_reference_b])
    sqlite_session.commit()

    sqlite_session.add(duplicate)
    with pytest.raises(IntegrityError):
        sqlite_session.commit()


def test_ledger_entry_schema_has_append_only_mvp_guard_fields():
    assert not hasattr(LedgerEntry, "updated_at")
    assert not hasattr(LedgerEntry, "deleted_at")

    required_columns = {
        "type",
        "reference_type",
        "reference_id",
        "timestamp",
        "actor",
    }
    for column_name in required_columns:
        assert LedgerEntry.__table__.c[column_name].nullable is False

    entry = LedgerEntry(
        type="payment_settled",
        amount=Decimal("100.00"),
        currency="USD",
        reference_type="payment",
        reference_id="payment-123",
        timestamp=datetime.now(UTC),
        actor="system",
        metadata_={},
    )
    assert entry.reference_id == "payment-123"
