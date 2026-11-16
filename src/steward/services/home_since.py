"""Since you last looked (Home spec, section 3): each person's visits to Home, and what came in since the last one.
A visit is the person's own: only their row is read or written. Nothing here reads a note, a rule's note or the undo
journal, and nothing is logged."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import clock
from steward.db.models import Account, HomeVisit, Reimburser, Transaction
from steward.services import networth
from steward.services import spending as sp
from steward.services.vault_flows import BUSINESS_TYPES, CASH_FLOW_TYPES, REPAYMENT, personal_amount
from steward.watch.payees import display

LOOK_BACK_DAYS = 35            # P33: a last look over 35 days ago covers the last 35 days
MARK_DAYS = 1                  # POST /home/seen: a mark from within the last day
TOO_OLD = "That visit is too old."


class LookRefused(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Look:
    at: datetime               # rows Steward received after this are new
    over_month: bool           # the last look was over 35 days ago, so `at` is 35 days back


def household_day(at: datetime) -> date:
    return at.astimezone(clock.household_tz()).date()


def last_look(db: Session, user_id: int, now: datetime, asked: datetime | None = None) -> Look | None:
    """P27-P29, P33. None on a first visit: no row, or only a glance from today. `asked` is a refetch's ?from= (the
    first answer's from, so saving the visit never empties the list on screen), used when it is within the last 35
    days and not in the future. Otherwise the later of the full look and a glance from an earlier household day: a
    quick refresh today never moves `from`, but yesterday's glance does."""
    v = db.get(HomeVisit, user_id)
    if v is None:
        return None
    floor = now - timedelta(days=LOOK_BACK_DAYS)
    if asked is not None and floor <= asked <= now:
        return Look(asked, False)
    marks = [v.seen_at] if v.seen_at is not None else []
    if v.glanced_at is not None and household_day(v.glanced_at) < household_day(now):
        marks.append(v.glanced_at)
    if not marks:
        return None
    at = max(marks)
    return Look(floor, True) if at < floor else Look(at, False)


def save_look(db: Session, user_id: int, mark: datetime, *, glance: bool, now: datetime) -> None:
    """P28: keep the later of the stored mark and this one, for a full look or a glance (no commit). A mark older than
    a day or in the future is refused."""
    if not now - timedelta(days=MARK_DAYS) <= mark <= now:
        raise LookRefused(TOO_OLD)
    v = db.get(HomeVisit, user_id)
    if v is None:
        v = HomeVisit(user_id=user_id)
        db.add(v)
    if glance:
        v.glanced_at = mark if v.glanced_at is None or mark > v.glanced_at else v.glanced_at
    else:
        v.seen_at = mark if v.seen_at is None or mark > v.seen_at else v.seen_at
    db.flush()


POSTED_DAYS = 10               # P30: posted at most 10 days before the last look
MAX_LINES = 6                  # P31
LARGE_MIN_CENTS = 25_000       # a large charge: at least $250
LARGE_BP = 300                 # and at least 3% of the typical month's money out
GROUP_MIN_CENTS = 15_000       # a category's group: at least $150
GROUP_MIN_ROWS = 2             # over 2 or more charges
MIN_CENTS = 100                # nothing under $1
NET_WORTH_MIN_CENTS = 10_000   # P32: net worth since shows from a $100 change
PAY_CATEGORIES = ("income", "business_income", REPAYMENT)


@dataclass(frozen=True)
class Row:
    category: str
    cents: int                 # the personal share, signed: money in above 0
    name: str


def name_of(nickname: str | None, merchant: str | None, raw: str) -> str:
    """P43: the name someone gave the row, else the merchant, else the bank's text set for display. Never a note."""
    return nickname or merchant or display(raw)


