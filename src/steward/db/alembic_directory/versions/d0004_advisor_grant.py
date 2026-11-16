"""advisor_grant: Claude Code grants, one person and one book each (milestone 3 plan C)

Revision ID: d0004
Revises: d0003
"""
import sqlalchemy as sa
from alembic import op

revision = "d0004"
down_revision = "d0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "advisor_grant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("issued_by", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["issued_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["revoked_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_advisor_grant_book_id", "advisor_grant", ["book_id"])


def downgrade() -> None:
    op.drop_table("advisor_grant")
