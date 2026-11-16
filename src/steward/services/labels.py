"""Notes that spread and names (polish round, item 5): who counts as a generic payee, how far "Also…" reaches, the
form's save, and names and notes at ingest. Notes and names stay in the encrypted book: nothing here is sent to Claude
or the categorizer (tests/advisor/test_tools_never_read_notes.py)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from steward.db.models import NICKNAME_MAX, NOTE_MAX, Account, CategorySource, MerchantRule, Transaction, TransactionNote
from steward.services.categorize import INVESTMENT_TYPES, builtin_rule
from steward.services.transactions import exact_rule, normalize
from steward.services.undo import Capture

# P32: a payee whose built-in rule on the raw text names one of these is generic: "Also…" narrows to the same amount.
# Read from the raw text, never the row's merchant, which a person may have changed.
GENERIC: tuple[str, ...] = ("PayPal", "Venmo", "Zelle", "Cash App", "Amazon")


def generic_payee(raw: str) -> str | None:
    s = builtin_rule(raw)
    return s.merchant if s is not None and s.merchant in GENERIC else None


def apply_labels(db: Session, rows: list[Transaction], now: datetime) -> int:
    """At ingest (P37): the rule for a row's exact amount, else its plain rule, names the row when it has a name and
    adds its note, written by whoever saved it under the name they had then, dated when the row arrived. Returns the
    rows labelled. The caller passes household rows on non-investment accounts only (Engineering choice 8)."""
    found = db.scalars(select(MerchantRule).where(or_(MerchantRule.nickname.is_not(None), MerchantRule.note.is_not(None)))).all()
    if not rows or not found:
        return 0
    by = {(r.pattern, r.amount_cents): r for r in found}
    n = 0
    for t in rows:
        p = normalize(t.raw_description)
        r = (by.get((p, t.amount_cents)) or by.get((p, None))) if p else None
        if r is None:
            continue
        if r.nickname:
            t.nickname = r.nickname
        if r.note:
            db.add(TransactionNote(transaction_id=t.id, author_id=r.note_by or 0, author_name=r.note_by_name or "Someone",
                                   body=r.note, created_at=now))
        n += 1
    db.flush()
    return n


REACH_MAX = 500                                    # P41
NOT_UNDERSTOOD = "That request wasn't understood."
NOTHING = "Add a note or a name."
NAME_RULE = "A name is 1 to 40 characters."
NOTE_RULE = "A note is 1 to 1,000 characters."
TOO_MANY = "That's more than 500 rows. Narrow it with the amount."
UNSORTED = "uncategorized"


class LabelError(ValueError):
    """A refusal in plain words: PUT …/label answers 422 with it."""


@dataclass(frozen=True)
class Reach:
    """How far "Also…" reaches from one row: the other rows with its pattern (and its exact amount for a generic payee),
    in non-investment accounts, sorted or not, oldest first."""
    pattern: str
    amount_cents: int | None
    payee: str
    generic: bool
    ids: tuple[int, ...]


def reach(db: Session, t: Transaction) -> Reach | None:
    """One SELECT narrowed by the pattern's first word, as matching_counts is; the exact test is normalize(). None
    when the description normalizes to nothing: no rule can be made and nothing is like it."""
    pattern = normalize(t.raw_description)
    if not pattern:
        return None
    generic = generic_payee(t.raw_description)
    amount = t.amount_cents if generic else None
    q = (select(Transaction.id, Transaction.raw_description).join(Account, Account.id == Transaction.account_id)
         .where(Transaction.id != t.id, Account.type.not_in(INVESTMENT_TYPES),
                Transaction.raw_description.icontains(pattern.split(" ")[0], autoescape=True)))
    if amount is not None:
        q = q.where(Transaction.amount_cents == amount)
    ids = tuple(i for i, raw in db.execute(q.order_by(Transaction.id)) if normalize(raw) == pattern)
    return Reach(pattern, amount, generic or t.merchant or pattern.title(), generic is not None, ids)


def label_view(db: Session, t: Transaction) -> dict:
    """GET …/label: the row's name, how far Also reaches, and the rule "And future ones" would keep the label on."""
    r = reach(db, t)
    rule = exact_rule(db, r.pattern, r.amount_cents) if r is not None else None
    return {"nickname": t.nickname,
            "reach": None if r is None else {"others": len(r.ids), "payee": r.payee, "amount_cents": r.amount_cents,
                                             "generic": r.generic},
            "rule": None if rule is None else {"id": rule.id, "nickname": rule.nickname, "note": rule.note,
                                               "has_category": rule.category is not None}}


