"""inventory: inventory_item, file, change_record, suggestion, tax_form

Revision ID: 0009
Revises: 0008

Creates five tables (family books plan 2). Nothing alters a table that holds data. This is the first migration a
parent book receives; a book upgraded by a failed deploy needs the hand restore in docs/guides/backups.md.
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner", sa.String(length=40), nullable=False),
        sa.Column("institution", sa.String(length=120), nullable=True),
        sa.Column("last4", sa.String(length=4), nullable=True),
        sa.Column("full_number", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=14), nullable=False),
        sa.Column("check_reason", sa.Text(), nullable=True),
        sa.Column("data_source", sa.String(length=10), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("login_kept_in", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("closed_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("account_id", name="uq_inventory_item_account"),
        sa.CheckConstraint("kind IN ('account', 'income', 'insurance', 'document', 'contact')", name="ck_inventory_item_kind"),
        sa.CheckConstraint("status IN ('confirmed', 'needs_checking', 'closed')", name="ck_inventory_item_status"),
        sa.CheckConstraint("data_source IS NULL OR data_source IN ('feed', 'statement', 'manual')",
                           name="ck_inventory_item_data_source"),
    )
    op.create_index("ix_inventory_item_kind", "inventory_item", ["kind"])
    op.create_index("ix_inventory_item_status", "inventory_item", ["status"])
    op.create_table(
        "file",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=60), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_file_item_id", "file", ["item_id"])
    op.create_table(
        "change_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("target_type", sa.String(length=12), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("before", sa.Text(), nullable=True),
        sa.Column("after", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_change_record_at", "change_record", ["at"])
    op.create_index("ix_change_record_item_id", "change_record", ["item_id"])
    op.create_table(
        "suggestion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("payer_key", sa.String(length=120), nullable=False),
        sa.Column("payer_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inventory_item.id"), nullable=True),
        sa.Column("undo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("answered_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("kind", "payer_key", name="uq_suggestion_kind_payer"),
        sa.CheckConstraint("status IN ('open', 'added', 'linked', 'dismissed')", name="ck_suggestion_status"),
    )
    op.create_index("ix_suggestion_status", "suggestion", ["status"])
    op.create_table(
        "tax_form",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("form", sa.String(length=10), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("recipient", sa.String(length=40), nullable=False),
        sa.Column("payer", sa.String(length=120), nullable=False),
        sa.Column("payer_key", sa.String(length=120), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=True),
        sa.Column("boxes", sa.Text(), nullable=False),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("file.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint("form IN ('1099-INT', '1099-DIV', '1099-R', 'SSA-1099')", name="ck_tax_form_form"),
    )
    op.create_index("ix_tax_form_payer_key", "tax_form", ["payer_key"])


def downgrade() -> None:
    op.drop_table("tax_form")
    op.drop_table("suggestion")
    op.drop_table("change_record")
    op.drop_table("file")
    op.drop_table("inventory_item")
