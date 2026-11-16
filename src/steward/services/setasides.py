"""Set-asides (phase 11c spec): costs that come once or twice a year, or once, spread over the months until they
are due. One definition for the monthly amount, the due dates, "should be by now", how one account is shared out
and the five states; matching, suggestions, estimates and the views and writes follow below. Integer cents; today
is the household's day (deps.today())."""
from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import (CATEGORIES, SET_ASIDE_KINDS, Account, AccountType, SetAside, SetAsideDismissed, SetAsideMatch,
                               Transaction)
from steward import clock
from steward.services.accounts import latest_balance
from steward.engine.inputs import OneOffCost
from steward.events import log_event
from steward.services.categorize import INCOME_TAX
from steward.services.transactions import tidy
from steward.services.vault_flows import (month_add, months_between, personal_amount,
                                         personal_clauses)
from steward.watch.payees import display, payee

KINDS: tuple[str, ...] = SET_ASIDE_KINDS
MATCHED_HOWS: tuple[str, ...] = ("auto", "hand")
STATES: tuple[str, ...] = ("short", "behind", "not_paid", "on_track", "no_account")
NEEDS_LOOK: tuple[str, ...] = ("short", "behind", "not_paid")
BEHIND_MIN_CENTS = 2500          # decision 14: behind is short of should-be by more than $25
BEHIND_MIN_BP = 500              # and more than 5%
SHORT_DAYS = 30                  # short (red): due within 30 days with less than the installment put away
LATE_DAYS = 42                   # decision 3: matched up to 6 weeks after its due date
BEFORE_DAYS = 45                 # and from 45 days before it
AMOUNT_TOLERANCE_BP = 2500       # within 25% of the installment
HISTORY_MONTHS = 25              # decision 18: suggestions and matching look back 25 months
STALE_DAYS = 7                   # a snapshot older than this says "balance from Oct 12"
CASH_TYPES = (AccountType.checking, AccountType.savings)


def first_month_after(today: date) -> date:
    """Decision 12: the first month is the month after the set-aside is added."""
    return month_add(today.replace(day=1), 1)


def safe_date(year: int, month: int, day: int) -> date:
    """The day clamped to the month (engineering choice 2): Feb 29 is Feb 28 in a common year."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def div_round(n: int, d: int) -> int:
    """n ÷ d to the nearest cent, half up."""
    return (n + d // 2) // d


def months_through(first: date, due_year: int, due_month: int) -> int:
    """The months from `first` through the due month, both included; never fewer than 1."""
    return max(1, months_between(first, date(due_year, due_month, 1)) + 1)


def monthly_cents(sa) -> int:
    """Decision 12: yearly ÷ 12; twice a year 2 × installment ÷ 12; one-off cost ÷ the months through its due month."""
    if sa.kind == "yearly":
        return div_round(sa.amount_cents, 12)
    if sa.kind == "twice_yearly":
        return div_round(2 * sa.amount_cents, 12)
    return div_round(sa.amount_cents, months_through(sa.first_month, sa.due_year, sa.due_month))


def installment_cents(sa) -> int:
    """What one due date asks for: the yearly amount, one of the two installments, or the cost."""
    return sa.amount_cents


def yearly_cents(sa) -> int:
    """A year's worth; a one-off is no yearly cost."""
    return {"yearly": sa.amount_cents, "twice_yearly": 2 * sa.amount_cents}.get(sa.kind, 0)


def due_dates(sa, start: date, end: date) -> list[date]:
    """Every installment date in [start, end]: the month and day in each year (twice a year: both), or a one-off's
    first of its due month."""
    if sa.kind == "one_off":
        d = date(sa.due_year, sa.due_month, 1)
        return [d] if start <= d <= end else []
    pairs = [(sa.due_month, sa.due_day)]
    if sa.kind == "twice_yearly":
        pairs.append((sa.second_month, sa.second_day))
    out = [safe_date(y, m, d) for y in range(start.year, end.year + 1) for m, d in pairs]
    return sorted(x for x in out if start <= x <= end)


def local_day(at: datetime) -> date:
    """A stored timestamp's day in the household's time zone (an evening in Los Angeles is the next day in UTC)."""
    return at.astimezone(clock.household_tz()).date()


def added_on(sa) -> date:
    """The household's day the set-aside was added: an installment before it is never next and never missed (a new
    set-aside must not open red for a bill it was added after). Matching may still attach an earlier payment to it."""
    return local_day(sa.created_at)


def concern_from(sa) -> date:
    """The first day an installment is this set-aside's concern: the day it was added. A one-off is due on the 1st
    of its month, so one added later in that month counts from the 1st, or it would be neither next nor missed."""
    day = added_on(sa)
    return day.replace(day=1) if sa.kind == "one_off" else day


def next_from(sa, today: date) -> date:
    """The earliest installment that can be next: not more than 6 weeks past, and not before the set-aside was added."""
    return max(today - timedelta(days=LATE_DAYS), concern_from(sa))


def next_due(sa, today: date, settled: set[date]) -> date | None:
    """The next due date (spec, The next due date; engineering choice 3): the earliest installment not paid or
    skipped and not more than 6 weeks past. An installment paid early moves it on to the following one."""
    # A one-off has no horizon: its next due date is its due date, however far away. Yearly and twice-yearly look
    # a little over two years ahead, which always reaches the next installment.
    end = date.max if sa.kind == "one_off" else today + timedelta(days=800)
    for d in due_dates(sa, next_from(sa, today), end):
        if d not in settled:
            return d
    return None


def missed_dues(sa, today: date, settled: set[date]) -> list[date]:
    """Installments more than 6 weeks past with no payment and not skipped, from the first month on (an installment
    before the set-aside started, or was added, was never its concern)."""
    # A one-off's own due month is its concern even when its first month (the month after it was added) is later.
    start = concern_from(sa) if sa.kind == "one_off" else max(sa.first_month, concern_from(sa))
    return [d for d in due_dates(sa, start, today - timedelta(days=LATE_DAYS + 1)) if d not in settled]


def should_be_cents(sa, today: date, counted_from: date | None) -> int:
    """Decision 13: the monthly amount × the whole months from the month after the last matched payment (or skipped
    installment) through this month; with none yet, from the first month. A one-off never needs more than its cost."""
    start = sa.first_month if counted_from is None else month_add(counted_from.replace(day=1), 1)
    this = today.replace(day=1)
    if start > this:
        return 0
    total = monthly_cents(sa) * (months_between(start, this) + 1)
    return min(total, sa.amount_cents) if sa.kind == "one_off" else total


def share_out(rows: list[tuple[int, date | None, int, int]], balance_cents: int) -> dict[int, int]:
    """Decision 7, soonest due first, in three passes: each takes up to its should-be-by-now; what is left tops each up
    to its next installment; anything still left goes to the last. rows are (set-aside id, next due, should-be,
    installment: 0 for a paid one-off). Nothing is ever negative."""
    order = sorted(rows, key=lambda r: (r[1] or date.max, r[0]))
    left = max(0, balance_cents)
    out: dict[int, int] = {r[0]: 0 for r in order}
    for sa_id, _, should, _ in order:
        take = min(left, should)
        out[sa_id] += take
        left -= take
    for sa_id, _, _, installment in order:
        take = min(left, max(0, installment - out[sa_id]))
        out[sa_id] += take
        left -= take
    unpaid = [r[0] for r in order if r[3] > 0]          # a paid one-off (installment 0) takes nothing in any pass
    if unpaid:
        out[unpaid[-1]] += left
    return out


def state_of(*, linked: bool, today: date, next_due: date | None, missed: bool, put_away: int, should: int,
             installment: int) -> str:
    """The states in their order of precedence (spec, States): short, behind, not_paid, on_track, no_account."""
    if linked and next_due is not None and (next_due - today).days <= SHORT_DAYS and put_away < installment:
        return "short"
    gap = should - put_away
    if linked and gap > BEHIND_MIN_CENTS and gap * 10_000 > BEHIND_MIN_BP * should:
        return "behind"
    if missed:
        return "not_paid"
    return "on_track" if linked else "no_account"


def estimate_of(sa) -> dict | None:
    return json.loads(sa.estimate) if sa.estimate else None


def is_estimate(sa) -> bool:
    """Tagged ESTIMATE until a person changes its year or amount (spec, Estimates)."""
    e = estimate_of(sa)
    return e is not None and not e.get("confirmed", False)


# ---- Reads ----

def active(db: Session) -> list[SetAside]:
    return list(db.scalars(select(SetAside).where(SetAside.archived_at.is_(None)).order_by(SetAside.id)))


