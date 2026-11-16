"""business: the tag on each transaction, business_rule and business_state

Revision ID: 0014
Revises: 0013

Business plan Task 1 (spec 5; rulings 1, 2 and 12). Five columns on transaction, two new tables, and every row that
was already business becomes 100% business chosen by hand, and every other row on a business account (business-type, or
owned by Business) becomes business by account (final review ruling I1). Nothing else changes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transaction") as b:
        b.add_column(sa.Column("business_pct", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("business_source", sa.String(length=8), nullable=False, server_default="none"))
        b.add_column(sa.Column("business_line", sa.String(length=20), nullable=True))
        b.add_column(sa.Column("business_hint", sa.Integer(), nullable=True))
        b.add_column(sa.Column("business_answered_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE \"transaction\" SET business_pct = 100, business_source = 'manual' WHERE is_business = 1")
    # Final review ruling I1: rows on a business-type account, or one owned by Business, are business by account.
    # Spec 5: household books only. A parent book never has a business account, whatever an owner is called.
    household = op.get_context().config.attributes.get("household", True)
    if household:
        op.execute("UPDATE \"transaction\" SET business_pct = 100, is_business = 1, business_source = 'account' "
                   "WHERE business_source = 'none' AND is_transfer = 0 AND account_id IN (SELECT id FROM account "
                   "WHERE type IN ('business_checking', 'business_credit') OR owner = 'business')")
    op.create_table(
        "business_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("pattern", sa.String(length=200), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("pct", sa.Integer(), nullable=False),
        sa.Column("line", sa.String(length=20), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("kind IN ('merchant', 'account', 'client')", name="ck_business_rule_kind"),
        sa.CheckConstraint("pct BETWEEN 1 AND 100", name="ck_business_rule_pct"),
    )
    op.create_index("ix_business_rule_account_id", "business_rule", ["account_id"])
    op.create_table(
        "business_state",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    # The inverse of the account backfill: only rows a person marked stay business.
    op.execute("UPDATE \"transaction\" SET is_business = 0 WHERE business_source = 'account'")
    op.drop_table("business_state")
    op.drop_index("ix_business_rule_account_id", table_name="business_rule")
    op.drop_table("business_rule")
    with op.batch_alter_table("transaction") as b:
        b.drop_column("business_answered_at")
        b.drop_column("business_hint")
        b.drop_column("business_line")
        b.drop_column("business_source")
        b.drop_column("business_pct")
