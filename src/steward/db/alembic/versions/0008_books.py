"""books: the sign-in tables move to the directory

Revision ID: 0008
Revises: 0007

Drops user, passkey, password_reset and session (the directory copied them first: steward.books.bootstrap), and
the foreign keys that pointed at user from import_batch.imported_by, plan.saved_by, setup_step.user_id and
user_setup.user_id. The id columns stay: a book keeps the ids, the directory knows who they are (spec 2.2).

SQLite can't drop a foreign key in place, so those four tables are rebuilt in batch mode (copy, drop, rename),
which keeps every row and id. Their foreign keys are unnamed, so a naming convention gives the reflected ones
names to drop by. env.py turns foreign-key enforcement off for the run; the end checks nothing points nowhere.
account and transaction are never rebuilt.

A downgrade gives back empty sign-in tables; restore the pre-books backup to get the rows back.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
POINTERS = (("import_batch", "imported_by"), ("plan", "saved_by"), ("setup_step", "user_id"),
            ("user_setup", "user_id"))


def upgrade() -> None:
    for table, column in POINTERS:
        with op.batch_alter_table(table, naming_convention=NAMING) as b:
            b.drop_constraint(f"fk_{table}_{column}_user", type_="foreignkey")
    for table in ("passkey", "password_reset", "session", "user"):
        op.drop_table(table)
    problems = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"Rows point at rows that don't exist: {problems[:5]}")


def downgrade() -> None:
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
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("email"), sa.UniqueConstraint("username"),
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
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]), sa.PrimaryKeyConstraint("id"),
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
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]), sa.PrimaryKeyConstraint("id"),
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
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_session_user_id", "session", ["user_id"])
    for table, column in POINTERS:
        with op.batch_alter_table(table) as b:
            b.create_foreign_key(f"fk_{table}_{column}_user", "user", [column], ["id"])
