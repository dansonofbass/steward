"""mail_outbox.locked_since: when the current streak of database locks on a row began

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mail_outbox", sa.Column("locked_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("mail_outbox", "locked_since")
