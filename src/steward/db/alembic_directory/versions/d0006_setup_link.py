"""setup_link: the one-time link `steward setup` prints for the first person (release spec 2026-11-05, section 6).
Only the SHA-256 of the link's token is kept. Additive: one new table, nothing else changes.

Revision ID: d0006
Revises: d0005
"""
import sqlalchemy as sa
from alembic import op

revision = "d0006"
down_revision = "d0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setup_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:
    op.drop_table("setup_link")
