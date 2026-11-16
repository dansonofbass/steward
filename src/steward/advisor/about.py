"""What a question is about (Ask about this, P5, P6, P8, P25, P29): the browser sends ids and the NAS builds the wire
object from typed columns only. parse_about checks the request's shape; resolve reads the listed columns of one row,
gives an account its alias and checks the result against protocol.ABOUT before anything uses it. No free-text column
of these tables is ever selected (the advisor word tests), and nothing here logs a row's values."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.advisor.aliases import Aliases
from steward.advisor.tools.parent import flag_day
from steward.books.registry import BookInfo
from steward.db.models import Account, CareScenario, Flag, Transaction
from steward_boundary import vocab as V
from steward_boundary.aliases import protected_spans
from steward_boundary.protocol import ABOUT, check_frame

GONE = "That isn't in this book any more."
NOT_UNDERSTOOD = "That request wasn't understood."      # steward.api.body's words
MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
FIELDS = {"account": ("id",), "transaction": ("id",), "flag": ("id",), "category": ("category", "month"),
          "plan": (), "care": ()}
KINDS = {"household": frozenset({"account", "category", "plan", "transaction"}),
         "parent": frozenset({"flag", "care", "transaction"})}
MAX_ID = 2**31 - 1


class AboutRefused(Exception):
    """A request Steward doesn't take (422): a shape that isn't one of the spec's, a kind this book doesn't have, a
    month outside the book."""

    def __init__(self, message: str = NOT_UNDERSTOOD):
        super().__init__(message)
        self.message = message


class AboutGone(Exception):
    """The row it names isn't in the book any more (404, P28): merged away or removed."""

    def __init__(self, message: str = GONE):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class AboutIn:
    kind: str
    id: int | None = None
    category: str | None = None
    month: str | None = None


def _whole(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_ID


def parse_about(raw: object) -> AboutIn | None:
    """None when there is no about. Exactly the keys of one request shape (spec, API): a key more, a label, a free
    string or an id that isn't a whole number is refused, so a client can't slip words in."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str) or raw["kind"] not in FIELDS:
        raise AboutRefused()
    kind = raw["kind"]
    need = FIELDS[kind]
    allowed = {"kind", *need, *(("id",) if kind == "care" else ())}
    if set(raw) - allowed or any(k not in raw for k in need):
        raise AboutRefused()
    if "id" in raw and not _whole(raw["id"]):
        raise AboutRefused()
    if kind == "category" and (not isinstance(raw["category"], str) or raw["category"] not in V.CATEGORIES
                               or not isinstance(raw["month"], str) or MONTH.fullmatch(raw["month"]) is None):
        raise AboutRefused()
    return AboutIn(kind, raw.get("id"), raw.get("category"), raw.get("month"))


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def resolve(db: Session, book: BookInfo, aliases: Aliases, about: AboutIn, today: date) -> dict:
    """The wire object for `about` in this book (no commit). Only these columns are read: an account's id; a
    transaction's day, amount, category and account; a flag's check, its transaction's day, its due day and when it
    was made (P16); a care scenario's id and level, in their order (its number is its place, as care_projection
    counts). AboutRefused for a kind this book doesn't have (P29) or a month outside the book's; AboutGone for a row
    that isn't there (P28)."""
    if about.kind not in KINDS[book.kind]:
        raise AboutRefused()
    if about.kind == "account":
        if db.scalar(select(Account.id).where(Account.id == about.id)) is None:
            raise AboutGone()
        wire = {"kind": "account", "account": aliases.account(about.id)}
    elif about.kind == "transaction":
        row = db.execute(select(Transaction.posted_at, Transaction.amount_cents, Transaction.category,
                                Transaction.account_id).where(Transaction.id == about.id)).one_or_none()
        if row is None:
            raise AboutGone()
        posted, cents, category, account_id = row
        wire = {"kind": "transaction", "date": posted.isoformat(), "amount_cents": cents, "category": category,
                "account": aliases.account(account_id)}
    elif about.kind == "flag":
        row = db.execute(select(Flag.check, Flag.transaction_id, Flag.due_on, Flag.created_at)
                         .where(Flag.id == about.id)).one_or_none()
        if row is None:
            raise AboutGone()
        check, txn_id, due_on, made = row
        posted = db.scalar(select(Transaction.posted_at).where(Transaction.id == txn_id)) if txn_id else None
        wire = {"kind": "flag", "check": check, "date": flag_day(posted, due_on, made).isoformat()}
    elif about.kind == "care":
        if about.id is None:
            wire = {"kind": "care"}
        else:
            order = db.execute(select(CareScenario.id, CareScenario.level)
                               .order_by(CareScenario.position, CareScenario.id)).all()
            n = next((i for i, (sid, _) in enumerate(order, 1) if sid == about.id), None)
            if n is None:
                raise AboutGone()
            wire = {"kind": "care", "scenario": n, "level": order[n - 1][1]}
    elif about.kind == "category":
        # Clamped to this month, as Spending's first month is, so a book whose rows all lie ahead still has one.
        earliest = db.scalar(select(func.min(Transaction.posted_at)))
        first = min(_ym(earliest), _ym(today)) if earliest else _ym(today)
        if not first <= about.month <= _ym(today):
            raise AboutRefused()
        wire = {"kind": "category", "category": about.category, "month": about.month}
    else:
        wire = {"kind": "plan"}
    if check_frame(ABOUT, wire):
        raise ValueError("the about object didn't match protocol.ABOUT")
    return wire


def chips_for(sent: str, wire: dict) -> list[dict]:
    """The about alias inside the about line, as a chip (layer "alias") for What Claude will see."""
    alias = wire.get("account")
    if not alias:
        return []
    return [{"start": s, "end": e, "label": alias, "layer": "alias"}
            for s, e in protected_spans(sent, frozenset({alias}))]
