import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import CategorySource, MerchantRule, Transaction
from steward.services.transfers import PAIRABLE_CHOICES, pair_transfers, unpair_peers

_WS = re.compile(r"\s+")
_CODE = re.compile(r"#?\d[\d/\-]*|\*\w+")      # a trailing word that is a number, a date, a "#" number or a *code
_STAR = re.compile(r"\*\w+$")
# An ACH entry's tail ("WEB ID: 1234567890", "PPD ID: ...", a bare "ID:" and a number) or a bank's reference ("CONF#",
# "REF #", "TRACE#:", "TRN:"), and everything after it. Never the first word: the match starts at a space.
_TAIL = re.compile(r"\s(?:(?:WEB|PPD|CCD|TEL|IAT|CTX|ARC|BOC|POP|RCK)\s+ID\b|ID:\s*(?:\d|$)"
                   r"|(?:CONF|CONFIRMATION|REF|REFERENCE|TRACE|TRN|TXN)\s*(?:#|:|NO\b|NUMBER\b)).*$")
_RUN = re.compile(r"\d{4,}")
_DATE = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?")
_STORE = re.compile(r"#\d+")


def _drop_trailing_codes(s: str) -> str:
    """`s` (its spaces already collapsed to one) without its trailing number and *code words; the first word stays.
    Word by word, not one `(\\s+(...))+$` pattern, which took time that grew with the square of a long description
    (SEC-3's class: a 5 MB OFX name froze the server)."""
    words = s.split(" ")
    while len(words) > 1 and _CODE.fullmatch(words[-1]):
        words.pop()
    return " ".join(words)


def _noise(tok: str) -> bool:
    """A reference, not a word: a run of 4+ digits ("57444", "XX1234", "...1234"), a date, a "#" store number, or a
    code that mixes letters and digits ("ST-A1B2C3", "JPM99B8XYZ"; 5+ letters and digits, 2+ of them digits, so
    "401K" and "1ST" stay)."""
    if _RUN.search(tok) or _DATE.fullmatch(tok) or _STORE.fullmatch(tok):
        return True
    alnum = [c for c in tok if c.isalnum()]
    digits = sum(c.isdigit() for c in alnum)
    return 0 < digits < len(alnum) and len(alnum) >= 5 and digits >= 2


def tidy(raw: str) -> str:
    """The old cleaning: upper case, spaces collapsed, trailing numbers and *codes gone. Kept where a stored key or a
    comparison was built on it: payee keys (watch.payees), the suggester's payer keys, the built-in rules' keyword
    search and the duplicate checks, where a reference code tells two real payments apart."""
    s = _WS.sub(" ", raw.strip().upper())
    s = _STAR.sub("", s)
    s = _drop_trailing_codes(s).strip()
    return s[:200]


def normalize(raw: str) -> str:
    """The pattern a household rule matches on, and what "Also apply to N matching transactions" groups by: tidy(), and
    a bank's reference noise dropped too (an ACH tail, a confirmation code, a store number, a date), so the same
    payee's rows share one pattern month after month. The first word always stays and a plain word is never dropped,
    so two payees stay two patterns. "" when nothing is left. db/alembic/versions/0029 holds a frozen copy; a change
    here that moves patterns needs a migration like it (tests/test_normalize_corpus.py)."""
    s = _WS.sub(" ", raw.strip().upper())
    s = _TAIL.sub("", s)
    s = _STAR.sub("", s)
    first, *rest = s.split(" ")
    s = " ".join([first, *(t for t in rest if not _noise(t))])
    s = _drop_trailing_codes(s).strip()
    return s[:200]


def exact_rule(db: Session, pattern: str, amount_cents: int | None) -> MerchantRule | None:
    """The one rule for this pattern and exact amount (P33, P35); the plain rule when amount_cents is None."""
    q = select(MerchantRule).where(MerchantRule.pattern == pattern)
    return db.scalar(q.where(MerchantRule.amount_cents.is_(None)) if amount_cents is None
                     else q.where(MerchantRule.amount_cents == amount_cents))


def rules_for(db: Session, pattern: str, amount_cents: int | None) -> tuple[MerchantRule | None, MerchantRule | None]:
    """The rule for this exact amount (None without an amount) and the plain rule for the pattern."""
    return (exact_rule(db, pattern, amount_cents) if amount_cents is not None else None), exact_rule(db, pattern, None)


def sorting_rule(db: Session, pattern: str, amount_cents: int | None) -> MerchantRule | None:
    """The rule that sorts a row (Engineering choice 5): the amount rule when it has a category, else the plain rule
    when it has one. A rule with no category names and notes rows but sorts nothing (P34)."""
    return next((r for r in rules_for(db, pattern, amount_cents) if r is not None and r.category is not None), None)


def apply_correction(db: Session, txn: Transaction, merchant: str | None, category: str | None,
                     is_business: bool | None, now: datetime, *, make_rule: bool = True) -> MerchantRule | None:
    """A person's correction: the category (and merchant), the source `correction` and reviewed_at, a transfer paired
    or unpaired. With make_rule (a single row's sort) the row's pattern also gets a merchant rule; bulk sort passes
    False (profile spec P29: the rows share no text), and no rule is made or changed."""
    if merchant is not None:
        txn.merchant = merchant
    if category is not None:
        txn.category = category
        txn.guess_category = txn.guess_pct = None  # sorting clears the guess (phase 12)
    if is_business is not None:
        txn.is_business = is_business
    if category == "transfer":
        txn.is_transfer = True
    elif category is not None and txn.is_transfer:
        txn.is_transfer = False
    if category is not None and category not in PAIRABLE_CHOICES and txn.transfer_peer_id is not None:
        unpair_peers(db, [txn.id])          # the other side was a transfer only as this one's pair: back to Review
        txn.transfer_peer_id = None
    if txn.category == "uncategorized":
        db.flush()
        return None  # nothing was decided: not reviewed, and no rule that would hide future rows
    txn.category_source = CategorySource.correction
    txn.reviewed_at = now
    if not make_rule:
        db.flush()
        if txn.is_transfer and txn.transfer_peer_id is None:
            pair_transfers(db, [txn.id])
        return None
    pattern = normalize(txn.raw_description)
    if not pattern:
        return None  # an unnormalizable description never becomes a merchant rule
    amount_rule, plain = rules_for(db, pattern, txn.amount_cents)
    rule = amount_rule or plain              # P35: the amount rule when one matches this row; a sort never touches a label
    if rule is None:
        rule = MerchantRule(pattern=pattern, merchant=txn.merchant or pattern.title(),
                            category=txn.category, is_business=is_business, source=CategorySource.correction)
        db.add(rule)
    else:
        rule.merchant = txn.merchant or rule.merchant
        rule.category = txn.category
        if is_business is not None:
            rule.is_business = is_business
    db.flush()
    if txn.is_transfer and txn.transfer_peer_id is None:
        pair_transfers(db, [txn.id])        # ruling 11: the other side becomes a transfer too
    return rule
