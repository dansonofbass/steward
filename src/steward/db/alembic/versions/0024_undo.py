"""undo for Review actions (sorting redesign): the undo_entry table

Revision ID: 0024
Revises: 0023

Sorting redesign spec, Undo. A sort (with the matching rows it applied to), a Snooze or an Ignore writes one row here
inside its own transaction: a random URL-safe token, the person who acted, what they did, when it was made, when it
expires (15 minutes) and when it was used, and the before and after values of every transaction and merchant rule it
changed, as JSON. POST /undo/{token} puts the before values back. Expired rows are deleted by the next action that
writes one. Downgrade drops the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "undo_entry",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("before", sa.Text(), nullable=False),
        sa.Column("after", sa.Text(), nullable=False),
    )
    op.create_index("ix_undo_entry_expires_at", "undo_entry", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_undo_entry_expires_at", table_name="undo_entry")
    op.drop_table("undo_entry")
