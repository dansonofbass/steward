"""statement holdings: a positions import's source, batch, period, check, balance, snapshot and Undo

Revision ID: 0037
Revises: 0036

PDF statements spec P39, P40, P49 (PR 3). positions_import gains where its holdings came from (csv, pdf or pdf_scan),
the import set a statement came in with (for the batch's one Undo), the statement's batch that wrote it (so undoing
another file of the same day never takes its holdings), the statement's first day, its $1 check (adds_up |
anyway), the ending balance it printed, the snapshot it wrote, and when it was undone. Existing rows: source 'csv',
NULLs elsewhere. Downgrade drops the columns.
"""
import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("positions_import") as b:
        b.add_column(sa.Column("source", sa.String(8), nullable=False, server_default=sa.text("'csv'")))
        b.add_column(sa.Column("set_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("batch_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("period_start", sa.Date(), nullable=True))
        b.add_column(sa.Column("check_state", sa.String(8), nullable=True))
        b.add_column(sa.Column("balance_cents", sa.Integer(), nullable=True))
        b.add_column(sa.Column("snapshot_as_of", sa.Date(), nullable=True))
        b.add_column(sa.Column("rolled_back_at", sa.DateTime(), nullable=True))
        b.create_foreign_key("fk_positions_import_set_id", "import_set", ["set_id"], ["id"])
        b.create_foreign_key("fk_positions_import_batch_id", "import_batch", ["batch_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("positions_import") as b:
        b.drop_constraint("fk_positions_import_batch_id", type_="foreignkey")
        b.drop_constraint("fk_positions_import_set_id", type_="foreignkey")
        for col in ("rolled_back_at", "snapshot_as_of", "balance_cents", "check_state", "period_start", "batch_id", "set_id",
                    "source"):
            b.drop_column(col)