def matches_of(db: Session, sa_ids: list[int]) -> dict[int, list[SetAsideMatch]]:
    out: dict[int, list[SetAsideMatch]] = {i: [] for i in sa_ids}
    if sa_ids:
        for m in db.scalars(select(SetAsideMatch).where(SetAsideMatch.set_aside_id.in_(sa_ids)).order_by(SetAsideMatch.due_on, SetAsideMatch.id)):
            out[m.set_aside_id].append(m)
    return out


def settled_dues(rows: list[SetAsideMatch]) -> set[date]:
    """Installments that take no more payments: paid (auto or hand) or skipped. A refusal settles nothing."""
    return {m.due_on for m in rows if m.how != "refused"}


def counted_from(db: Session, rows: list[SetAsideMatch]) -> date | None:
    """The month should-be counts after (engineering choice 4): the latest matched payment's posted month or the
    latest skipped installment's month, whichever is later; None with neither."""
    dates: list[date] = [m.due_on for m in rows if m.how == "skipped"]
    ids = [m.transaction_id for m in rows if m.how in MATCHED_HOWS]
    if ids:
        dates.extend(db.scalars(select(Transaction.posted_at).where(Transaction.id.in_(ids))))
    return max(dates).replace(day=1) if dates else None


@dataclass(frozen=True)
class Standing:
    next_due: date | None
    missed: tuple[date, ...]
    should: int
    put_away: int
    state: str
    installment: int
    counted_from: date | None
    paid: SetAsideMatch | None               # a one-off's matched payment, once it has one
    balance: tuple[date, int] | None         # the linked account's latest snapshot
    shared: tuple[str, ...]                  # the other set-asides on the same account, soonest due first


def standings(db: Session, today: date, sas: list[SetAside] | None = None) -> dict[int, Standing]:
    """Every active set-aside's standing today: its next due date and missed installments, should-be, its share of
    the linked account (decision 7) and its state."""
    wanted = active(db) if sas is None else sas
    # An account is shared out among ALL its active set-asides, whichever were asked for (decision 7), so one
    # set-aside's standing is the same alone as in the list.
    have = {s.id for s in wanted}
    accounts = {s.account_id for s in wanted if s.account_id is not None}
    others = [s for s in active(db) if s.account_id in accounts and s.id not in have] if accounts else []
    sas = list(wanted) + others
    rows = matches_of(db, [s.id for s in sas])
    nd: dict[int, date | None] = {}
    missed: dict[int, tuple[date, ...]] = {}
    should: dict[int, int] = {}
    from_: dict[int, date | None] = {}
    paid: dict[int, SetAsideMatch | None] = {}
    for s in sas:
        settled = settled_dues(rows[s.id])
        nd[s.id] = next_due(s, today, settled)
        missed[s.id] = tuple(missed_dues(s, today, settled))
        from_[s.id] = counted_from(db, rows[s.id])
        paid[s.id] = next((m for m in rows[s.id] if m.how in MATCHED_HOWS), None) if s.kind == "one_off" else None
        should[s.id] = 0 if paid[s.id] is not None else should_be_cents(s, today, from_[s.id])   # a paid one-off needs nothing more
    by_account: dict[int, list[SetAside]] = {}
    for s in sas:
        if s.account_id is not None:
            by_account.setdefault(s.account_id, []).append(s)
    put_away: dict[int, int] = {s.id: 0 for s in sas}
    balances: dict[int, tuple[date, int] | None] = {}
    shared: dict[int, tuple[str, ...]] = {s.id: () for s in sas}
    for account_id, group in by_account.items():
        bal = latest_balance(db, account_id)
        balances[account_id] = bal
        order = sorted(group, key=lambda s: (nd[s.id] or date.max, s.id))
        put_away.update(share_out([(s.id, nd[s.id], should[s.id], 0 if paid[s.id] is not None else installment_cents(s)) for s in group], bal[1] if bal else 0))
        for s in group:
            shared[s.id] = tuple(o.name for o in order if o.id != s.id)
    out: dict[int, Standing] = {}
    for s in wanted:
        linked = s.account_id is not None
        state = state_of(linked=linked, today=today, next_due=nd[s.id], missed=bool(missed[s.id]),
                         put_away=put_away[s.id], should=should[s.id], installment=installment_cents(s))
        if paid[s.id] is not None:
            state = "on_track"                      # a paid one-off asks for nothing more; the detail offers the next one
        out[s.id] = Standing(nd[s.id], missed[s.id], should[s.id], put_away[s.id], state, installment_cents(s),
                             from_[s.id], paid[s.id], balances.get(s.account_id) if linked else None, shared[s.id])
    return out


# ---- Estimates (spec, Estimates; engineering choice 11) ----

ITEMS: tuple[str, ...] = ("roof", "water_heater", "hvac", "car", "appliance", "other")
DATA = Path(__file__).with_name("setaside_lifespans.json")
MIN_YEAR = 1950
MAX_MILES = 1_000_000


class EstimateError(ValueError):
    """A refusal in plain words; POST /setasides/estimate answers 422 with it."""


@cache
def lifespans() -> dict:
    """The data file, checked the way the engine's rules tables are: a source list at the top, the date it was
    checked and what that covers, and a source line (and a cost source line) on every item."""
    raw = json.loads(DATA.read_text())
    source, checked = raw.get("source"), raw.get("checked")
    if not isinstance(source, list) or not source or not isinstance(checked, dict) or not checked.get("date") \
            or not isinstance(checked.get("covers"), list):
        raise EstimateError(f"{DATA.name} needs a source list and the date it was checked, with what that covers")
    for key, item in raw["items"].items():
        if not str(item.get("source", "")).strip() or not str(item.get("cost_source", "")).strip():
            raise EstimateError(f"{DATA.name}: {key} needs a source")
    return raw


def _year(value, name: str, today: date) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise EstimateError(f"Enter the {name} as a year like 2014.")
    if value < MIN_YEAR:
        raise EstimateError(f"Enter a year from {MIN_YEAR} on.")
    if value > today.year:
        raise EstimateError("That year is in the future.")
    return value


def estimate(item: str, today: date, *, installed_year: int | None = None, model_year: int | None = None,
             miles: int | None = None, first_month: date | None = None, cost_cents: int | None = None) -> dict:
    """An estimate from the item's age (spec, Estimates): the end of its usual range from the install year (a car:
    the earlier of its age end and the year it passes the high mileage at its miles so far per year), planned a year
    before the end and for December of that year; the amount is the middle of the cost range, less a car's sale
    value. An item already past its range is planned for this December, or next year's in December.
    `cost_cents` carries a given cost instead of the middle of the range (the next replacement after a one-off is
    paid costs what that one did); nothing is taken off it."""
    if item == "other":
        raise EstimateError("Something else has no typical lifespan: enter the year and the amount yourself.")
    if item not in ITEMS:
        raise EstimateError("Choose Roof, Water heater, Heating and cooling, Car, Appliance or Something else.")
    if cost_cents is not None and (not isinstance(cost_cents, int) or isinstance(cost_cents, bool) or cost_cents <= 0):
        raise EstimateError("Enter the cost as a positive amount.")
    data = lifespans()
    spec = data["items"][item]
    lo, hi = spec["lifespan_years"]
    first = first_month or first_month_after(today)
    if item == "car":
        if model_year is None:
            raise EstimateError("Enter the car's model year.")
        start = _year(model_year, "model year", today)
        if miles is not None and (not isinstance(miles, int) or isinstance(miles, bool) or not 0 <= miles <= MAX_MILES):
            raise EstimateError("Enter the miles as a whole number.")
    else:
        if installed_year is None:
            raise EstimateError("Enter the year it was installed.")
        start = _year(installed_year, "installed year", today)
    age = today.year - start
    end, decided_by = start + hi, "age"
    per_year = None
    miles_range = spec.get("lifespan_miles")
    if item == "car" and miles and age > 0:
        per_year = div_round(miles, age)
        # The year it passes the high mileage at this pace; a car already past it reaches it this year. Under half a
        # mile a year there is no pace to count, so age decides.
        if per_year:
            miles_end = today.year + (miles_range[1] - miles) // per_year if miles < miles_range[1] else today.year
            if miles_end < end:
                end, decided_by = miles_end, "miles"
    planned = max(end - 1, today.year + (1 if today.month == 12 else 0))
    clo, chi = spec["cost_cents"]
    replacement = cost_cents if cost_cents is not None else div_round(clo + chi, 2)
    sale = div_round(replacement * spec["resale_bp"], 10_000) if item == "car" and cost_cents is None else 0
    amount = replacement - sale
    months = months_through(first, planned, 12)
    return {"item": item, "label": spec["label"], "installed_year": None if item == "car" else start,
            "model_year": start if item == "car" else None, "miles": miles if item == "car" else None, "age": age,
            "miles_per_year": per_year, "lifespan": [lo, hi], "lifespan_miles": miles_range,
            "range": [start + lo, end], "decided_by": decided_by, "planned_year": planned, "due_year": planned,
            "due_month": 12, "cost_range": [clo, chi], "replacement_cents": replacement, "sale_cents": sale,
            "amount_cents": amount, "months": months, "first_month": first.isoformat(),
            "monthly_cents": div_round(amount, months), "sources": [spec["source"], spec["cost_source"]],
            "to_check": item in data["needs_check"], "cost_to_check": True}


