"""account.rate_bp: a card's or loan's yearly interest rate

Revision ID: 0016
Revises: 0015

Next dollar plan Task 4 (cash-flow and tax spec section 6, step 4: debt above 7% interest). One nullable column in
basis points; nothing else changes. The API keeps it to cards and loans, from 0 to 10,000.
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account") as b:
        b.add_column(sa.Column("rate_bp", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("account") as b:
        b.drop_column("rate_bp")
