"""directory: people, sign-in, books and memberships

Revision ID: d0001
Revises:

The four sign-in tables are created exactly as book revision 0001 created them in steward.db, so the move
(steward.books.bootstrap) copies them column for column.
"""
import sqlalchemy as sa
from alembic import op

revision = "d0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=40), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "passkey",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_id"),
    )
    op.create_index("ix_passkey_user_id", "passkey", ["user_id"])
    op.create_table(
        "password_reset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_password_reset_user_id", "password_reset", ["user_id"])
    op.create_table(
        "session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("device_label", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_session_user_id", "session", ["user_id"])
    op.create_table(
        "book",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("owner_names", sa.Text(), nullable=False),
        sa.Column("file", sa.String(length=200), nullable=False),
        sa.Column("key_scheme", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.CheckConstraint("kind IN ('household', 'parent')", name="ck_book_kind"),
        sa.CheckConstraint("key_scheme IN ('raw', 'derived')", name="ck_book_key_scheme"),
    )
    op.create_table(
        "membership",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("user_id", "book_id"),
        sa.CheckConstraint("role IN ('manager', 'viewer')", name="ck_membership_role"),
    )
    op.create_index("ix_membership_book_id", "membership", ["book_id"])
    op.create_table(
        "membership_change",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("role_before", sa.String(length=8), nullable=True),
        sa.Column("role_after", sa.String(length=8), nullable=True),
        sa.Column("by_user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["by_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("action IN ('added', 'invited', 'role_changed', 'removed')", name="ck_membership_change_action"),
    )
    op.create_index("ix_membership_change_at", "membership_change", ["at"])
    op.create_table(
        "directory_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_directory_event_at", "directory_event", ["at"])
    op.create_table(
        "directory_meta",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    for name in ("directory_meta", "directory_event", "membership_change", "membership", "book", "session",
                 "password_reset", "passkey", "user"):
        op.drop_table(name)
