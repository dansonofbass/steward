"""tax_state: what the household enters for Taxes, and the quarterly email's switches and sent marks

Revision ID: 0017
Revises: 0016

Tax decisions plan Task 4 (spec 7; ruling 21). One key-value table, like business_state; nothing else changes. Parent
books get it too and never write to it (every /taxes route is household only).
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tax_state",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tax_state")