def estimate_json(e: dict) -> str:
    """What SetAside.estimate stores: the basis, and confirmed=False until a person changes the year or amount."""
    return json.dumps({"item": e["item"], "installed_year": e["installed_year"], "model_year": e["model_year"],
                       "miles": e["miles"], "lifespan": e["lifespan"], "cost_range": e["cost_range"],
                       "planned_year": e["planned_year"], "replacement_cents": e["replacement_cents"],
                       "sale_cents": e["sale_cents"], "to_check": e["to_check"], "cost_to_check": e["cost_to_check"],
                       "confirmed": False})


# ---- Matching (spec, Matching payments; engineering choices 1, 5, 6) ----

class MatchError(ValueError):
    """A refusal in plain words; the match routes answer 422 with it."""


class StoppedError(MatchError):
    """The set-aside was stopped: the route answers 409."""


def payee_key_of(t: Transaction) -> str:
    return payee(t.raw_description, t.merchant).key


def candidate_clauses() -> tuple:
    """Money out on the household's cash accounts, not a transfer, with no match row of any kind yet: a refusal, a
    skip or a match elsewhere all take the payment out of automatic matching."""
    taken = select(SetAsideMatch.transaction_id).where(SetAsideMatch.transaction_id.is_not(None))
    return (*personal_clauses(), Transaction.amount_cents < 0, Transaction.category != "transfer",
            Transaction.id.not_in(taken))


def _within_tolerance(cents: int, installment: int) -> bool:
    return abs(cents - installment) * 10_000 <= installment * AMOUNT_TOLERANCE_BP


def candidates(db: Session, sa, due_on: date) -> list[tuple[Transaction, int]]:
    """Rows that could be the payment of one installment: in its window, by the payee key (or by the category when
    no payee is set; never for a one-off), and within +-25% of the installment. With their personal cents."""
    if sa.payee_key is None and (sa.category is None or sa.kind == "one_off"):
        return []
    lo, hi = due_on - timedelta(days=BEFORE_DAYS), due_on + timedelta(days=LATE_DAYS)
    q = (select(Transaction, -personal_amount()).join(Account, Account.id == Transaction.account_id)
         .where(Transaction.posted_at >= lo, Transaction.posted_at <= hi, *candidate_clauses())
         .order_by(Transaction.posted_at, Transaction.id))
    if sa.payee_key is None:
        q = q.where(Transaction.category == sa.category)
    return [(t, int(cents)) for t, cents in db.execute(q)
            if (sa.payee_key is None or payee_key_of(t) == sa.payee_key) and _within_tolerance(int(cents), installment_cents(sa))]


def _open_dues(sa, today: date, settled: set[date]) -> list[date]:
    """Installments matching can fill: from 25 months back to 45 days ahead, oldest first, not paid or skipped."""
    start = month_add(today.replace(day=1), -HISTORY_MONTHS)
    return [d for d in due_dates(sa, start, today + timedelta(days=BEFORE_DAYS)) if d not in settled]


def match_set_aside(db: Session, sa, today: date, *, by: int | None = None) -> list[SetAsideMatch]:
    """Each open installment takes at most one payment: the closest in date (ties: the earlier posted, the lower id),
    marked late when it posted after the due date. Logs nothing: an add or an edit folds the count into its own
    event. Returns the new rows; the caller commits."""
    settled = settled_dues(matches_of(db, [sa.id])[sa.id])
    made: list[SetAsideMatch] = []
    for due_on in _open_dues(sa, today, settled):
        found = candidates(db, sa, due_on)
        if not found:
            continue
        t, _ = min(found, key=lambda tc: (abs((tc[0].posted_at - due_on).days), tc[0].posted_at, tc[0].id))
        m = SetAsideMatch(transaction_id=t.id, set_aside_id=sa.id, due_on=due_on, how="auto", late=t.posted_at > due_on,
                          created_by=by)
        db.add(m)
        db.flush()                      # so the next installment's candidates leave this payment out
        made.append(m)
    return made


def day_text(d: date) -> str:
    return f"{calendar.month_abbr[d.month]} {d.day}, {d.year}"


def match_all(db: Session, today: date, *, by: int | None = None, log: bool = True) -> list[SetAsideMatch]:
    """After a sync or an import: every active set-aside, oldest first, and one summary event when anything matched
    (log=False leaves the event to the caller). A parent book is never asked: it has no set-asides."""
    made: list[SetAsideMatch] = []
    names: list[str] = []
    for s in active(db):
        for m in match_set_aside(db, s, today, by=by):
            made.append(m)
            names.append(f"{s.name} ({day_text(m.due_on)})")
    if made and log:
        n = len(made)
        log_event(db, "info", "setaside", f"Steward matched {n} payment{'s' if n != 1 else ''} to set-asides: {', '.join(names)}.")
    return made


def match_by_hand(db: Session, t: Transaction, sa, today: date, *, by: int) -> SetAsideMatch:
    """Decision 15: a person pairs a payment with the unpaid installment nearest its date, whatever the window and the
    amount (a one-off has just its one date, however far away). A refused payment is moved: its one row is rewritten.
    A payment already matched, or any payment on a paid-up one-off, is refused in plain words."""
    if t.amount_cents >= 0 or t.is_transfer or t.category == "transfer":
        raise MatchError("Only money out can be paid from a set-aside.")
    household = select(Transaction.id).join(Account, Account.id == Transaction.account_id).where(Transaction.id == t.id, *personal_clauses())
    if db.scalar(household) is None:            # all business: Spending never shows it, so the match would show nowhere
        raise MatchError("That payment is business. Only household payments can be paid from a set-aside."
                         if t.is_business else "Only payments from household accounts can be paid from a set-aside.")
    existing = db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == t.id))
    if existing is not None and existing.how in MATCHED_HOWS:
        raise MatchError("That payment is already matched to a set-aside. Undo that first.")
    settled = settled_dues(matches_of(db, [sa.id])[sa.id])
    if sa.kind == "one_off":
        if settled:
            raise MatchError(f"{sa.name} is already paid.")
        due_on = date(sa.due_year, sa.due_month, 1)
    else:
        far = timedelta(days=800)
        open_dues = [d for d in due_dates(sa, min(sa.first_month, t.posted_at) - far, max(today, t.posted_at) + far)
                     if d not in settled]
        if not open_dues:
            raise MatchError(f"Every installment of {sa.name} is already paid.")
        due_on = min(open_dues, key=lambda d: (abs((d - t.posted_at).days), d))
    if existing is None:
        existing = SetAsideMatch(transaction_id=t.id)
        db.add(existing)
    existing.set_aside_id, existing.due_on, existing.how = sa.id, due_on, "hand"
    existing.late, existing.created_by = t.posted_at > due_on, by
    db.flush()
    return existing


def refuse(db: Session, transaction_id: int, *, by: int) -> SetAsideMatch:
    """"Not this one" (spec, Undo): the row becomes a refusal, so the pairing is never offered again, the
    installment goes back to unpaid and the payment back to its category."""
    m = db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == transaction_id, SetAsideMatch.how.in_(MATCHED_HOWS)))
    if m is None:
        raise MatchError("That payment isn't matched to a set-aside.")
    if db.get(SetAside, m.set_aside_id).archived_at is not None:
        raise StoppedError("That set-aside was stopped.")          # its matches are history
    m.how, m.late, m.created_by = "refused", False, by
    db.flush()
    return m


def skip_due(db: Session, sa, due_on: date, *, by: int) -> SetAsideMatch:
    """"It was not due": the installment is settled with no payment, so not_paid clears and should-be counts on from
    the month after it."""
    far = timedelta(days=800)
    if due_on not in due_dates(sa, due_on - far, due_on + far):
        raise MatchError(f"{day_text(due_on)} is not one of {sa.name}'s due dates.")
    if due_on in settled_dues(matches_of(db, [sa.id])[sa.id]):
        raise MatchError(f"{day_text(due_on)} is already settled.")
    m = SetAsideMatch(transaction_id=None, set_aside_id=sa.id, due_on=due_on, how="skipped", late=False, created_by=by)
    db.add(m)
    db.flush()
    return m


# ---- Suggestions (spec, Suggestions; polish round item 3) ----

