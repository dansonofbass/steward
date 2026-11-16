"""rule labels: a merchant rule may carry a name, a note and an exact amount, and a row a name; undo keeps old text
apart

Revision ID: 0032
Revises: 0031

Polish round spec, section 5 and Data and migration (P31, P33-P36). merchant_rule gains amount_cents (the signed row
amount it matches exactly), nickname (40), note, note_by and note_by_name (who saved the note, as they were named
then). Its category may be empty (a rule that names and notes rows but sorts nothing), with a check that a rule does
something. pattern stops being unique: it is unique among rules with no amount, and (pattern, amount) among the rest.
The table is rebuilt by hand (create, copy, drop, rename) so its constraints are replaced exactly; existing rules keep
every value with no amount, and nothing points at a rule's id. transaction gains nickname with ALTER TABLE ADD COLUMN:
no rebuild, so the foreign keys to and from transaction stay as they are. undo_text is new: the old text an undoable
action replaced, keyed by the entry's token, with the text it wrote (Engineering choice 1), so undo_entry never holds a
note or a name.

Downgrade deletes the rules with no category and, of rules sharing a pattern, keeps the newest plain rule (or the newest
when none is plain), as 0029 merged; it drops the new columns, makes pattern unique again and drops undo_text. It is
lossy for names, rule notes and amount rules.
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

SOURCES = ("rule", "correction", "model", "none")
OLD = ("id", "pattern", "merchant", "category", "is_business", "source", "created_at")


def _rule_table(new: bool) -> None:
    cols = [sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("pattern", sa.String(length=200), nullable=False),
            sa.Column("merchant", sa.String(length=200), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=new),
            sa.Column("is_business", sa.Boolean(), nullable=True),
            sa.Column("source", sa.Enum(*SOURCES, name="categorysource"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False)]
    if new:
        cols += [sa.Column("amount_cents", sa.Integer(), nullable=True),
                 sa.Column("nickname", sa.String(length=40), nullable=True),
                 sa.Column("note", sa.Text(), nullable=True),
                 sa.Column("note_by", sa.Integer(), nullable=True),
                 sa.Column("note_by_name", sa.String(length=120), nullable=True)]
        op.create_table("merchant_rule_new", *cols, sa.CheckConstraint(
            "category IS NOT NULL OR nickname IS NOT NULL OR note IS NOT NULL", name="ck_merchant_rule_does_something"))
    else:
        op.create_table("merchant_rule_new", *cols, sa.UniqueConstraint("pattern"))


def _copy_and_swap(columns: tuple[str, ...]) -> None:
    names = ", ".join(columns)
    op.get_bind().execute(sa.text(f"INSERT INTO merchant_rule_new ({names}) SELECT {names} FROM merchant_rule"))
    op.drop_table("merchant_rule")
    op.rename_table("merchant_rule_new", "merchant_rule")


def upgrade() -> None:
    _rule_table(new=True)
    _copy_and_swap(OLD)
    op.create_index("uq_merchant_rule_pattern", "merchant_rule", ["pattern"], unique=True,
                    sqlite_where=sa.text("amount_cents IS NULL"))
    op.create_index("uq_merchant_rule_pattern_amount", "merchant_rule", ["pattern", "amount_cents"], unique=True,
                    sqlite_where=sa.text("amount_cents IS NOT NULL"))
    op.add_column("transaction", sa.Column("nickname", sa.String(length=40), nullable=True))
    op.create_table("undo_text",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("token", sa.String(length=64), nullable=False),
                    sa.Column("model", sa.String(length=20), nullable=False),
                    sa.Column("row_key", sa.String(length=40), nullable=False),
                    sa.Column("field", sa.String(length=20), nullable=False),
                    sa.Column("value", sa.Text(), nullable=True),
                    sa.Column("written", sa.Text(), nullable=True))
    op.create_index("ix_undo_text_token", "undo_text", ["token"])


def downgrade() -> None:
    c = op.get_bind()
    op.drop_index("ix_undo_text_token", table_name="undo_text")
    op.drop_table("undo_text")
    c.execute(sa.text('ALTER TABLE "transaction" DROP COLUMN nickname'))   # SQLite 3.35+: no rebuild
    c.execute(sa.text("DELETE FROM merchant_rule WHERE category IS NULL"))
    rows = c.execute(sa.text("SELECT id, pattern FROM merchant_rule "
                             "ORDER BY pattern, amount_cents IS NULL DESC, created_at DESC, id DESC")).all()
    keep: dict[str, int] = {}
    for rid, pattern in rows:
        keep.setdefault(pattern, rid)
    gone = [rid for rid, _ in rows if rid not in keep.values()]
    if gone:
        c.execute(sa.text(f"DELETE FROM merchant_rule WHERE id IN ({', '.join(str(i) for i in gone)})"))
    op.drop_index("uq_merchant_rule_pattern_amount", table_name="merchant_rule")
    op.drop_index("uq_merchant_rule_pattern", table_name="merchant_rule")
    _rule_table(new=False)
    _copy_and_swap(OLD)
