"""care: care_setup, care_scenario, care_quote

Revision ID: 0015
Revises: 0014

Parent care plan Task 2 (spec 4). Three new tables; nothing else changes. Household books get them too and never
write to them (every Care route is parent only).
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

LEVELS = ("at_home", "in_home_help", "assisted_living", "memory_care", "nursing_home")


def upgrade() -> None:
    op.create_table(
        "care_setup",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("person", sa.String(length=40), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=False),
        sa.Column("spouse_birth_year", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("care_inflation_bp", sa.Integer(), nullable=False, server_default="400"),
        sa.Column("spending_monthly_cents", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_care_setup_one_row"),
    )
    op.create_table(
        "care_scenario",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("hours_week", sa.Integer(), nullable=True),
        sa.Column("adult_day_days", sa.Integer(), nullable=True),
        sa.Column("room", sa.String(length=8), nullable=True),
        sa.Column("sell_home_year", sa.Integer(), nullable=True),
        sa.Column("home_price_cents", sa.Integer(), nullable=True),
        sa.Column("home_basis_cents", sa.Integer(), nullable=True),
        sa.Column("selling_cost_bp", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("family_monthly_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spending_change_monthly_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(f"level IN ({', '.join(repr(v) for v in LEVELS)})", name="ck_care_scenario_level"),
        sa.CheckConstraint("room IS NULL OR room IN ('shared', 'private')", name="ck_care_scenario_room"),
    )
    op.create_table(
        "care_quote",
        sa.Column("key", sa.String(length=32), primary_key=True),
        sa.Column("cents", sa.Integer(), nullable=False),
        sa.Column("quoted_on", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("care_quote")
    op.drop_table("care_scenario")
    op.drop_table("care_setup")
