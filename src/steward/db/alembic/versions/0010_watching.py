"""watching: flag, flag_event, watch_known, watch_state, watch_recipient, mail_outbox, transaction.watched_at

Revision ID: 0010
Revises: 0009

Family books plan 3. Adds six tables and one nullable column. Transactions posted more than 14 days before the upgrade
are marked checked, so the first run looks at the last two weeks only (plan ruling 2).
"""
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

CHECKS = ("scam", "payee", "large", "unusual", "cash", "monthly", "duplicate", "deposit", "premium", "account", "low")
STATUSES = ("open", "checking", "expected", "handled", "arrived")
EVENTS = ("flagged", "emailed", "summary", "email_failed", "paid", "arrived")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    with op.batch_alter_table("transaction") as b:
        b.add_column(sa.Column("watched_at", sa.DateTime(), nullable=True))
    now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    cut = (date.today() - timedelta(days=14)).isoformat()
    op.execute(sa.text('UPDATE "transaction" SET watched_at = :now WHERE posted_at < :cut').bindparams(now=now, cut=cut))
    op.create_table(
        "flag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("check_name", sa.String(length=10), nullable=False),
        sa.Column("severity", sa.String(length=6), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("facts", sa.Text(), nullable=False),
        sa.Column("also", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status_by", sa.Integer(), nullable=True),
        sa.Column("status_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("summarized_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("transaction_id", name="uq_flag_transaction"),
        sa.UniqueConstraint("check_name", "item_id", "due_on", name="uq_flag_due"),
        sa.CheckConstraint(_in("check_name", CHECKS), name="ck_flag_check"),
        sa.CheckConstraint("severity IN ('urgent', 'normal')", name="ck_flag_severity"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_flag_status"),
    )
    op.create_index("ix_flag_check_name", "flag", ["check_name"])
    op.create_index("ix_flag_status", "flag", ["status"])
    op.create_index("ix_flag_created_at", "flag", ["created_at"])
    op.create_table(
        "flag_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flag_id", sa.Integer(), sa.ForeignKey("flag.id"), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("user_ids", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.CheckConstraint(_in("kind", EVENTS), name="ck_flag_event_kind"),
    )
    op.create_index("ix_flag_event_flag_id", "flag_event", ["flag_id"])
    op.create_table(
        "watch_known",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payee_key", sa.String(length=120), nullable=False),
        sa.Column("payee_name", sa.String(length=160), nullable=False),
        sa.Column("low_cents", sa.Integer(), nullable=True),
        sa.Column("high_cents", sa.Integer(), nullable=True),
        sa.Column("check_name", sa.String(length=10), nullable=False),
        sa.Column("flag_id", sa.Integer(), sa.ForeignKey("flag.id"), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("removed_by", sa.Integer(), nullable=True),
    )
    op.create_index("ix_watch_known_payee_key", "watch_known", ["payee_key"])
    op.create_table(
        "watch_state",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "watch_recipient",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("urgent", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    op.create_table(
        "mail_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("flag_id", sa.Integer(), sa.ForeignKey("flag.id"), nullable=True),
        sa.Column("flag_ids", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("next_try_at", sa.DateTime(), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False),
        sa.Column("to_user_ids", sa.Text(), nullable=True),
        sa.Column("sent_to", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("kind IN ('urgent', 'summary')", name="ck_mail_outbox_kind"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed', 'skipped')", name="ck_mail_outbox_status"),
    )
    op.create_index("ix_mail_outbox_status", "mail_outbox", ["status"])
    op.create_index("ix_mail_outbox_next_try_at", "mail_outbox", ["next_try_at"])


def downgrade() -> None:
    for table in ("mail_outbox", "watch_recipient", "watch_state", "watch_known", "flag_event", "flag"):
        op.drop_table(table)
    with op.batch_alter_table("transaction") as b:
        b.drop_column("watched_at")
