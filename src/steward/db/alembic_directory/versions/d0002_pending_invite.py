"""pending_invite: an invitation to an existing account waits for that person to accept

Revision ID: d0002
Revises: d0001
"""
import sqlalchemy as sa
from alembic import op

revision = "d0002"
down_revision = "d0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_invite",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("invited_by", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["invited_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint("role IN ('manager', 'viewer')", name="ck_pending_invite_role"),
    )
    op.create_index("ix_pending_invite_book_id", "pending_invite", ["book_id"])
    op.create_index("ix_pending_invite_user_id", "pending_invite", ["user_id"])


def downgrade() -> None:
    op.drop_table("pending_invite")
