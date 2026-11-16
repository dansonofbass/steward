"""same account, two feeds: the SimpleFIN feeds of each account, the bank's own org id, feeds held for a question,
the answers, the copies a merge dropped, and the feed each transaction came through

Revision ID: 0027
Revises: 0026

Same-account spec, Data. account_feed holds every SimpleFIN account id that feeds an account ("sfin:<id>", unique),
the connection's institution, the bank's own name for it (refreshed at each sync, so a person's rename doesn't hide a
duplicate) and when it was added and last seen. Each account whose external_id starts "sfin:" gets one, named as the
account is and last seen at its institution's last sync. institution gains org_id, SimpleFIN's id for the bank
(simplefin_org_id holds the connection's). held_feed keeps a SimpleFIN account that looks like one already in the book,
with its latest balance and up to 400 transactions as JSON, until a person answers; the payload stays in the book.
same_account_answer holds the one-time check's open questions and every "they're different". feed_txn_alias maps a
dropped copy's id, per account and feed, to the transaction it copies. transaction gains feed_id, the feed a row came
through: rows sync brought (a bank id and no import) take their account's feed. Downgrade drops it all.
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("institution") as b:
        b.add_column(sa.Column("org_id", sa.String(length=120), nullable=True))
    op.create_table(
        "account_feed",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False, unique=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institution.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_account_feed_account_id", "account_feed", ["account_id"])
    op.create_table(
        "held_feed",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=200), nullable=False, unique=True),
        sa.Column("institution_id", sa.Integer(), sa.ForeignKey("institution.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("candidate_account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("balance_cents", sa.Integer(), nullable=False),
        sa.Column("balance_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "same_account_answer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("other_account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=True),
        sa.Column("held_external_id", sa.String(length=200), nullable=True),
        sa.Column("answer", sa.String(length=10), nullable=False),
        sa.Column("match_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("answered_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("answer IN ('open', 'different')", name="ck_same_account_answer"),
        sa.CheckConstraint("other_account_id IS NOT NULL OR held_external_id IS NOT NULL",
                           name="ck_same_account_other"),
        sa.UniqueConstraint("account_id", "other_account_id", name="uq_same_account_pair"),
    )
    op.create_table(
        "feed_txn_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feed_id", sa.Integer(), sa.ForeignKey("account_feed.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transaction.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "external_id", name="uq_feed_txn_alias"),
    )
    op.create_index("ix_feed_txn_alias_transaction_id", "feed_txn_alias", ["transaction_id"])
    with op.batch_alter_table("transaction") as b:
        b.add_column(sa.Column("feed_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_transaction_feed_id", "account_feed", ["feed_id"], ["id"], ondelete="SET NULL")
    op.execute(
        "INSERT INTO account_feed (account_id, external_id, institution_id, name, added_at, last_seen_at) "
        "SELECT a.id, a.external_id, a.institution_id, a.name, a.created_at, COALESCE(i.last_sync_at, a.created_at) "
        "FROM account a JOIN institution i ON i.id = a.institution_id "
        "WHERE a.external_id LIKE 'sfin:%' ORDER BY a.id")
    op.execute(
        'UPDATE "transaction" SET feed_id = '
        '(SELECT f.id FROM account_feed f WHERE f.account_id = "transaction".account_id) '
        "WHERE external_id IS NOT NULL AND import_batch_id IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("transaction") as b:
        b.drop_constraint("fk_transaction_feed_id", type_="foreignkey")
        b.drop_column("feed_id")
    op.drop_index("ix_feed_txn_alias_transaction_id", table_name="feed_txn_alias")
    op.drop_table("feed_txn_alias")
    op.drop_table("same_account_answer")
    op.drop_table("held_feed")
    op.drop_index("ix_account_feed_account_id", table_name="account_feed")
    op.drop_table("account_feed")
    with op.batch_alter_table("institution") as b:
        b.drop_column("org_id")
