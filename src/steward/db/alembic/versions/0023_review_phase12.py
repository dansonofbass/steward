"""review and categorizing (phase 12): the model's guess and when it was asked, transaction notes, card interest as
fees, and the catch-up's cursor retired

Revision ID: 0023
Revises: 0022

Phase 12 spec, Data. transaction gains guess_category (the model's best guess when it wasn't sure enough to sort the
row), guess_pct (its confidence, 0-100) and model_asked_at (when the model last answered about the row). A new table,
transaction_note, holds a person's notes on a transaction (decision 18); a note goes with its transaction. Backfill:
rows the model already sorted were asked when they were imported; interest a card charged (money out that the
built-in Interest rule sorted) is a Fee (decision 10); the catch-up's watch_state cursor is replaced by
model_asked_at (ruling 14). Downgrade drops the columns and the table and puts the fee rows back to Interest.
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transaction") as b:
        b.add_column(sa.Column("guess_category", sa.String(length=40), nullable=True))
        b.add_column(sa.Column("guess_pct", sa.Integer(), nullable=True))
        b.add_column(sa.Column("model_asked_at", sa.DateTime(), nullable=True))
    op.create_table(
        "transaction_note",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transaction.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("author_name", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_transaction_note_transaction_id", "transaction_note", ["transaction_id"])
    c = op.get_bind()
    c.execute(sa.text("UPDATE \"transaction\" SET model_asked_at = imported_at WHERE category_source = 'model'"))
    c.execute(sa.text("UPDATE \"transaction\" SET category = 'fees' "
                      "WHERE category = 'interest' AND category_source = 'rule' AND amount_cents < 0"))
    c.execute(sa.text("DELETE FROM watch_state WHERE key = 'catchup_cursor'"))


def downgrade() -> None:
    c = op.get_bind()
    c.execute(sa.text("UPDATE \"transaction\" SET category = 'interest' WHERE category = 'fees' "
                      "AND category_source = 'rule' AND amount_cents < 0 AND upper(raw_description) LIKE '%INTEREST%'"))
    op.drop_index("ix_transaction_note_transaction_id", table_name="transaction_note")
    op.drop_table("transaction_note")
    with op.batch_alter_table("transaction") as b:
        b.drop_column("model_asked_at")
        b.drop_column("guess_pct")
        b.drop_column("guess_category")
