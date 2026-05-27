"""add outbound payment fields to expenses

Revision ID: 9b23a4d7e8f1
Revises: 5d79256e586a
Create Date: 2026-05-27 02:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "9b23a4d7e8f1"
down_revision: str | Sequence[str] | None = "5d79256e586a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "expense_requests",
        sa.Column("outbound_payment_provider", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "expense_requests",
        sa.Column("outbound_payment_reference", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "expense_requests",
        sa.Column("outbound_payment_status", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("expense_requests", "outbound_payment_status")
    op.drop_column("expense_requests", "outbound_payment_reference")
    op.drop_column("expense_requests", "outbound_payment_provider")
