"""investment activity out of Review: the rows of investment accounts that no person sorted take Investment activity,
or Interest for a dividend, interest or capital gain paid out

Revision ID: 0022
Revises: 0021

Roadmap 12 (JR, Oct 28). In a brokerage, 401(k), IRA, HSA or 529 account a buy, a sale, a reinvested dividend or a fee
is money moving inside the account: not spending, not income, and not a transfer (a transfer into one counts as money
put in, services.contributions). Until now those rows sat in Review as Not sorted yet. From now on sync and import sort
them (services.categorize.investment_suggestion); this sorts the ones already there. A row a person sorted, a transfer,
and a row already Interest or Taxes are left alone. No schema changes. Downgrade puts the rows this migration changed
back to Not sorted yet (it marks them with category_source 'rule'; the ids are not kept, so it
reverts every Investment activity row from a rule in those accounts; the Interest it gave a dividend stays).
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

TYPES = ("brokerage_taxable", "k401", "roth_ira", "traditional_ira", "hsa", "plan529")
KEPT = ("transfer", "interest", "taxes", "investment")
# The same tests as services.categorize.investment_category, on the normalized (upper-cased, spaces collapsed) text.
EARNED = re.compile(r"\bDIV\b|DIVIDEND|\bINTEREST\b|CAP(?:ITAL)? GAIN")
REINVEST = re.compile(r"REINVEST")


def _category(raw: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "").strip().upper())
    return "interest" if EARNED.search(text) and not REINVEST.search(text) else "investment"


def upgrade() -> None:
    c = op.get_bind()
    types = ", ".join(f"'{t}'" for t in TYPES)
    kept = ", ".join(f"'{k}'" for k in KEPT)
    rows = c.execute(sa.text(
        f"SELECT t.id, t.raw_description FROM \"transaction\" t JOIN account a ON a.id = t.account_id "
        f"WHERE a.type IN ({types}) AND t.is_transfer = 0 AND t.category_source != 'correction' "
        f"AND t.category NOT IN ({kept})")).all()
    for tid, raw in rows:
        c.execute(sa.text("UPDATE \"transaction\" SET category = :cat, category_source = 'rule' WHERE id = :id"),
                  {"cat": _category(raw), "id": tid})


def downgrade() -> None:
    c = op.get_bind()
    types = ", ".join(f"'{t}'" for t in TYPES)
    c.execute(sa.text(
        f"UPDATE \"transaction\" SET category = 'uncategorized', category_source = 'none' WHERE category = 'investment' "
        f"AND category_source = 'rule' AND account_id IN (SELECT id FROM account WHERE type IN ({types}))"))
