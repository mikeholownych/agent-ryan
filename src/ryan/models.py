from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ryan.db import Base


def _uuid() -> str:
    return str(uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    current_objective: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)


class Offer(Base, TimestampMixin):
    __tablename__ = "offers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed_channels: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("source", "source_reference", name="uq_leads_source_reference"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_reference: Mapped[str | None] = mapped_column(String(255), unique=True)
    email_or_contact_reference: Mapped[str | None] = mapped_column(String(255))


class CheckoutSession(Base, TimestampMixin):
    __tablename__ = "checkout_sessions"
    __table_args__ = (
        UniqueConstraint(
            "payment_provider",
            "provider_reference",
            name="uq_checkout_sessions_provider_reference",
        ),
        UniqueConstraint("idempotency_key", name="uq_checkout_sessions_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    offer_id: Mapped[str] = mapped_column(ForeignKey("offers.id"), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_provider: Mapped[str | None] = mapped_column(String(128))
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    checkout_url: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint(
            "payment_provider",
            "provider_reference",
            name="uq_invoices_provider_reference",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    offer_id: Mapped[str] = mapped_column(ForeignKey("offers.id"), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_provider: Mapped[str | None] = mapped_column(String(128))
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint(
            "payment_provider",
            "provider_reference",
            name="uq_payments_provider_reference",
        ),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    checkout_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("checkout_sessions.id")
    )
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    payment_provider: Mapped[str | None] = mapped_column(String(128))
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    settlement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rule_results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_reference_type: Mapped[str] = mapped_column(String(128), nullable=False)
    request_reference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ExpenseRequest(Base, TimestampMixin):
    __tablename__ = "expense_requests"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_expense_requests_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    policy_status: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("policy_decisions.id")
    )
    source_wallet_id: Mapped[str | None] = mapped_column(ForeignKey("wallets.id"))
    execution_status: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_by_actor: Mapped[str] = mapped_column(String(255), nullable=False)


class PolicyRule(Base, TimestampMixin):
    __tablename__ = "policy_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(nullable=False)
    created_by_actor: Mapped[str] = mapped_column(String(255), nullable=False)


class Wallet(Base, TimestampMixin):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint(
            "type in ('revenue', 'operating', 'reserve')",
            name="ck_wallets_type_mvp",
        ),
        UniqueConstraint("type", "currency", name="uq_wallets_type_currency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class BucketAllocation(Base):
    __tablename__ = "bucket_allocations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_bucket_allocations_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), nullable=False)
    source_wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False)
    destination_wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    allocation_rule_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class WalletTransfer(Base, TimestampMixin):
    __tablename__ = "wallet_transfers"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wallet_transfers_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), nullable=False)
    destination_wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("policy_decisions.id")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_ledger_entries_reference", "reference_type", "reference_id"),
        {"info": {"append_only_mvp_guard": "no update/delete columns; DB trigger deferred"}},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    reference_type: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ExceptionRecord(Base):
    __tablename__ = "exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("policy_decisions.id")
    )
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class KillSwitchState(Base):
    __tablename__ = "kill_switch_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    activated_by_actor: Mapped[str | None] = mapped_column(String(255))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_by_actor: Mapped[str | None] = mapped_column(String(255))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "idempotency_key",
            name="uq_idempotency_records_scope_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    response_reference_type: Mapped[str | None] = mapped_column(String(128))
    response_reference_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Agent",
    "BucketAllocation",
    "CheckoutSession",
    "Customer",
    "ExceptionRecord",
    "ExpenseRequest",
    "IdempotencyRecord",
    "Invoice",
    "KillSwitchState",
    "Lead",
    "LedgerEntry",
    "Offer",
    "Payment",
    "PolicyDecision",
    "PolicyRule",
    "Report",
    "Wallet",
    "WalletTransfer",
]
