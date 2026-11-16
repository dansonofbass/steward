"""one home value: a book whose Profile has a home value gets that home as a Property account, linked to the value

Revision ID: 0021
Revises: 0020

Roadmap 11 (JR, Oct 26): Profile's "what the home would sell for" is the home's Property account, so net worth, the
Accounts tab and Care count the house. A book with the fact home.value_cents and no link (home.account_id) is linked to
its one active property account, or to one named Home, or gets a manual Property account called Home holding the latest
value on its date (steward.services.home_value does the same on each save from now on). Linking an account the household
already had keeps the newer of its balance and Profile's answer. No schema changes. Downgrade removes the link, and the
account this migration made with its balance (never an account the household had, or one with transactions).
"""
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

LINKED = "Linked by migration 0021"             # an account the household already had
MADE = "Made and linked by migration 0021"      # the Home account this migration made


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    c = op.get_bind()
    value = c.execute(sa.text("SELECT value, as_of FROM fact WHERE key = 'home.value_cents' "
                              "ORDER BY as_of DESC, id DESC LIMIT 1")).first()
    if value is None or not str(value[0]).lstrip("-").isdigit():
        return
    if c.execute(sa.text("SELECT 1 FROM fact WHERE key = 'home.account_id' LIMIT 1")).first() is not None:
        return
    cents, as_of = int(value[0]), value[1]
    props = c.execute(sa.text(
        "SELECT a.id, a.name, a.is_active, (SELECT balance_cents FROM balance_snapshot b WHERE b.account_id = a.id "
        "ORDER BY b.as_of DESC LIMIT 1) FROM account a WHERE a.type = 'property' ORDER BY a.id")).all()
    active = [p for p in props if p[2]]
    named = [p for p in props if p[1].strip().lower() == "home"]
    # One active property, or the one called Home, or with several the largest (what Care takes as the home): never a
    # second account for the same house.
    existing = (active[0][0] if len(active) == 1 else named[0][0] if len(named) == 1
                else max(active, key=lambda p: (p[3] or 0, -p[0]))[0] if active else None)
    if existing is not None:
        aid, note = existing, LINKED
        c.execute(sa.text("UPDATE account SET is_active = 1 WHERE id = :aid"), {"aid": aid})   # Profile says it's owned
        # The newer of the account's balance and Profile's answer: a newer answer becomes the balance on its date.
        latest = c.execute(sa.text("SELECT max(as_of) FROM balance_snapshot WHERE account_id = :aid"), {"aid": aid}).scalar()
        if latest is None or str(latest) < str(as_of):
            c.execute(sa.text("INSERT OR REPLACE INTO balance_snapshot (account_id, as_of, balance_cents) "
                              "VALUES (:aid, :as_of, :cents)"), {"aid": aid, "as_of": as_of, "cents": cents})
    else:
        note = MADE
        inst = c.execute(sa.text("SELECT id FROM institution WHERE source = 'manual'")).scalar()
        if inst is None:
            inst = c.execute(sa.text("INSERT INTO institution (name, source) VALUES ('Manual', 'manual') RETURNING id")).scalar()
        aid = c.execute(sa.text(
            "INSERT INTO account (institution_id, name, type, owner, source, currency, is_active, created_at) "
            "VALUES (:inst, 'Home', 'property', 'joint', 'manual', 'USD', 1, :now) RETURNING id"),
            {"inst": inst, "now": _utcnow()}).scalar()
        c.execute(sa.text("INSERT INTO balance_snapshot (account_id, as_of, balance_cents) VALUES (:aid, :as_of, :cents)"),
                  {"aid": aid, "as_of": as_of, "cents": cents})
    c.execute(sa.text("INSERT INTO fact (key, value, as_of, note, created_at) "
                      "VALUES ('home.account_id', :aid, :today, :note, :now)"),
              {"aid": str(aid), "today": date.today(), "note": note, "now": _utcnow()})


def downgrade() -> None:
    c = op.get_bind()
    link = c.execute(sa.text("SELECT value, note FROM fact WHERE key = 'home.account_id' AND note IN (:linked, :made)"),
                     {"linked": LINKED, "made": MADE}).first()
    if link is None:
        return
    aid = int(link[0])
    c.execute(sa.text("DELETE FROM fact WHERE key = 'home.account_id' AND note IN (:linked, :made)"),
              {"linked": LINKED, "made": MADE})
    has_rows = c.execute(sa.text('SELECT 1 FROM "transaction" WHERE account_id = :aid LIMIT 1'), {"aid": aid}).first()
    # Only the account exactly as the migration left it: one balance. Any balance entered since keeps it.
    balances = c.execute(sa.text("SELECT count(*) FROM balance_snapshot WHERE account_id = :aid"), {"aid": aid}).scalar()
    if link[1] == MADE and has_rows is None and balances <= 1:
        c.execute(sa.text("DELETE FROM balance_snapshot WHERE account_id = :aid"), {"aid": aid})
        c.execute(sa.text("DELETE FROM account WHERE id = :aid"), {"aid": aid})
