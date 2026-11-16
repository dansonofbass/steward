"""statements: staged PDF statements, remembered statement layouts, and a statement's period, check and page

Revision ID: 0036
Revises: 0035

PDF statements spec, Data (P3, P23, P24, P35, P38, P40, P42, P49; plan Engineering choices 7 and 8). statement_stage
holds one row per staged PDF in the book's encrypted file for at most 7 days: its state, its extracted lines (account
numbers masked), the rows read, the statement's facts and the check; never the PDF. statement_layout keeps a layout a
person confirmed: digit-free anchors and the validated labels, never data; forgotten_at is Forget's soft delete.
import_batch gains the statement's period, pages, check, layout and the snapshot it wrote (snapshot_cents: the value,
so Undo can tell it changed); transaction gains statement_page. Existing rows get NULLs. Downgrade drops it all.
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_layout",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("anchors", sa.Text(), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_by", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("forgotten_at", sa.DateTime(), nullable=True))
    op.create_table(
        "statement_stage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("added_by", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("warned_at", sa.DateTime(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("pages_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(8), nullable=True),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("error", sa.String(24), nullable=True),
        sa.Column("tries", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("layout_id", sa.Integer(), sa.ForeignKey("statement_layout.id", ondelete="SET NULL"), nullable=True),
        sa.Column("proposal", sa.Text(), nullable=True),
        sa.Column("lines", sa.Text(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=True),
        sa.Column("rows", sa.Text(), nullable=True),
        sa.Column("holdings", sa.Text(), nullable=True),
        sa.Column("gap_cents", sa.Integer(), nullable=True),
        sa.Column("anyway", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("suggested_by", sa.String(8), nullable=True),
        sa.Column("part", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_index("ix_statement_stage_state", "statement_stage", ["state"])
    op.create_index("ix_statement_stage_expires_at", "statement_stage", ["expires_at"])
    with op.batch_alter_table("import_batch") as b:
        b.add_column(sa.Column("period_start", sa.Date(), nullable=True))
        b.add_column(sa.Column("period_end", sa.Date(), nullable=True))
        b.add_column(sa.Column("pages", sa.Integer(), nullable=True))
        b.add_column(sa.Column("check_state", sa.String(8), nullable=True))
        b.add_column(sa.Column("check_gap_cents", sa.Integer(), nullable=True))
        b.add_column(sa.Column("statement_layout_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("snapshot_as_of", sa.Date(), nullable=True))
        b.add_column(sa.Column("snapshot_cents", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_import_batch_statement_layout_id", "statement_layout", ["statement_layout_id"], ["id"],
                             ondelete="SET NULL")
    with op.batch_alter_table("transaction") as b:
        b.add_column(sa.Column("statement_page", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transaction") as b:
        b.drop_column("statement_page")
    with op.batch_alter_table("import_batch") as b:
        b.drop_constraint("fk_import_batch_statement_layout_id", type_="foreignkey")
        for col in ("snapshot_cents", "snapshot_as_of", "statement_layout_id", "check_gap_cents", "check_state", "pages",
                    "period_end", "period_start"):
            b.drop_column(col)
    op.drop_index("ix_statement_stage_expires_at", table_name="statement_stage")
    op.drop_index("ix_statement_stage_state", table_name="statement_stage")
    op.drop_table("statement_stage")
    op.drop_table("statement_layout")
