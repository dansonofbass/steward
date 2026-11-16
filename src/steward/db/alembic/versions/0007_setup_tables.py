"""setup tables: setup_step, user_setup

Revision ID: 0007
Revises: 0006

Creates two tables. Nothing alters the populated account or user tables (M1-B: a batch alter rebuilds them);
both new tables only reference user.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setup_step",
        sa.Column("step", sa.String(length=10), primary_key=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("step IN ('about', 'banks', 'home', 'pay', 'children', 'health', 'earnings')", name="ck_setup_step_step"),
        sa.CheckConstraint("status IN ('done', 'skipped', 'doesnt_apply')", name="ck_setup_step_status"),
    )
    op.create_table(
        "user_setup",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("home_hidden_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("user_setup")
    op.drop_table("setup_step")
