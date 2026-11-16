"""reimbursable expenses: who pays the household back, trips, "always reimbursable" rules, settled leftovers, and a
payer, a trip and a source on each transaction

Revision ID: 0025
Revises: 0024

Reimbursable spec, The model. reimburser holds the payers ("Acme"), unique in the book. trip holds a trip's name, first
and last days, optional city and payer. reimburse_rule marks a normalized description reimbursable for a payer (and
remembers a repayment's payer). reimburse_settlement is a leftover balance settled as the household's spending in a
category. transaction gains reimburser_id (a reimbursable charge's payer, or a repayment's; a payer in use can't be
deleted), trip_id (cleared if the trip goes) and reimburse_source (none, manual or rule). Nothing is backfilled.
Downgrade drops the columns and the tables.
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reimburser",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=60), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 60", name="ck_reimburser_name"),
    )
    op.create_table(
        "trip",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("end", sa.Date(), nullable=False),
        sa.Column("city", sa.String(length=60), nullable=True),
        sa.Column("reimburser_id", sa.Integer(), sa.ForeignKey("reimburser.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.CheckConstraint('"end" >= start', name="ck_trip_dates"),
    )
    op.create_table(
        "reimburse_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pattern", sa.String(length=200), nullable=False, unique=True),
        sa.Column("reimburser_id", sa.Integer(), sa.ForeignKey("reimburser.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "reimburse_settlement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reimburser_id", sa.Integer(), sa.ForeignKey("reimburser.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("amount_cents > 0", name="ck_reimburse_settlement_amount"),
    )
    with op.batch_alter_table("transaction") as b:
        b.add_column(sa.Column("reimburser_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("trip_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("reimburse_source", sa.String(length=8), nullable=False, server_default="none"))
        b.create_foreign_key("fk_transaction_reimburser_id", "reimburser", ["reimburser_id"], ["id"], ondelete="RESTRICT")
        b.create_foreign_key("fk_transaction_trip_id", "trip", ["trip_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_transaction_reimburser_id", ["reimburser_id"])
        b.create_index("ix_transaction_trip_id", ["trip_id"])


def downgrade() -> None:
    with op.batch_alter_table("transaction") as b:
        b.drop_index("ix_transaction_trip_id")
        b.drop_index("ix_transaction_reimburser_id")
        b.drop_constraint("fk_transaction_trip_id", type_="foreignkey")
        b.drop_constraint("fk_transaction_reimburser_id", type_="foreignkey")
        b.drop_column("reimburse_source")
        b.drop_column("trip_id")
        b.drop_column("reimburser_id")
    op.drop_table("reimburse_settlement")
    op.drop_table("reimburse_rule")
    op.drop_table("trip")
    op.drop_table("reimburser")
