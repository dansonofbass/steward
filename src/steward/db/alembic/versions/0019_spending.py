"""spending_target and spending_prefs: each category's kind and monthly target, and when one is running ahead

Revision ID: 0019
Revises: 0018

Phase 11b (Spending and budgets), Data. Two new tables; nothing else changes. Parent books get them too and never
write to them (every /spending route is household only).
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spending_target",
        sa.Column("category", sa.String(length=40), primary_key=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("monthly_cents", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('everyday', 'fixed', 'occasional')", name="ck_spending_target_kind"),
        sa.CheckConstraint("monthly_cents IS NULL OR monthly_cents >= 0", name="ck_spending_target_cents"),
    )
    op.create_table(
        "spending_prefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("warn_pct_bp", sa.Integer(), nullable=False),
        sa.Column("warn_min_cents", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_spending_prefs_one_row"),
    )


def downgrade() -> None:
    op.drop_table("spending_prefs")
    op.drop_table("spending_target")