COUNTY = re.compile(r"COUNTY|TAX COLLECTOR|TREASURER")
GROUPS: tuple[str, ...] = ("home", "car", "kids", "memberships", "other")
# P22: with no known kind, only these categories can hold a yearly cost. Never: groceries, dining, shopping,
# entertainment, personal, travel, gifts, cash_atm, fees, business_expense, loan_payments.
ELIGIBLE: tuple[str, ...] = ("insurance", "taxes", "subscriptions", "childcare_education", "kids", "health", "home",
                             "housing", "utilities", "pets", "giving", "transport")


@dataclass(frozen=True)
class KnownKind:
    """A yearly cost Steward knows (spec, What's suggested). It matches when the category is one of `categories` (any,
    when empty) and one of `words` is in the payee's text (any, when empty). `name` is its clean name; None keeps the
    vendor's. The table is data, so it can grow without code."""
    key: str
    group: str
    name: str | None
    categories: tuple[str, ...] = ()
    words: tuple[str, ...] = ()


KNOWN_KINDS: tuple[KnownKind, ...] = (                      # first match wins
    KnownKind("property_tax", "home", "Property tax", ("taxes",), (COUNTY.pattern,)),   # today's county rule
    KnownKind("dmv", "car", "DMV registration", (), (r"\bDMV\b", "MOTOR VEHICLE", "VEHICLE REG", "REGISTRATION")),
    KnownKind("car_insurance", "car", "Car insurance", ("insurance",), (r"\bAUTO\b", r"\bCAR\b", "GEICO", "PROGRESSIVE")),
    KnownKind("home_insurance", "home", "Home insurance", ("insurance",), (r"\bHOME\b", "HOMEOWNER", "PROPERTY", "HAZARD")),
    KnownKind("aaa", "car", "AAA", (), (r"\bAAA\b",)),
    KnownKind("membership", "memberships", None, (), ("MEMBERSHIP", r"\bPRIME\b", "COSTCO MEMBER", "SAMS CLUB")),
    KnownKind("school", "kids", None, ("childcare_education",)),                 # School: the category, or…
    KnownKind("school_words", "kids", None, (), (r"\bSCHOOL\b", r"\bPTA\b", "DISTRICT", "TUITION")),   # …the words
    KnownKind("yearly_subscription", "memberships", None, ("subscriptions",)),
    KnownKind("other_insurance", "other", None, ("insurance",)),
)


@cache
def _known_words() -> tuple[tuple[KnownKind, re.Pattern | None], ...]:
    return tuple((k, re.compile("|".join(k.words)) if k.words else None) for k in KNOWN_KINDS)


def known_kind(text: str, category: str) -> KnownKind | None:
    """The first known kind the payee's text (upper case) and category match, or None."""
    t = text.upper()
    for k, rx in _known_words():
        if k.categories and category not in k.categories:
            continue
        if rx is not None and not rx.search(t):
            continue
        return k
    return None


@dataclass(frozen=True)
class Covered:
    """What suggestions leave out (spec, What's left out): payees with a set-aside (archived ones too, so stopping one
    does not bring its suggestion back), categories with a set-aside that names no payee, and the (payee, category)
    pairs a person refused or dismissed."""
    payees: frozenset[str]
    categories: frozenset[str]
    pairs: frozenset[tuple[str, str]]

    def has(self, key: str, category: str) -> bool:
        return key in self.payees or category in self.categories or (key, category) in self.pairs


def _covered(db: Session) -> Covered:
    payees: set[str] = set()
    categories: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for s in db.scalars(select(SetAside)):
        if s.payee_key:
            payees.add(s.payee_key)
        elif s.category:
            categories.add(s.category)
    refused = select(SetAsideMatch.transaction_id).where(SetAsideMatch.how == "refused")
    for t in db.scalars(select(Transaction).where(Transaction.id.in_(refused))):
        pairs.add((payee_key_of(t), t.category))
    for d in db.scalars(select(SetAsideDismissed)):
        pairs.add((d.payee_key, d.category))
    return Covered(frozenset(payees), frozenset(categories), frozenset(pairs))


Row = tuple[date, int, str, str]       # posted, personal cents, payee name, the bank's text (tidy)


def _groups(db: Session, today: date) -> dict[tuple[str, str], list[Row]]:
    """Money out over the last 25 months by (payee key, category), newest first."""
    start = month_add(today.replace(day=1), -HISTORY_MONTHS)
    q = (select(Transaction, -personal_amount()).join(Account, Account.id == Transaction.account_id)
         .where(Transaction.posted_at >= start, Transaction.posted_at <= today, Transaction.amount_cents < 0,
                Transaction.category != "transfer", *personal_clauses())
         .order_by(Transaction.posted_at.desc(), Transaction.id.desc()))
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for t, cents in db.execute(q):
        p = payee(t.raw_description, t.merchant)
        if p.key:
            groups[(p.key, t.category)].append((t.posted_at, int(cents), p.name, tidy(t.raw_description)))
    return groups


def _candidate(key: str, category: str, rows: list[Row]) -> tuple[str, str, bool] | None:
    """Item 3's first gates for one payee and category: a known kind (always eligible), or a category on the list.
    Returns (clean name, group, whether the county rule applies), or None."""
    k = known_kind(f"{key} {rows[0][3]}", category)
    if k is None:
        return (rows[0][2], "other", False) if category in ELIGIBLE else None
    return k.name or rows[0][2], k.group, k.key == "property_tax"


def _similar(rows: list[Row]) -> bool:
    """P23: every payment within 25% of the newest."""
    newest = rows[0][1]
    return all(abs(c - newest) * 10_000 <= newest * AMOUNT_TOLERANCE_BP for _, c, _, _ in rows)


def _suggestion(name: str, category: str, group: str, county: bool, payee_key: str, rows: list[Row]) -> dict | None:
    """Decision 5's timing on the pooled payments (newest first): every gap 10-14 months is yearly, 5-7 months twice a
    year; a county tax payment that fits neither, one included, is twice a year. Anything else is no suggestion."""
    if not _similar(rows):
        return None
    dates = sorted({d for d, _, _, _ in rows}, reverse=True)
    gaps = [months_between(b, a) for a, b in zip(dates, dates[1:])]
    latest, cents = dates[0], rows[0][1]
    if gaps and all(10 <= g <= 14 for g in gaps):
        kind, second = "yearly", (None, None)
    elif gaps and all(5 <= g <= 7 for g in gaps):
        kind, second = "twice_yearly", (dates[1].month, dates[1].day)
    elif county:
        kind, second = "twice_yearly", (month_add(latest.replace(day=1), 6).month, latest.day)
    else:
        return None
    yearly = cents if kind == "yearly" else 2 * cents
    return {"key": f"{payee_key}|{category}", "name": name, "group": group, "kind": kind, "amount_cents": cents,
            "yearly_cents": yearly, "monthly_cents": div_round(yearly, 12),
            "months": sorted({latest.month, *([second[0]] if second[0] else [])}),
            "payee_key": payee_key, "category": category, "due_month": latest.month, "due_day": latest.day,
            "second_month": second[0], "second_day": second[1], "payments": [d.isoformat() for d in dates]}


def _pooled(groups: dict[tuple[str, str], list[Row]]) -> list[tuple[list[str], dict]]:
    """P24: groups that clear the gates, merged by (clean name, category): their payments pool, the timing is worked
    out again from the pooled dates, and the newest payment's payee key is kept. Returns (every key, suggestion)."""
    pools: dict[tuple[str, str], dict] = {}
    for (key, category), rows in groups.items():
        c = _candidate(key, category, rows)
        if c is None:
            continue
        name, group, county = c
        p = pools.setdefault((name, category), {"keys": [], "rows": [], "group": group, "county": False, "newest": None})
        p["keys"].append(key)
        p["rows"] += rows
        p["county"] = p["county"] or county
        if p["newest"] is None or rows[0][0] > p["newest"][0]:
            p["newest"] = (rows[0][0], key)
    out = []
    for (name, category), p in pools.items():
        pooled = sorted(p["rows"], key=lambda r: r[0], reverse=True)
        s = _suggestion(name, category, p["group"], p["county"], p["newest"][1], pooled)
        if s is not None:
            out.append((p["keys"], s))
    return out


def find_occasional(db: Session, today: date) -> list[dict]:
    """Payees paid once or twice a year in the last 25 months, not yet set aside, refused or dismissed (a merged row
    is left out when any of its payee keys is: Engineering choice 15). By group (Home, Car, Kids, Memberships,
    Other), the largest year first; nothing is picked."""
    covered = _covered(db)
    out = [s for keys, s in _pooled(_groups(db, today)) if not any(covered.has(k, s["category"]) for k in keys)]
    return sorted(out, key=lambda s: (GROUPS.index(s["group"]), -s["yearly_cents"], s["name"]))


