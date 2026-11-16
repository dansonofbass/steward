"""duplicate_keep

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duplicate_keep",
        sa.Column("a_id", sa.Integer(), sa.ForeignKey("transaction.id"), primary_key=True),
        sa.Column("b_id", sa.Integer(), sa.ForeignKey("transaction.id"), primary_key=True),
        sa.Column("kept_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_txn_account_amount", "transaction", ["account_id", "amount_cents"])


def downgrade() -> None:
    op.drop_index("ix_txn_account_amount", table_name="transaction")
    op.drop_table("duplicate_keep")