def _text(value, most: int, rule: str) -> str | None:
    """A field's text, trimmed; None for no field or only spaces (Engineering choice 14)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise LabelError(rule)
    value = value.strip()
    if not value:
        return None
    if len(value) > most:
        raise LabelError(rule)
    return value


def parse_label(body) -> tuple[str | None, str | None, bool, bool]:
    """PUT …/label's body: {note, nickname, also, future}. Either text may be empty, not both."""
    if not isinstance(body, dict):
        raise LabelError(NOT_UNDERSTOOD)
    also, future = body.get("also", False), body.get("future", False)
    if not isinstance(also, bool) or not isinstance(future, bool):
        raise LabelError(NOT_UNDERSTOOD)
    note = _text(body.get("note"), NOTE_MAX, NOTE_RULE)
    nickname = _text(body.get("nickname"), NICKNAME_MAX, NAME_RULE)
    if note is None and nickname is None:
        raise LabelError(NOTHING)
    return note, nickname, also, future


LABEL_FIELDS = ("nickname", "note", "note_by", "note_by_name")


def save_label(db: Session, t: Transaction, cap: Capture, *, note: str | None, nickname: str | None, also: bool,
               future: bool, user_id: int, author: str, now: datetime) -> dict:
    """The form's Save, inside the caller's capturing (one action, one Undo; P36). The note goes on each reached row as
    its own TransactionNote; the name on each row's nickname. "And future ones" finds or makes the rule for the pattern
    (and the amount, for a generic payee) and keeps the name and note on it; a new rule takes the row's category, or
    none when the row is unsorted. Unticked, it takes them off a rule that had them, and a rule left doing nothing is
    removed. Raises LabelError before writing anything."""
    r = reach(db, t)
    others = list(r.ids) if also and r is not None else []
    if len(others) > REACH_MAX:
        raise LabelError(TOO_MANY)
    rows = [t, *db.scalars(select(Transaction).where(Transaction.id.in_(others)).order_by(Transaction.id))]
    added = named = 0
    for row in rows:
        if note is not None:
            db.add(TransactionNote(transaction_id=row.id, author_id=user_id, author_name=author, body=note, created_at=now))
            added += 1
        if nickname is not None and row.nickname != nickname:
            cap.keep_text("txn", row, "nickname", row.nickname, nickname)
            row.nickname = nickname
            named += 1
    rule_id = None
    rule = exact_rule(db, r.pattern, r.amount_cents) if r is not None else None
    if future and r is not None:
        made = rule is None
        if made:
            rule = MerchantRule(pattern=r.pattern, merchant=t.merchant or r.pattern.title(),
                                category=None if t.category == UNSORTED else t.category, is_business=None,
                                source=CategorySource.correction, amount_cents=r.amount_cents)
        wanted: dict[str, object] = {}
        if nickname is not None:
            wanted["nickname"] = nickname
        if note is not None:
            wanted.update(note=note, note_by=user_id, note_by_name=author)
        for f, v in wanted.items():
            if not made and getattr(rule, f) != v:
                cap.keep_text("rule", rule, f, getattr(rule, f), v)
            setattr(rule, f, v)
        if made:
            db.add(rule)
        db.flush()
        rule_id = rule.id
    elif rule is not None and (rule.nickname is not None or rule.note is not None):
        for f in LABEL_FIELDS:
            if getattr(rule, f) is not None:
                cap.keep_text("rule", rule, f, getattr(rule, f), None)
        rule_id = rule.id
        if rule.category is None:
            db.delete(rule)                     # a names-only rule left doing nothing goes (Engineering choice 6)
        else:
            for f in LABEL_FIELDS:
                setattr(rule, f, None)
    db.flush()
    return {"rows": len(rows), "notes_added": added, "named": named, "rule_id": rule_id}
