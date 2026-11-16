"""kinds and checks: a commitment kind for spending targets, and when a kept target may be checked again

Revision ID: 0031
Revises: 0030

Polish round spec, Data and migration (P1, P3, P19). spending_target's kind may also be commitment (giving,
childcare and kids: never praised or warned about), and the table gains check_after, the first day the monthly target
check may ask about that category again after Keep. A giving or childcare_education row stored as fixed becomes a
commitment (its amount still means "expected"); a kids row keeps its kind, since someone may have set an everyday
target. The table is rebuilt by hand (create, copy, drop, rename) so the CHECK is replaced exactly; nothing points at
it. Downgrade turns commitment back into fixed and drops check_after; it is lossless for amounts.
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

KINDS_NEW = ("everyday", "fixed", "commitment", "occasional")
KINDS_OLD = ("everyday", "fixed", "occasional")
COMMITTED = ("giving", "childcare_education")
COPY = ("INSERT INTO spending_target_new (category, kind, monthly_cents, updated_at, updated_by) "
        "SELECT category, {kind}, monthly_cents, updated_at, updated_by FROM spending_target")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _table(kinds: tuple[str, ...], new: bool) -> None:
    cols = [sa.Column("category", sa.String(length=40), primary_key=True),
            sa.Column("kind", sa.String(length=12), nullable=False),
            sa.Column("monthly_cents", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("updated_by", sa.Integer(), nullable=True)]
    if new:
        cols.append(sa.Column("check_after", sa.Date(), nullable=True))
    op.create_table("spending_target_new", *cols,
                    sa.CheckConstraint(f"kind IN ({_in(kinds)})", name="ck_spending_target_kind"),
                    sa.CheckConstraint("monthly_cents IS NULL OR monthly_cents >= 0", name="ck_spending_target_cents"))


def _swap() -> None:
    op.drop_table("spending_target")
    op.rename_table("spending_target_new", "spending_target")


def upgrade() -> None:
    _table(KINDS_NEW, new=True)
    kind = f"CASE WHEN kind = 'fixed' AND category IN ({_in(COMMITTED)}) THEN 'commitment' ELSE kind END"
    op.get_bind().execute(sa.text(COPY.format(kind=kind)))
    _swap()


def downgrade() -> None:
    _table(KINDS_OLD, new=False)
    op.get_bind().execute(sa.text(COPY.format(kind="CASE WHEN kind = 'commitment' THEN 'fixed' ELSE kind END")))
    _swap()
