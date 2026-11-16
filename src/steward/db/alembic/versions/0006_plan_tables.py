"""plan tables: plan, ss_earnings, child, asset_class

Revision ID: 0006
Revises: 0005

Creates four tables and one index. Nothing alters the populated account table (M1-B: a batch alter
rebuilds it); child.account_id only references it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("saved_at", sa.DateTime(), nullable=False),
        sa.Column("saved_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("levers", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=False),
        sa.Column("comfortable_age", sa.Integer(), nullable=True),
        sa.Column("likely_age", sa.Integer(), nullable=True),
    )
    op.create_index("ix_plan_saved_at", "plan", ["saved_at"])
    op.create_table(
        "ss_earnings",
        sa.Column("person", sa.String(length=6), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("earnings_cents", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("person IN ('jr', 'spouse')", name="ck_ss_earnings_person"),
    )
    op.create_table(
        "child",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=False),
        sa.Column("cost_level", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("monthly_contribution_cents", sa.Integer(), nullable=False),
        sa.UniqueConstraint("account_id", name="uq_child_account"),
        sa.CheckConstraint("cost_level IN ('in_state_public', 'out_of_state_public', 'private')", name="ck_child_cost_level"),
    )
    op.create_table(
        "asset_class",
        sa.Column("symbol", sa.String(length=20), primary_key=True),
        sa.Column("class", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.CheckConstraint("class IN ('us_stock', 'intl_stock', 'bond', 'cash')", name="ck_asset_class_class"),
        sa.CheckConstraint("source IN ('builtin', 'override')", name="ck_asset_class_source"),
    )


def downgrade() -> None:
    op.drop_table("asset_class")
    op.drop_table("child")
    op.drop_table("ss_earnings")
    op.drop_index("ix_plan_saved_at", table_name="plan")
    op.drop_table("plan")
