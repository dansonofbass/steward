"""membership.welcome_seen_at and book.sample_of (guided setup spec 7.1, 8.2). Every existing membership is marked
welcomed, so nobody already in a book sees a welcome. Additive: plain ADD COLUMNs, as d0005.

Revision ID: d0008
Revises: d0007
"""
import sqlalchemy as sa
from alembic import op

revision = "d0008"
down_revision = "d0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("membership", sa.Column("welcome_seen_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE membership SET welcome_seen_at = created_at")
    op.add_column("book", sa.Column("sample_of", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("book", "sample_of")
    op.drop_column("membership", "welcome_seen_at")