def dismissed_view(db: Session, today: date) -> list[dict]:
    """The folded lines: each dismissed payee with what it would have set aside a month."""
    groups = _groups(db, today)
    covered = _covered(db)
    out = []
    for d in db.scalars(select(SetAsideDismissed).order_by(SetAsideDismissed.id)):
        if d.payee_key in covered.payees or d.category in covered.categories:
            continue                    # a set-aside has taken it since: nothing to bring back
        rows = groups.get((d.payee_key, d.category), [])
        found = _pooled({(d.payee_key, d.category): rows}) if rows else []
        out.append({"payee_key": d.payee_key, "category": d.category, "payee_name": rows[0][2] if rows else d.payee_key,
                    "monthly_cents": found[0][1]["monthly_cents"] if found else 0})
    return out

def history_months(db: Session, today: date) -> int:
    """Decision 18: the days from the earliest personal transaction to today, over 30.44, rounded, at most the 25
    months looked at (SimpleFIN's 90 days reads 3 months)."""
    earliest = db.scalar(select(func.min(Transaction.posted_at)).join(Account, Account.id == Transaction.account_id)
                         .where(*personal_clauses()))
    if earliest is None:
        return 0
    return max(0, min(HISTORY_MONTHS, round((today - earliest).days / 30.44)))


def suggestions_view(db: Session, today: date) -> dict:
    return {"suggestions": find_occasional(db, today), "dismissed": dismissed_view(db, today),
            "history_months": history_months(db, today)}


def _dismissal(db: Session, payee_key: str, category: str) -> SetAsideDismissed | None:
    return db.scalar(select(SetAsideDismissed).where(SetAsideDismissed.payee_key == payee_key,
                                                     SetAsideDismissed.category == category))


def dismiss(db: Session, payee_key: str, category: str, *, by: int) -> SetAsideDismissed:
    row = _dismissal(db, payee_key, category)
    if row is None:
        row = SetAsideDismissed(payee_key=payee_key, category=category, created_by=by)
        db.add(row)
        db.flush()
    return row


def restore(db: Session, payee_key: str, category: str) -> bool:
    row = _dismissal(db, payee_key, category)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


# ---- The views (spec, API) ----

