"""plan subpages: what each saved plan was worked out from

Revision ID: 0026
Revises: 0025

Plan subpages spec, What changed since the last saved plan. plan gains inputs_summary: JSON text with the spending
basis, the investable balances by how they're taxed, the monthly saving, where each person's Social Security comes
from, the big one-off costs with their years, and the Comfortably age in months. Each save writes it; the Overview
compares it with today's. Saves made before this keep NULL, and the line then names no facts. Downgrade drops it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plan") as b:
        b.add_column(sa.Column("inputs_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plan") as b:
        b.drop_column("inputs_summary")
