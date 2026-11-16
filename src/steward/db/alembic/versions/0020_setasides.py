"""set_aside, set_aside_match and set_aside_dismissed: costs spread over the months until they are due, the payments
matched to them, and the suggestions a person said no to

Revision ID: 0020
Revises: 0019

Phase 11c (Set-asides), Data. Three new tables; nothing else changes. Parent books get them too and never write to
them (every /setasides route is household only).
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

KIND_FIELDS = ("(kind = 'yearly' AND due_month IS NOT NULL AND due_day IS NOT NULL) OR "
               "(kind = 'twice_yearly' AND due_month IS NOT NULL AND due_day IS NOT NULL "
               "AND second_month IS NOT NULL AND second_day IS NOT NULL) OR "
               "(kind = 'one_off' AND due_year IS NOT NULL AND due_month IS NOT NULL)")
MONTHS_AND_DAYS = ("(due_month IS NULL OR due_month BETWEEN 1 AND 12) AND (due_day IS NULL OR due_day BETWEEN 1 AND 31) AND "
                   "(second_month IS NULL OR second_month BETWEEN 1 AND 12) AND (second_day IS NULL OR second_day BETWEEN 1 AND 31)")
HOW_HAS_PAYMENT = "(how = 'skipped' AND transaction_id IS NULL) OR (how <> 'skipped' AND transaction_id IS NOT NULL)"


def upgrade() -> None:
    op.create_table(
        "set_aside",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("due_month", sa.Integer(), nullable=True),
        sa.Column("due_day", sa.Integer(), nullable=True),
        sa.Column("second_month", sa.Integer(), nullable=True),
        sa.Column("second_day", sa.Integer(), nullable=True),
        sa.Column("due_year", sa.Integer(), nullable=True),
        sa.Column("first_month", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("payee_key", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("estimate", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('yearly', 'twice_yearly', 'one_off')", name="ck_set_aside_kind"),
        sa.CheckConstraint("amount_cents > 0", name="ck_set_aside_amount"),
        sa.CheckConstraint(KIND_FIELDS, name="ck_set_aside_kind_fields"),
        sa.CheckConstraint(MONTHS_AND_DAYS, name="ck_set_aside_months_days"),
    )
    op.create_index("ix_set_aside_account_id", "set_aside", ["account_id"])
    op.create_table(
        "set_aside_match",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transaction.id"), nullable=True),
        sa.Column("set_aside_id", sa.Integer(), sa.ForeignKey("set_aside.id"), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("how", sa.String(length=8), nullable=False),
        sa.Column("late", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("how IN ('auto', 'hand', 'refused', 'skipped')", name="ck_set_aside_match_how"),
        sa.CheckConstraint(HOW_HAS_PAYMENT, name="ck_set_aside_match_payment"),
    )
    op.create_index("uq_set_aside_match_txn", "set_aside_match", ["transaction_id"], unique=True,
                    sqlite_where=sa.text("transaction_id IS NOT NULL"))
    op.create_index("uq_set_aside_match_due", "set_aside_match", ["set_aside_id", "due_on"], unique=True,
                    sqlite_where=sa.text("how <> 'refused'"))
    op.create_table(
        "set_aside_dismissed",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payee_key", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("payee_key", "category", name="uq_set_aside_dismissed"),
    )


def downgrade() -> None:
    op.drop_table("set_aside_dismissed")
    op.drop_index("uq_set_aside_match_due", table_name="set_aside_match")
    op.drop_index("uq_set_aside_match_txn", table_name="set_aside_match")
    op.drop_table("set_aside_match")
    op.drop_index("ix_set_aside_account_id", table_name="set_aside")
    op.drop_table("set_aside")
