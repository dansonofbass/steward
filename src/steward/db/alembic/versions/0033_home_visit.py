"""home visit: when each person last looked at Home, for "Since you last looked"

Revision ID: 0033
Revises: 0032

Home spec, Data (P27, P28, P36). home_visit holds one row per person in this book: seen_at, the newest full look's
mark (10 seconds on screen), and glanced_at, the newest glance's (Home reached ready). Both are the server's own
times, sent back by the web. user_id is a directory user id with no foreign key across files (spec 2.2), as
user_setup's. Upgrade creates it empty, so everyone's first visit after the deploy shows no Since section. Downgrade
drops it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("home_visit",
                    sa.Column("user_id", sa.Integer(), primary_key=True),
                    sa.Column("seen_at", sa.DateTime(), nullable=True),
                    sa.Column("glanced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_table("home_visit")
