"""chat turn about: what each question was asked about (Ask about this)

Revision ID: 0034
Revises: 0033

Ask about this spec, Data (P9). chat_turn gains about, the wire object the context line was made from (aliases,
enums, ISO days and months and whole numbers only), written once when the question starts, so the panel, the Ask tab
and History show "About: ..." over that question and the sent log labels its context part. Existing turns get NULL.
ADD COLUMN, so no rebuild. Downgrade drops it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_turn", sa.Column("about", sa.Text(), nullable=True))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE chat_turn DROP COLUMN about"))   # SQLite 3.35+: no rebuild