def new_rows(db: Session, look: Look) -> list[Row]:
    """P30: the rows Spending counts (matched set-aside payments included) that Steward received after the last look
    and that were posted at most 10 days before it, so a history import, a merge or a released held feed never floods
    the list; and repayments, which reimbursable rule 1 keeps out of Spending's rows (engineering choice 18). Neither
    SELECT reads a note or a rule."""
    posted_from = household_day(look.at) - timedelta(days=POSTED_DAYS)
    pa = personal_amount()
    q = (select(Transaction.category, pa, Transaction.nickname, Transaction.merchant, Transaction.raw_description)
         .join(Account, Account.id == Transaction.account_id)
         .where(Transaction.posted_at >= posted_from, Transaction.imported_at > look.at,
                *sp.spending_clauses(with_matched=True))
         .order_by(Transaction.posted_at, Transaction.id))
    out = [Row(c, int(cents), name_of(nick, merchant, raw)) for c, cents, nick, merchant, raw in db.execute(q)]
    repaid = (select(Transaction.amount_cents, Reimburser.name, Transaction.merchant, Transaction.raw_description)
              .join(Account, Account.id == Transaction.account_id)
              .outerjoin(Reimburser, Reimburser.id == Transaction.reimburser_id)
              .where(Transaction.posted_at >= posted_from, Transaction.imported_at > look.at,
                     Transaction.category == REPAYMENT, Transaction.amount_cents > 0,
                     Transaction.is_transfer.is_(False), Account.type.in_(CASH_FLOW_TYPES + BUSINESS_TYPES))
              .order_by(Transaction.posted_at, Transaction.id))
    out += [Row(REPAYMENT, int(cents), payer or merchant or display(raw)) for cents, payer, merchant, raw in db.execute(repaid)]
    return out


def since_lines(rows: list[Row], kinds: dict[str, str], typical_out: int | None) -> tuple[list[dict], int]:
    """P31: pay (summed by category and payee), Bills (a line each), large charges (any other single money-out row of
    at least $250 and 3% of the typical month's money out), then the rest of Flexible and Not sorted yet by category
    when a category's total is at least $150 over 2 or more charges. Largest first within each group. At most 6 lines,
    and how many more. Money out of a category Spending doesn't count, and anything under $1, is left out."""
    threshold = max(LARGE_MIN_CENTS, (typical_out or 0) * LARGE_BP // 10_000)
    pay: dict[tuple[str, str], list[int]] = {}
    bills: list[dict] = []
    large: list[dict] = []
    rest: dict[str, list[Row]] = {}
    for r in rows:
        if abs(r.cents) < MIN_CENTS:
            continue
        if r.cents > 0:
            if r.category in PAY_CATEGORIES:
                got = pay.setdefault((r.category, r.name), [0, 0])
                got[0] += r.cents
                got[1] += 1
            continue                                  # a refund or interest is not news
        kind = "everyday" if r.category == sp.UNSORTED else kinds.get(r.category)
        if kind is None:
            continue
        line = {"category": r.category, "name": r.name, "n": 1, "places": 1, "cents": r.cents}
        if kind == "fixed":
            bills.append({"kind": "bill", **line})
        elif -r.cents >= threshold:
            large.append({"kind": "large", **line})
        elif kind == "everyday":
            rest.setdefault(r.category, []).append(r)
    groups = []
    for category, items in rest.items():
        total = sum(-i.cents for i in items)
        if len(items) >= GROUP_MIN_ROWS and total >= GROUP_MIN_CENTS:
            names = sorted({i.name for i in items})
            groups.append({"kind": "group", "category": category, "name": names[0] if len(names) == 1 else None,
                           "n": len(items), "places": len(names), "cents": -total})
    pays = [{"kind": "pay", "category": c, "name": name, "n": n, "places": 1, "cents": cents}
            for (c, name), (cents, n) in pay.items()]

    def by_size(xs: list[dict]) -> list[dict]:
        return sorted(xs, key=lambda x: (-abs(x["cents"]), x["name"] or "", x["category"]))

    every = by_size(pays) + by_size(bills) + by_size(large) + by_size(groups)
    return every[:MAX_LINES], max(0, len(every) - MAX_LINES)


def net_worth_since(db: Session, look: Look, today: date, now_cents: int) -> int | None:
    """P32: today's net worth less the last look's day's, when that day is earlier than today and the change is at
    least $100 either way. From daily balances; nothing extra is stored."""
    day = household_day(look.at)
    if day >= today:
        return None
    change = now_cents - networth.net_worth_on(db, day)
    return change if abs(change) >= NET_WORTH_MIN_CENTS else None


def since_view(db: Session, look: Look | None, today: date, kinds: dict[str, str], typical_out: int | None,
               now_cents: int) -> dict | None:
    """GET /api/home's since: None on a first visit (P33). `kinds` is every spending category's kind, `typical_out`
    the typical month's money out, `now_cents` today's net worth."""
    if look is None:
        return None
    lines, more = since_lines(new_rows(db, look), kinds, typical_out)
    return {"from": look.at.isoformat(), "from_day": household_day(look.at).isoformat(), "over_month": look.over_month,
            "lines": lines, "more": more, "net_worth_cents": net_worth_since(db, look, today, now_cents)}
