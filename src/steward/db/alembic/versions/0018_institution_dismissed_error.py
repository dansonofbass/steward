"""institution.dismissed_error: a sync warning a person dismissed, so it isn't raised again

Revision ID: 0018
Revises: 0017

Click-through feedback 2026-10-25, section 0. One nullable column. The sync clears it when the connection's error
changes or the connection recovers.

Also a one-time clean-up: the old sync made an Institution named "A bank connection (MBR-...)" for every failing
connection SimpleFIN didn't name, and opened a Home warning with that text that nothing could clear. Those rows (only
ones with no accounts) are removed and their warnings resolved; the new sync logs such connections instead. The
downgrade can't bring them back, and doesn't need to.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("institution") as b:
        b.add_column(sa.Column("dismissed_error", sa.Text(), nullable=True))
    op.execute("UPDATE event_log SET resolved_at = CURRENT_TIMESTAMP WHERE kind = 'sync' AND resolved_at IS NULL "
               "AND message LIKE 'A bank connection (%'")
    op.execute("DELETE FROM institution WHERE source = 'simplefin' AND name LIKE 'A bank connection (%' "
               "AND id NOT IN (SELECT institution_id FROM account WHERE institution_id IS NOT NULL)")


def downgrade() -> None:
    with op.batch_alter_table("institution") as b:
        b.drop_column("dismissed_error")
