"""smarter patterns: every stored rule pattern recomputed with the new normalize(), which drops a bank's reference noise

Revision ID: 0029
Revises: 0028

services.transactions.normalize() now drops an ACH entry's tail ("WEB ID: 1234567890", "PPD ID: ...", and everything
after it), a confirmation or reference ("CONF# ...", "REF #...", "TRACE#..."), and, after the first word, a token that
mixes letters and digits (a Zelle code, "ST-A1B2C3"), a run of 4 or more digits, a "#" store number and a date. So
"BETTERMENT SEC TRANSFER ST-A1B2C3 WEB ID: 1234567890" is "BETTERMENT SEC TRANSFER" every month, where before every
row was its own pattern and no rule ever caught the next one.

Three tables keep a normalize() result: merchant_rule.pattern, reimburse_rule.pattern (both unique) and
business_rule.pattern (merchant and client rules; matched by kind, pattern and account). Rules keep no raw text, so
each pattern is recomputed from the stored one; the function below is a frozen copy of the new normalize() (a
migration must not import app code that can change later), and on a stored pattern it gives what it gives on the raw
text (tests/test_normalize_corpus.py). Where two or more rules now share a pattern the newest (created_at, then id) is
kept and the others are deleted; each merge is logged with the patterns it folded together. Nothing points at a
rule's id. An Undo still pending from before the upgrade that holds an old pattern refuses ("That changed since"), as
it should. Downgrade does nothing: the old patterns are not kept, and the new ones still work with the old code (they
match fewer rows).
"""
import logging
import re

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# ---- a frozen copy of services.transactions.normalize as of this revision -------------------------------------------
_WS = re.compile(r"\s+")
_TRAIL = re.compile(r"(\s+(#?\d[\d/\-]*|\*\w+))+$")
_STAR = re.compile(r"\*\w+$")
_TAIL = re.compile(r"\s(?:(?:WEB|PPD|CCD|TEL|IAT|CTX|ARC|BOC|POP|RCK)\s+ID\b|ID:\s*(?:\d|$)"
                   r"|(?:CONF|CONFIRMATION|REF|REFERENCE|TRACE|TRN|TXN)\s*(?:#|:|NO\b|NUMBER\b)).*$")
_RUN = re.compile(r"\d{4,}")
_DATE = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?")
_STORE = re.compile(r"#\d+")


def _noise(tok: str) -> bool:
    if _RUN.search(tok) or _DATE.fullmatch(tok) or _STORE.fullmatch(tok):
        return True
    alnum = [c for c in tok if c.isalnum()]
    digits = sum(c.isdigit() for c in alnum)
    return 0 < digits < len(alnum) and len(alnum) >= 5 and digits >= 2


def normalize(raw: str) -> str:
    s = _WS.sub(" ", raw.strip().upper())
    s = _TAIL.sub("", s)
    s = _STAR.sub("", s)
    first, *rest = s.split(" ")
    s = " ".join([first, *(t for t in rest if not _noise(t))])
    s = _TRAIL.sub("", s).strip()
    return s[:200]
# ---------------------------------------------------------------------------------------------------------------------


def _merge(c, table: str, extra: tuple[str, ...] = ()) -> None:
    """Recompute every pattern in `table`; rules that now share one (and the same `extra` columns) keep the newest."""
    cols = ", ".join(("id", "pattern", "created_at", *extra))
    groups: dict[tuple, list] = {}
    for r in c.execute(sa.text(f"SELECT {cols} FROM {table} WHERE pattern IS NOT NULL")).all():
        new = normalize(r.pattern) or r.pattern        # never empty a rule's pattern (no stored pattern does this)
        groups.setdefault((new, *(getattr(r, e) for e in extra)), []).append(r)
    for members in groups.values():
        members.sort(key=lambda r: (str(r.created_at or ""), r.id), reverse=True)
    # Deletes first: a survivor's new pattern can be another rule's old one only when that rule is in its group (the
    # new normalize() is its own fixed point), so once the others are gone no update can hit the unique index.
    for (new, *_), members in groups.items():
        keep, gone = members[0], members[1:]
        if gone:
            # By id only: a pattern is a piece of a transaction's description (P10).
            log.info("0029 %s: %d rules now share one pattern; kept #%d, deleted %s", table, len(members),
                     keep.id, ", ".join(f"#{g.id}" for g in gone))
            c.execute(sa.text(f"DELETE FROM {table} WHERE id IN ({', '.join(str(int(g.id)) for g in gone)})"))
    for (new, *_), members in groups.items():
        if members[0].pattern != new:
            c.execute(sa.text(f"UPDATE {table} SET pattern = :p WHERE id = :id"), {"p": new, "id": members[0].id})


def upgrade() -> None:
    c = op.get_bind()
    _merge(c, "merchant_rule")
    _merge(c, "reimburse_rule")
    _merge(c, "business_rule", ("kind", "account_id"))


def downgrade() -> None:
    pass
