"""import layouts: remembered CSV layouts, OFX account hints, and import batches grouped into sets

Revision ID: 0035
Revises: 0034

Import/export spec, Data (P14, P20, P32, P38; plan Engineering choice 1). import_layout keeps a person's confirmed
layout by the key of its normalized header: column names only, never a data cell. forgotten_at is Forget's soft
delete, so Undo can put the row back. import_hint keeps which account an OFX statement went to, by
"ofx:<ORG or BANKID>:<last 4>": never the full number. import_set groups one batch's files for one Undo. Existing
import_batch rows get NULLs (legacy, shown as batches of one). Downgrade drops the columns and the tables.
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_layout",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("header", sa.Text(), nullable=False),
        sa.Column("mapping", sa.Text(), nullable=False),
        sa.Column("negate", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("date_format", sa.String(24), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("forgotten_at", sa.DateTime(), nullable=True))
    op.create_table(
        "import_hint",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table(
        "import_set",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("imported_by", sa.Integer(), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("import_batch") as b:
        b.add_column(sa.Column("set_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("layout_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("content_sha256", sa.String(64), nullable=True))
        b.create_foreign_key("fk_import_batch_set_id", "import_set", ["set_id"], ["id"])
        b.create_foreign_key("fk_import_batch_layout_id", "import_layout", ["layout_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("import_batch") as b:
        b.drop_constraint("fk_import_batch_layout_id", type_="foreignkey")
        b.drop_constraint("fk_import_batch_set_id", type_="foreignkey")
        b.drop_column("content_sha256")
        b.drop_column("layout_id")
        b.drop_column("set_id")
    op.drop_table("import_set")
    op.drop_table("import_hint")
    op.drop_table("import_layout")
