"""investment views: the account's advisory fee, a vehicle's loan and what the bank sends; the holding's import; fund
expense ratio overrides, remembered position columns and positions imports

Revision ID: 0028
Revises: 0027

Investment views spec. account gains advisory_fee_bp (a robo-adviser's or adviser's yearly fee, set by hand), loan_id
(a vehicle's loan, for display; cleared if the loan goes), and sends_holdings, sends_transactions, holdings_seen_at
and transactions_seen_at (what SimpleFIN delivered for it at the last sync, and when each was last seen). holding gains
import_id (the positions import that wrote it, or NULL for the feed). expense_ratio_override holds the household's
ratio for a fund symbol, as a percent in text ("0.04"). positions_mapping remembers a positions CSV's columns per
institution (or per account entered by hand). positions_import records each import: the account, the day, the file's
name (never its contents), how many positions and who. AccountType.vehicle needs no change: account.type is plain
text. Nothing is backfilled. Downgrade drops the columns and the tables.
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "positions_import",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("imported_by", sa.Integer(), nullable=False),
    )
    op.create_index("ix_positions_import_account_id", "positions_import", ["account_id"])
    op.create_table(
        "positions_mapping",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("mapping", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "expense_ratio_override",
        sa.Column("symbol", sa.String(length=20), primary_key=True),
        sa.Column("ratio_pct", sa.String(length=8), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
    )
    with op.batch_alter_table("account") as b:
        b.add_column(sa.Column("advisory_fee_bp", sa.Integer(), nullable=True))
        b.add_column(sa.Column("loan_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("sends_holdings", sa.Boolean(), nullable=True))
        b.add_column(sa.Column("sends_transactions", sa.Boolean(), nullable=True))
        b.add_column(sa.Column("holdings_seen_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("transactions_seen_at", sa.DateTime(), nullable=True))
        b.create_foreign_key("fk_account_loan_id", "account", ["loan_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("holding") as b:
        b.add_column(sa.Column("import_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_holding_import_id", "positions_import", ["import_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("holding") as b:
        b.drop_constraint("fk_holding_import_id", type_="foreignkey")
        b.drop_column("import_id")
    with op.batch_alter_table("account") as b:
        b.drop_constraint("fk_account_loan_id", type_="foreignkey")
        b.drop_column("transactions_seen_at")
        b.drop_column("holdings_seen_at")
        b.drop_column("sends_transactions")
        b.drop_column("sends_holdings")
        b.drop_column("loan_id")
        b.drop_column("advisory_fee_bp")
    op.drop_table("expense_ratio_override")
    op.drop_table("positions_mapping")
    op.drop_index("ix_positions_import_account_id", table_name="positions_import")
    op.drop_table("positions_import")
