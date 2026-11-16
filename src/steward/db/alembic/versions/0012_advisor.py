"""advisor: advisor_alias, advisor_outgoing, chat_conversation, chat_message, advisor_state, chat_seen

Revision ID: 0012
Revises: 0011

Milestone 3 plan A. Six new tables; nothing else changes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TABLES = ("chat_seen", "advisor_state", "chat_message", "chat_conversation", "advisor_outgoing", "advisor_alias")


def upgrade() -> None:
    op.create_table(
        "advisor_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("target", sa.String(length=160), nullable=False),
        sa.Column("alias", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("kind", "target", name="uq_advisor_alias_target"),
        sa.CheckConstraint("kind IN ('owner', 'user', 'child', 'account', 'payee')", name="ck_advisor_alias_kind"),
    )
    op.create_table(
        "advisor_outgoing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("turn_id", sa.String(length=20), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("part", sa.String(length=12), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=40), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("channel IN ('chat', 'mcp', 'prewarm')", name="ck_advisor_outgoing_channel"),
        sa.CheckConstraint("part IN ('question', 'tool_result', 'merchant_rows', 'system', 'history_ref')",
                           name="ck_advisor_outgoing_part"),
    )
    op.create_index("ix_advisor_outgoing_at", "advisor_outgoing", ["at"])
    op.create_index("ix_advisor_outgoing_turn_id", "advisor_outgoing", ["turn_id"])
    op.create_index("ix_advisor_outgoing_sha256", "advisor_outgoing", ["sha256"])
    op.create_table(
        "chat_conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("last_input_tokens", sa.Integer(), nullable=False),
    )
    op.create_index("ix_chat_conversation_user_id", "chat_conversation", ["user_id"])
    op.create_table(
        "chat_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversation.id"), nullable=False),
        sa.Column("turn_id", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mac", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=40), nullable=True),
        sa.Column("usage", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_chat_message_role"),
    )
    op.create_index("ix_chat_message_conversation_id", "chat_message", ["conversation_id"])
    op.create_table(
        "advisor_state",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    op.create_table(
        "chat_seen",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("seen_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
