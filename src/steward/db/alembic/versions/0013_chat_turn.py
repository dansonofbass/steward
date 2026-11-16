"""chat_turn, and an index on advisor_outgoing.conversation_id

Revision ID: 0013
Revises: 0012

Milestone 3 plan B (ruling 1). One new table and one index; nothing else changes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_turn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversation.id"), nullable=False),
        sa.Column("turn_id", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("asked", sa.Text(), nullable=False),
        sa.Column("sent", sa.Text(), nullable=True),
        sa.Column("chips", sa.Text(), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("stop", sa.String(length=20), nullable=True),
        sa.Column("line", sa.Text(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("ms", sa.Integer(), nullable=False),
        sa.Column("approval", sa.String(length=10), nullable=True),
        sa.Column("store_rows", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("turn_id", name="uq_chat_turn_turn_id"),
        sa.CheckConstraint("approval IN ('approved', 'declined', 'viewer', 'timeout')", name="ck_chat_turn_approval"),
    )
    op.create_index("ix_chat_turn_conversation_id", "chat_turn", ["conversation_id"])
    op.create_index("ix_advisor_outgoing_conversation_id", "advisor_outgoing", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_advisor_outgoing_conversation_id", table_name="advisor_outgoing")
    op.drop_index("ix_chat_turn_conversation_id", table_name="chat_turn")
    op.drop_table("chat_turn")