def dollars_text(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def payee_name_of(db: Session, key: str) -> str:
    """The payee as Transactions shows it: from the latest payment with that key, else the key in title case."""
    for t in db.scalars(select(Transaction).join(Account, Account.id == Transaction.account_id)
                        .where(Transaction.amount_cents < 0, *personal_clauses())
                        .order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(400)):
        p = payee(t.raw_description, t.merchant)
        if p.key == key:
            return p.name
    return display(key.split(":", 1)[-1])


def describe(sa) -> str:
    """The event line's words: "Water heater, $2,200 about 2028"."""
    amount = dollars_text(sa.amount_cents)
    if sa.kind == "yearly":
        return f"{sa.name}, {amount} a year, due {calendar.month_abbr[sa.due_month]} {sa.due_day}"
    if sa.kind == "twice_yearly":
        return (f"{sa.name}, {amount} twice a year, {calendar.month_abbr[sa.due_month]} {sa.due_day} and "
                f"{calendar.month_abbr[sa.second_month]} {sa.second_day}")
    return f"{sa.name}, {amount} about {sa.due_year}"


def _iso(d) -> str | None:
    return None if d is None else d.isoformat()


def row_out(db: Session, sa: SetAside, st: Standing, today: date) -> dict:
    account = None
    if sa.account_id is not None:
        a = db.get(Account, sa.account_id)
        # as_of is the snapshot's date; stale (older than STALE_DAYS) tells the web to say "balance from Oct 12"
        account = {"id": a.id, "name": a.name, "balance_cents": st.balance[1] if st.balance else None,
                   "as_of": _iso(st.balance[0]) if st.balance else None,
                   "stale": st.balance is not None and (today - st.balance[0]).days > STALE_DAYS,
                   "shared_with": list(st.shared)}
    paid = None
    if st.paid is not None:
        t = db.get(Transaction, st.paid.transaction_id)
        paid = {"transaction_id": t.id, "posted_at": _iso(t.posted_at), "cents": -int(t.amount_cents),
                "account_name": db.get(Account, t.account_id).name}
    short = max(0, st.installment - st.put_away) if st.state == "short" else 0
    behind = max(0, st.should - st.put_away) if st.state == "behind" else 0
    return {"id": sa.id, "name": sa.name, "kind": sa.kind, "amount_cents": sa.amount_cents,
            "monthly_cents": monthly_cents(sa), "yearly_cents": yearly_cents(sa), "installment_cents": st.installment,
            "due_month": sa.due_month, "due_day": sa.due_day, "second_month": sa.second_month, "second_day": sa.second_day,
            "due_year": sa.due_year, "first_month": _iso(sa.first_month), "next_due": _iso(st.next_due),
            "days_until": None if st.next_due is None else (st.next_due - today).days,
            "missed_due": _iso(st.missed[0]) if st.missed else None, "is_estimate": is_estimate(sa),
            "estimate": estimate_of(sa), "account": account, "put_away_cents": st.put_away, "should_cents": st.should,
            "state": st.state, "short_cents": short, "behind_cents": behind, "counted_from": _iso(st.counted_from),
            "payee_key": sa.payee_key, "payee_name": payee_name_of(db, sa.payee_key) if sa.payee_key else None,
            "category": sa.category, "notes": sa.notes, "paid": paid, "archived_at": _iso(sa.archived_at)}


def _order(sa: SetAside, st: Standing):
    """Soonest due first, one-offs last (spec, Pages)."""
    return (sa.kind == "one_off", st.next_due or date.max, sa.id)


def list_view(db: Session, today: date) -> dict:
    sas = active(db)
    st = standings(db, today, sas)
    rows = [row_out(db, s, st[s.id], today) for s in sorted(sas, key=lambda s: _order(s, st[s.id]))]
    any_ever = db.scalar(select(SetAside.id).limit(1)) is not None      # archived ones count: a book that has stopped all is not new
    return {"as_of": today.isoformat(), "monthly_cents": sum(r["monthly_cents"] for r in rows), "count": len(rows),
            "yearly_cents": sum(r["yearly_cents"] for r in rows),
            "one_off_cents": sum(r["amount_cents"] for r in rows if r["kind"] == "one_off"),
            "needs_look": sum(1 for r in rows if r["state"] in NEEDS_LOOK), "rows": rows,
            **suggestions_view(db, today), "first_visit": not any_ever}


def _which(sa, d: date) -> str | None:
    if sa.kind != "twice_yearly":
        return None
    return "first" if (d.month, d.day) == (sa.due_month, safe_date(d.year, sa.due_month, sa.due_day).day) else "second"


def dues_out(db: Session, sa: SetAside, st: Standing, today: date) -> list[dict]:
    """The schedule (mockup, When it is due): missed installments, settled ones from the last 60 days, the next
    unpaid one (the row's next_due) and, twice a year, the one after. An unpaid installment before next_due's start
    (more than 6 weeks past, or due before the set-aside was added) is shown only when it was missed."""
    rows = matches_of(db, [sa.id])[sa.id]
    by_due = {m.due_on: m for m in rows if m.how != "refused"}
    posted = {m.transaction_id: db.get(Transaction, m.transaction_id) for m in rows if m.transaction_id}
    start = min([today - timedelta(days=60), *st.missed])
    open_from = next_from(sa, today)
    want = 2 if sa.kind == "twice_yearly" else 1
    out, upcoming = [], 0
    for d in due_dates(sa, min(start, sa.first_month), date.max if sa.kind == "one_off" else today + timedelta(days=800)):
        m = by_due.get(d)
        if m is None:
            if d in st.missed:
                status = "missed"
            elif d < open_from:
                continue
            elif upcoming < want:
                status = "next" if upcoming == 0 else "upcoming"
                upcoming += 1
            else:
                continue
            paid_on, days_late = None, None
        elif m.how == "skipped":
            if d < start:
                continue
            status, paid_on, days_late = "skipped", None, None
        else:
            if d < start:
                continue
            t = posted[m.transaction_id]
            status, paid_on, days_late = ("late" if m.late else "paid"), t.posted_at.isoformat(), max(0, (t.posted_at - d).days)
        out.append({"due_on": d.isoformat(), "status": status, "which": _which(sa, d), "amount_cents": st.installment,
                    "paid_on": paid_on, "days_late": days_late, "days_until": (d - today).days})
    return out


def payments_out(db: Session, sa: SetAside) -> list[dict]:
    q = (select(SetAsideMatch, Transaction, Account.name).join(Transaction, Transaction.id == SetAsideMatch.transaction_id)
         .join(Account, Account.id == Transaction.account_id)
         .where(SetAsideMatch.set_aside_id == sa.id, SetAsideMatch.how.in_(MATCHED_HOWS))
         .order_by(Transaction.posted_at.desc(), Transaction.id.desc()))
    return [{"transaction_id": t.id, "posted_at": t.posted_at.isoformat(), "account_name": name, "merchant": t.merchant,
             "nickname": t.nickname, "raw_description": t.raw_description, "category": t.category, "amount_cents": t.amount_cents,
             "due_on": m.due_on.isoformat(), "how": m.how, "late": m.late, "days_late": max(0, (t.posted_at - m.due_on).days)}
            for m, t, name in db.execute(q)]


def replace_out(db: Session, sa: SetAside, st: Standing, today: date) -> dict | None:
    """Decision 4: a paid one-off offers the next one, estimated the same way from the year it was paid and costing
    what this one did."""
    if st.paid is None:
        return None
    t = db.get(Transaction, st.paid.transaction_id)
    paid_cents = -int(t.amount_cents)
    e = estimate_of(sa)
    nxt = None
    if e and e.get("item") in ITEMS and e["item"] != "other" and paid_cents > 0:
        try:
            nxt = estimate(e["item"], today, installed_year=t.posted_at.year, model_year=t.posted_at.year if e["item"] == "car" else None,
                           cost_cents=paid_cents)
        except EstimateError:
            nxt = None
    return {"paid_on": t.posted_at.isoformat(), "paid_cents": paid_cents, "next": nxt}


def detail_view(db: Session, today: date, sa: SetAside) -> dict:
    st = standings(db, today, [sa])[sa.id]
    replace = replace_out(db, sa, st, today)
    nxt = replace["next"] if replace else None
    offer = None if nxt is None else {"year": nxt["planned_year"], "cents": nxt["amount_cents"], "monthly_cents": nxt["monthly_cents"]}
    row = row_out(db, sa, st, today)
    e = row["estimate"]
    if e and e.get("item") in ITEMS and e["item"] != "other":
        # The page's evidence, from the data file and the stored inputs: the item's own sources (lifespan, cost) and its age.
        spec = lifespans()["items"][e["item"]]
        start = e.get("installed_year") or e.get("model_year")
        row["estimate"] = {**e, "sources": [spec["source"], spec["cost_source"]], "age": None if start is None else today.year - start}
    missed = st.missed[0] if st.missed else None
    return {**row, "as_of": today.isoformat(), "dues": dues_out(db, sa, st, today), "payments": payments_out(db, sa),
            "replace": replace, "replace_offer": offer,
            # "Find the payment": the range to look in, from the matcher's own look-back to today
            "find_from": None if missed is None else (missed - timedelta(days=BEFORE_DAYS)).isoformat(),
            "find_to": None if missed is None else today.isoformat()}


# ---- The writes (spec, API; events in spec, Data) ----

class SetAsideError(ValueError):
    """A refusal in plain words; the routes answer 422 with it."""


NOT_UNDERSTOOD = "That request wasn't understood."
BAD_NAME = "Give it a name of up to 120 characters."
BAD_KIND = "Choose Every year, Twice a year or Once."
BAD_AMOUNT = "Enter an amount from $0.01 to $1,000,000."
BAD_MONTH = "Choose a month from 1 to 12."
BAD_DAY = "Choose a day from 1 to 31."
NEEDS_TWO = "Twice a year needs two due dates."
SAME_DATES = "The two due dates must differ."
NEEDS_YEAR = "Once needs a year and a month."
PAST_MONTH = "That month has passed. Choose this month or later."
BAD_ACCOUNT = "Choose a checking or savings account."
BAD_CATEGORY = "That isn't a category Spending tracks."
BAD_NOTES = "Notes can be up to 500 characters."
BAD_ITEM = "Choose Roof, Water heater, Heating and cooling, Car, Appliance or Something else."
ONLY_ONE_OFF_ESTIMATES = "Only a cost that comes once has an estimate."
MAX_AMOUNT_CENTS = 100_000_000
NEVER_SPENDING = ("income", "business_income", "interest", "transfer", "uncategorized")
COMMON_FIELDS = ("name", "kind", "amount_cents", "account_id", "payee_key", "category", "notes")
DATE_FIELDS = ("due_month", "due_day", "second_month", "second_day", "due_year")
KIND_FIELDS = {"yearly": ("due_month", "due_day"), "twice_yearly": ("due_month", "due_day", "second_month", "second_day"),
               "one_off": ("due_year", "due_month")}
NOT_FOR_KIND = {"yearly": "Every year takes one due date: leave out the second date and the year.",
                "twice_yearly": "Twice a year takes two due dates: leave out the year.",
                "one_off": "Once takes a year and a month: leave out the day and the second date."}


def _int(value, lo: int, hi: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise SetAsideError(message)
    return value


def _month_day(f: dict, month_key: str, day_key: str) -> tuple[int, int]:
    month = _int(f.get(month_key), 1, 12, BAD_MONTH)
    day = _int(f.get(day_key), 1, 31, BAD_DAY)
    most = calendar.monthrange(2024, month)[1]          # a leap year: Feb 29 is a due day, clamped in common years
    if day > most:
        raise SetAsideError(f"{calendar.month_name[month]} has at most {most} days.")
    return month, day


def _merged(body: dict, current) -> dict:
    """A PUT changes only the fields sent: the rest come from the set-aside as it is. Date fields carry over only
    where the kind keeps them (a change of kind keeps the dates the old and new kind share)."""
    merged = dict(body)
    kind = merged.get("kind", current.kind)
    if not isinstance(kind, str) or kind not in KINDS:
        raise SetAsideError(BAD_KIND)
    for key in COMMON_FIELDS:
        merged.setdefault(key, getattr(current, key))
    for key in DATE_FIELDS:
        if key not in merged and key in KIND_FIELDS.get(kind, ()) and key in KIND_FIELDS[current.kind]:
            merged[key] = getattr(current, key)
    return merged


def parse_body(body, today: date, current=None) -> dict:
    """The POST and PUT body (spec, Kinds): name, kind and amount; the dates for the kind (fields that don't belong to
    the kind are refused); an optional account, payee key, category, estimate inputs and notes. With `current` (a PUT),
    fields not sent keep their value. Raises SetAsideError."""
    if not isinstance(body, dict):
        raise SetAsideError(NOT_UNDERSTOOD)
    if current is not None:
        body = _merged(body, current)
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise SetAsideError(BAD_NAME)
    kind = body.get("kind")
    if kind not in KINDS:
        raise SetAsideError(BAD_KIND)
    f: dict = {"name": name.strip(), "kind": kind, "amount_cents": _int(body.get("amount_cents"), 1, MAX_AMOUNT_CENTS, BAD_AMOUNT),
               "due_month": None, "due_day": None, "second_month": None, "second_day": None, "due_year": None}
    if any(body.get(k) is not None for k in DATE_FIELDS if k not in KIND_FIELDS[kind]):
        raise SetAsideError(NOT_FOR_KIND[kind])
    if kind == "yearly":
        f["due_month"], f["due_day"] = _month_day(body, "due_month", "due_day")
    elif kind == "twice_yearly":
        f["due_month"], f["due_day"] = _month_day(body, "due_month", "due_day")
        if body.get("second_month") is None or body.get("second_day") is None:
            raise SetAsideError(NEEDS_TWO)
        f["second_month"], f["second_day"] = _month_day(body, "second_month", "second_day")
        if (f["due_month"], f["due_day"]) == (f["second_month"], f["second_day"]):
            raise SetAsideError(SAME_DATES)
    else:
        if body.get("due_year") is None or body.get("due_month") is None:
            raise SetAsideError(NEEDS_YEAR)
        was = (current.due_year, current.due_month) if current is not None and current.kind == "one_off" else None
        if was is not None and body["due_year"] == was[0]:
            f["due_year"] = was[0]                      # an unchanged year stays, even when it has gone by
        else:
            f["due_year"] = _int(body.get("due_year"), today.year, today.year + 60, f"Choose a year from {today.year} to {today.year + 60}.")
        f["due_month"] = _int(body.get("due_month"), 1, 12, BAD_MONTH)
        # A month gone by this year would be neither next nor missed: refused, unless an edit leaves the date as it was.
        if f["due_year"] == today.year and f["due_month"] < today.month and (f["due_year"], f["due_month"]) != was:
            raise SetAsideError(PAST_MONTH)
    account_id = body.get("account_id")
    f["account_id"] = None if account_id is None else _int(account_id, 1, 2**31, BAD_ACCOUNT)
    payee_key = body.get("payee_key")
    if payee_key is not None and (not isinstance(payee_key, str) or not 1 <= len(payee_key) <= 200):
        raise SetAsideError(NOT_UNDERSTOOD)
    f["payee_key"] = payee_key
    category = body.get("category")
    if category is not None and (category not in CATEGORIES or category in NEVER_SPENDING):
        raise SetAsideError(BAD_CATEGORY)
    f["category"] = category
    est = body.get("estimate")
    if est is not None:
        if not isinstance(est, dict) or est.get("item") not in ITEMS:
            raise SetAsideError(BAD_ITEM)
        if kind != "one_off":
            raise SetAsideError(ONLY_ONE_OFF_ESTIMATES)
        f["estimate"] = {"item": est["item"], "installed_year": est.get("installed_year"), "model_year": est.get("model_year"),
                         "miles": est.get("miles")}
    else:
        f["estimate"] = None
    notes = body.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 500):
        raise SetAsideError(BAD_NOTES)
    f["notes"] = notes.strip() if notes else None
    return f


def preview(body, today: date, db: Session | None = None, sa: SetAside | None = None) -> dict:
    """POST /estimate: any draft, worked out by the same rules the write will use and nothing written. A draft of
    just estimate inputs (flat, or under "estimate") answers the estimate; with a kind it answers the draft's monthly
    amount, first month, next due date and the months it is spread over, and whether the ESTIMATE tag would stay.
    With `sa` (an edit) the draft is that set-aside's: fields not sent keep their value, and its first month, added
    date and matches count, so the next due date, months and should-be are the real ones."""
    if not isinstance(body, dict):
        raise SetAsideError(NOT_UNDERSTOOD)
    given = body["estimate"] if isinstance(body.get("estimate"), dict) else body
    item, kind = given.get("item"), body.get("kind", sa.kind if sa is not None else None)
    first = sa.first_month if sa is not None else first_month_after(today)
    e = None
    if item is not None and kind in (None, "one_off") and not (item == "other" and kind == "one_off"):
        try:
            e = estimate(str(item), today, installed_year=given.get("installed_year"), model_year=given.get("model_year"),
                         miles=given.get("miles"), first_month=first)
        except EstimateError as err:
            raise SetAsideError(str(err)) from None
    if kind is None:
        if e is None:
            raise SetAsideError(BAD_KIND)
        return {**e, "is_estimate": True, "next_due": date(e["planned_year"], 12, 1).isoformat()}
    draft = body if sa is not None else {**body, "name": "Draft"}       # the name is no part of the arithmetic
    if e is not None:
        draft = dict(draft)
        for key, value in (("amount_cents", e["amount_cents"]), ("due_year", e["planned_year"]), ("due_month", 12)):
            if draft.get(key) is None:
                draft[key] = value
    f = parse_body(draft, today, current=sa)
    d = SetAside(kind=f["kind"], amount_cents=f["amount_cents"], due_month=f["due_month"], due_day=f["due_day"],
                 second_month=f["second_month"], second_day=f["second_day"], due_year=f["due_year"], first_month=first,
                 created_at=sa.created_at if sa is not None else datetime.combine(today, time.min, tzinfo=clock.household_tz()))
    rows = matches_of(db, [sa.id])[sa.id] if sa is not None else []
    nd = next_due(d, today, settled_dues(rows))
    stored = estimate_of(sa) if sa is not None and e is None and d.kind == "one_off" else None
    out = {**(e or {}), "kind": d.kind, "amount_cents": d.amount_cents, "monthly_cents": monthly_cents(d),
           "yearly_cents": yearly_cents(d), "first_month": first.isoformat(), "next_due": _iso(nd),
           "months": None if nd is None else months_through(first, nd.year, nd.month)}
    if sa is not None:
        paid = d.kind == "one_off" and any(m.how in MATCHED_HOWS for m in rows)
        out["should_cents"] = 0 if paid else should_be_cents(d, today, counted_from(db, rows))
    if e is not None:
        out.update(due_year=f["due_year"], due_month=f["due_month"],
                   is_estimate=f["due_year"] == e["planned_year"] and f["amount_cents"] == e["amount_cents"])
    elif stored is not None:          # the stored basis, judged the way edit judges it
        out.update(estimate=stored, is_estimate=not stored.get("confirmed", False) and f["due_year"] == stored["planned_year"]
                   and f["amount_cents"] == stored["replacement_cents"] - stored["sale_cents"])
    return out


def _check_account(db: Session, account_id: int | None) -> None:
    if account_id is None:
        return
    a = db.get(Account, account_id)
    if a is None or not a.is_active or a.type not in CASH_TYPES:
        raise SetAsideError(BAD_ACCOUNT)


def _estimate_text(f: dict, today: date, first_month: date) -> str | None:
    """Recompute the basis from the inputs (engineering choice 11); confirmed when the person's year or amount differ."""
    if f["estimate"] is None or f["estimate"]["item"] == "other":
        return None
    try:
        e = estimate(f["estimate"]["item"], today, installed_year=f["estimate"]["installed_year"],
                     model_year=f["estimate"]["model_year"], miles=f["estimate"]["miles"], first_month=first_month)
    except EstimateError as err:
        raise SetAsideError(str(err)) from None
    stored = json.loads(estimate_json(e))
    stored["confirmed"] = f["due_year"] != e["planned_year"] or f["amount_cents"] != e["amount_cents"]
    return json.dumps(stored)


def _apply(sa: SetAside, f: dict) -> None:
    for key in ("name", "kind", "amount_cents", "due_month", "due_day", "second_month", "second_day", "due_year",
                "account_id", "payee_key", "category", "notes"):
        setattr(sa, key, f[key])


def _matched_note(made: list) -> str:
    """The one event line folds in what matching found (one event per write)."""
    return f"; matched {len(made)} payment{'s' if len(made) != 1 else ''}" if made else ""


def add(db: Session, f: dict, *, user_id: int, who: str, today: date, at: datetime) -> SetAside:
    _check_account(db, f["account_id"])
    sa = SetAside(first_month=first_month_after(today), created_at=at, updated_at=at, updated_by=user_id)
    _apply(sa, f)
    sa.estimate = _estimate_text(f, today, sa.first_month)
    db.add(sa)
    db.flush()
    made = match_set_aside(db, sa, today, by=user_id)
    log_event(db, "info", "setaside", f"{who} added {describe(sa)}{_matched_note(made)}")
    return sa


MAX_MANY = 50
TOO_MANY = "Set aside up to 50 at a time."


def add_many(db: Session, fs: list[dict], *, user_id: int, who: str, today: date, at: datetime) -> list[SetAside]:
    """POST /setasides/many (P26): parse_body's fields for each, all made, then matched (only these: Engineering
    choice 16), with one event line. The caller wraps it in one Undo and commits; a refusal raises SetAsideError and
    the caller rolls back, so nothing is made."""
    for f in fs:
        _check_account(db, f["account_id"])
    made = []
    for f in fs:
        sa = SetAside(first_month=first_month_after(today), created_at=at, updated_at=at, updated_by=user_id)
        _apply(sa, f)
        sa.estimate = _estimate_text(f, today, sa.first_month)
        db.add(sa)
        made.append(sa)
    db.flush()
    matched = [m for sa in made for m in match_set_aside(db, sa, today, by=user_id)]
    log_event(db, "info", "setaside",
              f"{who} set aside {len(made)}: {'; '.join(describe(s) for s in made)}{_matched_note(matched)}")
    return made


def _changes(old: dict, sa: SetAside) -> list[str]:
    out = []
    if old["name"] != sa.name:
        out.append(f"name {old['name']} → {sa.name}")
    if old["amount_cents"] != sa.amount_cents:
        out.append(f"amount {dollars_text(old['amount_cents'])} → {dollars_text(sa.amount_cents)}")
    if old["kind"] != sa.kind:
        out.append(f"kind {old['kind']} → {sa.kind}")
    if (old["due_month"], old["due_day"], old["second_month"], old["second_day"], old["due_year"]) != (
            sa.due_month, sa.due_day, sa.second_month, sa.second_day, sa.due_year):
        out.append("the due dates")
    if old["account_id"] != sa.account_id:
        out.append("the account")
    if (old["payee_key"], old["category"]) != (sa.payee_key, sa.category):
        out.append("what it matches")
    if old["notes"] != sa.notes:
        out.append("the notes")
    return out


def edit(db: Session, sa: SetAside, f: dict, *, user_id: int, who: str, today: date, at: datetime) -> SetAside:
    """PUT (f is parse_body(..., current=sa), so fields not sent are unchanged): the estimate's basis kept (and
    recomputed when new inputs come), confirmed when the year or amount move away from it; the account does not
    confirm it. Then matching runs again for it; one event line covers the change and what matched."""
    if f["account_id"] != sa.account_id:
        _check_account(db, f["account_id"])
    old = {k: getattr(sa, k) for k in (*COMMON_FIELDS, *DATE_FIELDS)}
    _apply(sa, f)
    if f["estimate"] is not None:
        sa.estimate = _estimate_text(f, today, sa.first_month)
    elif sa.estimate:
        e = json.loads(sa.estimate)
        if sa.kind != "one_off":
            sa.estimate = None
        elif sa.due_year != e["planned_year"] or sa.amount_cents != e["replacement_cents"] - e["sale_cents"]:
            e["confirmed"] = True
            sa.estimate = json.dumps(e)
    sa.updated_at, sa.updated_by = at, user_id
    db.flush()
    changes = _changes(old, sa)
    made = match_set_aside(db, sa, today, by=user_id)
    if changes or made:
        log_event(db, "info", "setaside",
                  f"{who} changed {sa.name}{': ' + ', '.join(changes) if changes else ''}{_matched_note(made)}")
    return sa


def archive(db: Session, sa: SetAside, *, user_id: int, who: str, at: datetime) -> None:
    sa.archived_at, sa.updated_at, sa.updated_by = at, at, user_id
    db.flush()
    log_event(db, "info", "setaside", f"{who} stopped setting aside {sa.name}")


def replace(db: Session, sa: SetAside, *, user_id: int, who: str, today: date, at: datetime) -> SetAside:
    """Decision 4, "Start": a new one-off from the same estimate type, installed the year it was paid, for what it
    cost this time (the matched payment's amount, no sale value); the paid one is archived."""
    st = standings(db, today, [sa])[sa.id]
    offer = replace_out(db, sa, st, today)
    if offer is None or offer["next"] is None:
        raise SetAsideError("Only a paid one-off with an estimate can start the next one.")
    nxt = offer["next"]
    new = SetAside(name=sa.name, kind="one_off", amount_cents=offer["paid_cents"], due_year=nxt["planned_year"], due_month=12,
                   first_month=first_month_after(today), account_id=sa.account_id, payee_key=sa.payee_key,
                   category=sa.category, notes=sa.notes, estimate=estimate_json(nxt), created_at=at, updated_at=at,
                   updated_by=user_id)
    db.add(new)
    sa.archived_at, sa.updated_at, sa.updated_by = at, at, user_id
    db.flush()
    log_event(db, "info", "setaside", f"{who} started the next {new.name}, {dollars_text(new.amount_cents)} about {new.due_year}")
    return new


def last_change(db: Session) -> tuple[datetime | None, int | None]:
    """When set-asides last changed and by whom (the Plan's "Last updated" line)."""
    row = db.execute(select(SetAside.updated_at, SetAside.updated_by).order_by(SetAside.updated_at.desc(), SetAside.id.desc()).limit(1)).first()
    return (row[0], row[1]) if row else (None, None)


# ---- Spending's section (spec, Spending (changes to 11b); decision 10; engineering choices 7 and 8) ----

def matched_in_month(db: Session, month: date, end: date) -> list[dict]:
    """The payments matched to a set-aside posted in [month, end): "Paid from Setting aside". Archived set-asides keep theirs."""
    q = (select(SetAsideMatch, SetAside.name, Transaction, Account.name, -personal_amount(), SetAside.archived_at)
         .join(SetAside, SetAside.id == SetAsideMatch.set_aside_id)
         .join(Transaction, Transaction.id == SetAsideMatch.transaction_id)
         .join(Account, Account.id == Transaction.account_id)
         .where(SetAsideMatch.how.in_(MATCHED_HOWS), Transaction.posted_at >= month, Transaction.posted_at < end, *personal_clauses(),
                Transaction.category != "transfer")
         .order_by(Transaction.posted_at, Transaction.id))
    return [{"set_aside_id": m.set_aside_id, "name": name, "transaction_id": t.id,
             "payee": t.merchant or payee(t.raw_description, t.merchant).name, "posted_at": t.posted_at.isoformat(),
             "cents": int(cents), "late": m.late, "account_name": account_name, "category": t.category,
             "archived": archived_at is not None}
            for m, name, t, account_name, cents, archived_at in db.execute(q)]


def _paid_months(db: Session) -> dict[int, date]:
    """The month each one-off's matched payment was posted in (the first, if there are several)."""
    q = (select(SetAsideMatch.set_aside_id, func.min(Transaction.posted_at))
         .join(Transaction, Transaction.id == SetAsideMatch.transaction_id)
         .where(SetAsideMatch.how.in_(MATCHED_HOWS)).group_by(SetAsideMatch.set_aside_id))
    return {i: d.replace(day=1) for i, d in db.execute(q)}


def _live_in(sa: SetAside, month: date, end: date, paid_month: date | None) -> bool:
    """Counted in this month (engineering choices 8 and 18): added in or before it (its created month; first_month is
    only for should-be and the one-off divisor), not archived by the month's end (the month it is archived in does
    not count), and for a one-off neither past its due month nor past the month it was paid in."""
    if added_on(sa).replace(day=1) > month or (sa.archived_at is not None and local_day(sa.archived_at) < end):
        return False
    if sa.kind != "one_off":
        return True
    return date(sa.due_year, sa.due_month, 1) >= month and (paid_month is None or paid_month >= month)


def month_section(db: Session, today: date, month: date, end: date) -> dict | None:
    """GET /spending's set_aside (spec, The month payload): the set-asides live in the month and the payments matched
    in it; None when there is neither. States and "needs a look" are today's, so only the current month has them."""
    paid_months = _paid_months(db)
    live_in = [s for s in db.scalars(select(SetAside).order_by(SetAside.id)) if _live_in(s, month, end, paid_months.get(s.id))]
    paid = matched_in_month(db, month, end)
    if not live_in and not paid:
        return None
    current = month == today.replace(day=1)
    live = [s for s in live_in if s.archived_at is None]
    rows: list[dict] = []
    if current and live:
        st = standings(db, today, live)
        rows = [row_out(db, s, st[s.id], today) for s in sorted(live, key=lambda s: _order(s, st[s.id]))]
    names = [r["name"] for r in rows] if current else [s.name for s in live_in]
    nxt = next((r for r in rows if r["next_due"] is not None), None)
    return {"monthly_cents": sum(monthly_cents(s) for s in live_in), "count": len(live_in),
            "yearly_cents": sum(yearly_cents(s) for s in live_in),
            "one_off_cents": sum(s.amount_cents for s in live_in if s.kind == "one_off"), "names": names[:3],
            "needs_look": [r for r in rows if r["state"] in NEEDS_LOOK], "paid": paid,
            "next": {"name": nxt["name"], "next_due": nxt["next_due"]} if nxt else None}


# ---- The Plan (spec, The Plan; decisions 9, 17 and D; engineering choice 10) ----

def _unpaid_one_offs(db: Session) -> list[SetAside]:
    paid = select(SetAsideMatch.set_aside_id).where(SetAsideMatch.how.in_(MATCHED_HOWS))
    return list(db.scalars(select(SetAside).where(SetAside.kind == "one_off", SetAside.archived_at.is_(None),
                                                  SetAside.id.not_in(paid)).order_by(SetAside.due_year, SetAside.id)))


def one_off_costs(db: Session, plan_year: int) -> tuple[OneOffCost, ...]:
    """Household.one_off_costs: the active, unpaid one-offs, summed by year. An overdue one (due before the plan
    year, still unpaid) is still coming, so it counts in the plan year."""
    by_year: dict[int, int] = {}
    for s in _unpaid_one_offs(db):
        y = max(s.due_year, plan_year)
        by_year[y] = by_year.get(y, 0) + s.amount_cents
    return tuple(OneOffCost(y, c) for y, c in sorted(by_year.items()))


def plan_one_offs(db: Session, plan_year: int) -> list[dict]:
    """The Plan page's "Big costs ahead" rows. `year` is the year the engine pays it (the plan year for an overdue
    one); `due_year` is when it was due and `overdue` says the two differ."""
    return [{"id": s.id, "name": s.name, "year": max(s.due_year, plan_year), "due_year": s.due_year, "due_month": s.due_month, "overdue": s.due_year < plan_year,
             "cents": s.amount_cents, "monthly_cents": monthly_cents(s), "is_estimate": is_estimate(s)}
            for s in _unpaid_one_offs(db)]


def history_ids(db: Session) -> tuple[list[int], list[int]]:
    """For derive_flows: Taxes payments matched to a yearly or twice-yearly set-aside that are not income tax (kept
    in the spending history, decision 9), and payments matched to a one-off (left out, decision 17), archived or not."""
    q = (select(SetAsideMatch.transaction_id, SetAside.kind, Transaction.raw_description, Transaction.category)
         .join(SetAside, SetAside.id == SetAsideMatch.set_aside_id)
         .join(Transaction, Transaction.id == SetAsideMatch.transaction_id)
         .where(SetAsideMatch.how.in_(MATCHED_HOWS)))
    kept, one_off = [], []
    for tid, kind, raw, category in db.execute(q):
        if kind == "one_off":
            one_off.append(tid)
        elif category == "taxes" and not INCOME_TAX.search(tidy(raw)):
            kept.append(tid)
    return kept, one_off
