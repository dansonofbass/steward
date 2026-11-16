"""Spending (phase 11b spec, "What counts as spending"): one definition, used by Spending, Home's line, Over time and
the category page. The cash-flow base stays (vault_flows: checking, savings, credit and the business accounts; paired
transfers out; only a row's personal share). On top: rows categorized transfer are out too, refunds net against their
own category (never below $0), and every category has a kind. Integer cents throughout; months are calendar months and
`today` is the household's day (deps.today())."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median_low
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from steward.db.models import CATEGORIES, SPENDING_KINDS, Account, Fact, SetAsideMatch, SpendingTarget, Transaction
from steward.events import log_event
from steward.services import setasides as sas
from steward.services.vault_flows import (first_complete_month, month_add, personal_amount, personal_clauses,
                                          settlements_by_month)

KINDS: tuple[str, ...] = SPENDING_KINDS
INCOME_CATEGORIES: tuple[str, ...] = ("income", "business_income", "interest")
UNSORTED = "uncategorized"
# P2: Bills, Commitments and Once in a while; everything else is Flexible (stored "everyday"). There is no phone
# category (phone bills sort to Utilities); saving and set-asides aren't spending categories.
_FIXED = ("housing", "utilities", "insurance", "subscriptions", "loan_payments")
_COMMITMENT = ("giving", "childcare_education", "kids")
_OCCASIONAL = ("taxes",)
_NEVER_SPENDING = (*INCOME_CATEGORIES, "transfer", "investment", "reimbursement", UNSORTED)
DEFAULT_KINDS: dict[str, str] = {
    c: "fixed" if c in _FIXED else "commitment" if c in _COMMITMENT else "occasional" if c in _OCCASIONAL
    else "everyday"
    for c in CATEGORIES if c not in _NEVER_SPENDING}
SPENDING_CATEGORIES: tuple[str, ...] = tuple(DEFAULT_KINDS)
# The web's lib/categories.ts labels, for event_log lines.
LABELS: dict[str, str] = {
    "groceries": "Groceries", "dining": "Eating out", "housing": "Housing", "utilities": "Utilities",
    "transport": "Getting around", "travel": "Travel", "health": "Health", "insurance": "Insurance",
    "childcare_education": "Childcare and school", "giving": "Giving", "subscriptions": "Subscriptions",
    "shopping": "Shopping", "personal": "Personal", "kids": "Kids", "home": "Home and garden", "gifts": "Gifts",
    "entertainment": "Fun", "business_expense": "Business expense", "taxes": "Taxes", "fees": "Fees",
    "loan_payments": "Loan payments", "pets": "Pets", "cash_atm": "Cash and ATM",
}
TYPICAL_MONTHS = 6
WATCHED: tuple[str, ...] = ("fixed", "commitment")   # Bills and Commitments: watched as fixed costs, never as targets
LATE_DAYS = 5                       # P7: "Not seen yet" from usual day + 5, capped at the month's last day
EXPECTED_PAID = 4                   # P4: expected this month when paid in 4 of the last 6 window months
DIFFER_MIN_CENTS = 2500             # decision 1: different from usual is a gap of at least $25
DIFFER_MIN_BP = 1000                # and at least 10% of usual
GIVING_OUTSIDE_KEY = "giving.outside_cents"   # P13: a monthly amount, shown on Giving's row only
OVER_ON_CENTS = 500                 # decision 2: over by less than $5 is on target
OVER_LITTLE_CENTS = 2500            # a little over: by $25 or less, or by 10% or less; clearly over is beyond both
EARLY_DAYS = 7                      # on days 1-7 of the current month only clearly over shows
CHECK_MISSED = 4                    # the monthly target check: missed in at least 4 of the last 6 window months
KEEP_MONTHS = 3                     # Keep hides the check for 3 months (P19)


@dataclass(frozen=True)
class Flow:
    in_cents: int       # money in, personal share
    out_cents: int      # money out, personal share, as a positive number
    out_rows: int       # rows of money out


@dataclass(frozen=True)
class Setting:
    kind: str
    monthly_cents: int | None


def ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def first_of(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


MATCHED_HOWS: tuple[str, ...] = ("auto", "hand")


def matched_ids():
    """Payments matched to a set-aside (phase 11c, decision 16): out of every category figure, still in money out."""
    return select(SetAsideMatch.transaction_id).where(SetAsideMatch.how.in_(MATCHED_HOWS), SetAsideMatch.transaction_id.is_not(None))


def spending_clauses(*, with_matched: bool = False) -> tuple:
    """vault_flows' personal rows, less the rows only categorized as a transfer (a card payment the feed didn't pair)
    and, unless asked for, less the payments matched to a set-aside (engineering choice 9)."""
    base = (*personal_clauses(), Transaction.category != "transfer")
    return base if with_matched else (*base, Transaction.id.not_in(matched_ids()))


def _month():
    return func.strftime("%Y-%m", Transaction.posted_at)


def category_months(db: Session, start: date, end: date, *, with_matched: bool = False) -> dict[str, dict[str, Flow]]:
    """Money in and out by month and category over [start, end), in one grouped query, plus each settled leftover as
    money out in its category and month (reimbursable spec, rule 2; a settlement is not a row, so out_rows stays)."""
    month = _month()
    pa = personal_amount()
    rows = db.execute(
        select(month, Transaction.category,
               func.coalesce(func.sum(case((Transaction.amount_cents > 0, pa), else_=0)), 0),
               func.coalesce(func.sum(case((Transaction.amount_cents < 0, -pa), else_=0)), 0),
               func.count(case((Transaction.amount_cents < 0, 1))))
        .join(Account, Account.id == Transaction.account_id)
        .where(Transaction.posted_at >= start, Transaction.posted_at < end, *spending_clauses(with_matched=with_matched))
        .group_by(month, Transaction.category)).all()
    out: dict[str, dict[str, Flow]] = {}
    for m, category, money_in, money_out, n_out in rows:
        out.setdefault(m, {})[category] = Flow(int(money_in), int(money_out), int(n_out))
    for m, cats in settlements_by_month(db, start, end).items():
        for category, cents in cats.items():
            f = out.setdefault(m, {}).get(category, Flow(0, 0, 0))
            out[m][category] = Flow(f.in_cents, f.out_cents + cents, f.out_rows)
    return out


def spent(flow: Flow | None) -> int:
    """Money out less refunds, never below zero: a month whose refunds exceed its spending shows $0 spent."""
    return 0 if flow is None else max(0, flow.out_cents - flow.in_cents)


def received(flow: Flow | None) -> int:
    """Money in less money out, never below zero (income categories)."""
    return 0 if flow is None else max(0, flow.in_cents - flow.out_cents)


def earliest_month(db: Session) -> str | None:
    """The first month with any counted row (the month switcher's first month)."""
    e = db.scalar(select(func.min(Transaction.posted_at)).join(Account, Account.id == Transaction.account_id)
                  .where(*spending_clauses(with_matched=True)))      # a matched payment is still history
    return None if e is None else ym(e)


def window_sums(db: Session, today: date, n: int = TYPICAL_MONTHS) -> tuple[list[str], dict[str, dict[str, Flow]]]:
    """The typical month's months (spec, "The typical month"; ruling 1): walking back from the month before today's,
    the last 6 complete months that have any counted row, oldest first; a month without one is skipped and an older
    month taken, so there are fewer only when history runs out. The book starts where vault_flows.counted_start's
    does (its first complete month of personal rows, transfer-category rows included), but with no 12-month cap.
    With their sums. Over time's count takes the last `n` such months instead (6 or 12, the span it draws); the
    typical month's 6 are always that list's last 6."""
    start = first_complete_month(db)
    if start is None:
        return [], {}
    this = today.replace(day=1)
    month = _month()
    recent = db.scalars(
        select(month).join(Account, Account.id == Transaction.account_id)
        .where(Transaction.posted_at >= start, Transaction.posted_at < this, *spending_clauses())
        .group_by(month).order_by(month.desc()).limit(n)).all()
    if not recent:
        return [], {}
    window = sorted(recent)
    return window, category_months(db, first_of(window[0]), this)


def money_out_cents(flows: dict[str, Flow]) -> int:
    """A month's money out (decision 17): every spending category's spending, refunds netted and never below $0,
    whatever its kind (everyday, fixed or paid once in a while), plus Not sorted yet's money out (ruling 16).
    Transfers and income are never in it. Spending's head and Home's strip both take it from here."""
    unsorted = flows.get(UNSORTED)
    return sum(spent(flows.get(c)) for c in SPENDING_CATEGORIES) + (unsorted.out_cents if unsorted else 0)


def income_cents(flows: dict[str, Flow]) -> int:
    """A month's income: each income category's money in less its money out, never below $0."""
    return sum(received(flows.get(c)) for c in INCOME_CATEGORIES)


def past_zero_cents(flows: dict[str, Flow]) -> int:
    """What refunds and credits took spending categories past $0 (a big gift sorted to Gifts, a return bigger than the
    month's shopping). Each category's spending still stops at $0 (spent()), so targets, pace and the typical month
    never see it; only the month's money in does (JR, on #58's "money in past $0 counts nowhere")."""
    return sum(received(flows.get(c)) for c in SPENDING_CATEGORIES)


def money_in_cents(flows: dict[str, Flow]) -> int:
    """A month's money in: income, plus money in past $0 in a spending category. Home's figure and strip, Spending's
    "out · in" line and Ask's cash_flow all take it from here. Not sorted yet's credits stay out (ruling 16)."""
    return income_cents(flows) + past_zero_cents(flows)


def counted_categories(flows: dict[str, Flow]) -> list[dict]:
    """Each category's part of the month's money in and money out, as money_in_cents and money_out_cents count it, so
    the parts add up to them: a spending category's spending and what it went past $0, an income category's income,
    Not sorted yet's money out. Categories that count nowhere (investment, say) are left out. Largest out first."""
    rows = []
    for c, f in flows.items():
        if c in DEFAULT_KINDS:
            in_cents, out_cents = received(f), spent(f)
        elif c in INCOME_CATEGORIES:
            in_cents, out_cents = received(f), 0
        elif c == UNSORTED:
            in_cents, out_cents = 0, f.out_cents
        else:
            continue
        if in_cents or out_cents:
            rows.append({"category": c, "in_cents": in_cents, "out_cents": out_cents})
    return sorted(rows, key=lambda r: (-r["out_cents"], -r["in_cents"], r["category"]))


def flow_months(db: Session, today: date, months: int) -> list[dict]:
    """The last `months` calendar months by Spending's rules, this one last (so far), oldest first, each with its
    counted categories: Home's strip (flow_view) and Ask's cash_flow tool both read it, so neither can disagree with
    Spending's head. A month with nothing in it is $0 both ways."""
    this = today.replace(day=1)
    start = month_add(this, -(months - 1))
    sums = category_months(db, start, month_add(this, 1), with_matched=True)      # matched payments stay: Home reconciles with the bank
    out = []
    for i in range(months):
        m = ym(month_add(start, i))
        flows = sums.get(m, {})
        money_in, money_out = money_in_cents(flows), money_out_cents(flows)
        out.append({"month": m, "in_cents": money_in, "out_cents": money_out, "net_cents": money_in - money_out,
                    "categories": counted_categories(flows)})
    return out


def flow_view(db: Session, today: date, months: int) -> dict:
    """GET /api/spending/flow: Home's "this month so far" strip, by Spending's rules, so its figures and bars agree
    with Spending's month (money out and money in) for every month drawn. Shaped like the old cash-flow rows."""
    return {"as_of": today.isoformat(),
            "months": [{k: r[k] for k in ("month", "in_cents", "out_cents", "net_cents")}
                       for r in flow_months(db, today, months)]}


def typical_cents(values: list[int]) -> int | None:
    """The median, rounded to the nearest $10 (half up); None for no months."""
    if not values:
        return None
    s, n = sorted(values), len(values)
    twice = 2 * s[n // 2] if n % 2 else s[n // 2 - 1] + s[n // 2]
    return (twice + 1000) // 2000 * 1000


def typicals(window: list[str], sums: dict[str, dict[str, Flow]]) -> dict[str, int | None]:
    """Each spending category's typical month; a window month without the category counts as $0."""
    return {c: typical_cents([spent(sums[m].get(c)) for m in window]) for c in SPENDING_CATEGORIES}


def typical_income(window: list[str], sums: dict[str, dict[str, Flow]]) -> int | None:
    return typical_cents([sum(received(sums[m].get(c)) for c in INCOME_CATEGORIES) for m in window])


def usual_by(target: int, day: int, days: int) -> int:
    """Usual by today on a straight line: target × day ÷ days, to the nearest cent."""
    return (target * day + days // 2) // days


def over_level(spent_cents: int, target_cents: int, day: int | None) -> tuple[int, str]:
    """Decision 2: a Flexible row against its target, by this month's facts only (no pace projection). Returns the
    cents over (never below 0) and on, little or clear. `day` is today's day in the current month, None in a closed
    one: on days 1-7 a little over counts as on target."""
    over = spent_cents - target_cents
    if over < OVER_ON_CENTS:
        level = "on"
    elif over <= OVER_LITTLE_CENTS or over * 10 <= target_cents:
        level = "little"
    else:
        level = "clear"
    if level == "little" and day is not None and day <= EARLY_DAYS:
        level = "on"
    return max(0, over), level


def pace(spent_cents: int, target_cents: int | None, day: int | None, days: int) -> tuple[str, int | None]:
    """A Flexible category's state: over or on track by its over level, none without a target (P17: running ahead
    is gone). Usual by today stays: the bar's today mark is drawn against it."""
    if target_cents is None:
        return "none", None
    usual = None if day is None else usual_by(target_cents, day, days)
    return ("on_track" if over_level(spent_cents, target_cents, day)[1] == "on" else "over"), usual


def suggested_cents(values: list[int]) -> int | None:
    """P21: the 75th percentile of the window's months by nearest rank (sorted, index ceil(0.75 n) - 1, so the 5th of
    6), a month without the category counting as $0, rounded up to $10. None for no months or a $0 result."""
    if not values:
        return None
    s = sorted(values)
    p = s[-(-3 * len(s) // 4) - 1]
    return -(-p // 1000) * 1000 or None


def differs_from_usual(spent_cents: int, usual_cents: int) -> bool:
    """Decision 1: different from usual is a gap of at least $25 and at least 10%, under or over. The one place it
    is worked out: a fixed cost's state, the head and Over time's varying costs use it."""
    gap = abs(spent_cents - usual_cents)
    return gap >= DIFFER_MIN_CENTS and gap * 10_000 >= usual_cents * DIFFER_MIN_BP


def usual_cents(values: list[int]) -> int | None:
    """A Bill's or a Commitment's usual (decision 1): the median of the window months that had a payment (net
    spending above $0), to $10 half up; None when no month had one. The typical month counts a $0 month; usual
    leaves it out, so a twice-yearly premium's usual is the premium."""
    return typical_cents([v for v in values if v > 0])


def usual_of(s: Setting, values: list[int]) -> int | None:
    """A set amount stands in for usual (P5), $0 included."""
    return s.monthly_cents if s.monthly_cents is not None else usual_cents(values)


def is_expected(s: Setting, values: list[int]) -> bool:
    """P4: expected this month when paid in at least 4 of the last 6 window months, or set to more than $0."""
    return sum(1 for v in values if v > 0) >= EXPECTED_PAID or (s.monthly_cents or 0) > 0


def watched_line(s: Setting, values: list[int]) -> int | None:
    """What Over time and Set targets measure a Bill or a Commitment against: a set amount, or its usual when it is
    expected; None when there is nothing to judge it by (ruling 24)."""
    if s.monthly_cents is not None:
        return s.monthly_cents
    return usual_cents(values) if is_expected(s, values) else None


def fixed_state(kind: str, spent_cents: int, usual: int | None, *, expected: bool, paid: bool,
                usual_day: int | None, day: int | None, days: int, new_payee: bool) -> tuple[str, str]:
    """A Bill's or a Commitment's state and tone (spec, The states). `day` is None for a closed month (P6: the
    current month never reads as month end). `paid` is whether any payment came out this month (a payment and a
    bigger credit net to $0 but came out). The tone is one of check (neutral ink), ring (dashed, muted), amber or
    quiet (no icon); only a Bill is ever amber, and a new payee on a Bill stacks amber over the rest (P8)."""
    bill = kind == "fixed"
    if not paid:
        if day is None:
            return "none", "quiet"
        if usual_day is not None and day >= min(usual_day + LATE_DAYS, days):
            return "late", "amber" if bill else "ring"
        return "waiting", "ring"
    if not expected or usual is None or not differs_from_usual(spent_cents, usual):
        state = "as_usual"
    elif spent_cents > usual:
        state = "over"
    else:
        state = "so_far" if day is not None else "under"
    tone = "ring" if state == "so_far" else "amber" if state == "over" and bill else "check"
    if new_payee and bill:
        tone = "amber"
    return state, tone


def giving_outside(db: Session) -> int:
    """P13: what the household gives outside these accounts each month, the latest fact; 0 when none or cleared."""
    v = db.scalar(select(Fact.value).where(Fact.key == GIVING_OUTSIDE_KEY)
                  .order_by(Fact.as_of.desc(), Fact.id.desc()).limit(1))
    return int(v) if v is not None and v.isdigit() else 0


def everyday_order(rows: list[tuple[str, int | None, int | None]]) -> list[str]:
    """Decision 8: by target, largest first; then the untargeted by typical month, largest first; ties and the rest
    in CATEGORIES order. Targeted rows move only when targets change; untargeted rows move when the typical
    month's window rolls on."""
    def key(row: tuple[str, int | None, int | None]):
        c, target, typical = row
        if target is not None:
            return (0, -target, 0, CATEGORIES.index(c))
        return (1, 0, -(typical if typical is not None else -1), CATEGORIES.index(c))
    return [r[0] for r in sorted(rows, key=key)]


def settings(db: Session) -> dict[str, Setting]:
    """Every spending category's kind and target; a category without a row takes its default kind and no target."""
    saved = {t.category: t for t in db.scalars(select(SpendingTarget))}
    return {c: Setting(saved[c].kind, saved[c].monthly_cents) if c in saved else Setting(DEFAULT_KINDS[c], None)
            for c in SPENDING_CATEGORIES}


def has_targets(db: Session) -> bool:
    """Whether any category has a target amount (ruling 11): a row that only changes a kind is not one."""
    return db.scalar(select(func.count()).select_from(SpendingTarget)
                     .where(SpendingTarget.monthly_cents.is_not(None))) > 0


def _rows_out(db: Session, start: date, end: date, categories: list[str]) -> list[tuple[str, date, int, str | None]]:
    """Money-out rows of these categories as (category, posted_at, personal cents, cleaned merchant or None), oldest
    first. The merchant only, never the bank's raw text (ruling 12)."""
    if not categories or start >= end:
        return []
    pa = personal_amount()
    q = (select(Transaction.category, Transaction.posted_at, pa, Transaction.merchant)
         .join(Account, Account.id == Transaction.account_id)
         .where(Transaction.posted_at >= start, Transaction.posted_at < end, Transaction.amount_cents < 0,
                Transaction.category.in_(categories), *spending_clauses())
         .order_by(Transaction.posted_at, Transaction.id))
    return [(c, d, -int(a), name) for c, d, a, name in db.execute(q)]


def _largest(rows: list[tuple[str, date, int, str | None]]):
    """The biggest payment; the earliest of equal ones."""
    return max(rows, key=lambda r: (r[2], -r[1].toordinal())) if rows else None


def _fixed_summary(fixed: list[dict], current: bool) -> str:
    """The head's word on Fixed costs (P10): still to come this month, more than usual (Bills over the threshold
    only), or the plain figure. "Less than expected" is gone."""
    if not fixed:
        return "none"
    if current and any(r["state"] in ("waiting", "late") for r in fixed):
        return "to_come"
    if any(r["kind"] == "fixed" and r["state"] == "over" for r in fixed):
        return "more"
    return "plain"


_UNREAD: Any = object()


def flexible_rows(st: dict[str, Setting], flows: dict[str, Flow], typ: dict[str, int | None], day: int | None,
                  days: int) -> list[dict]:
    """A month's Flexible rows in decision 8's order, as Spending shows them; Home's Flexible sign and the verdict read
    the same rows. No query: `flows` is the month's category_months (matched payments out) and `typ` the typical
    months. `day` is today's day in the current month, None in a closed one."""
    shown = [c for c in SPENDING_CATEGORIES if st[c].kind == "everyday"
             and (st[c].monthly_cents is not None or c in flows or (typ[c] or 0) > 0)]
    out = []
    for i, c in enumerate(everyday_order([(c, st[c].monthly_cents, typ[c]) for c in shown])):
        target, s = st[c].monthly_cents, spent(flows.get(c))
        state, usual = pace(s, target, day, days)
        over, level = over_level(s, target, day) if target is not None else (None, None)
        out.append({"category": c, "kind": "everyday", "target_cents": target, "spent_cents": s,
                    "refunds_cents": flows[c].in_cents if c in flows else 0, "usual_by_today_cents": usual,
                    "state": state, "over_cents": over, "over_level": level, "typical_cents": typ[c], "order": i})
    return out


def watched_rows(db: Session, st: dict[str, Setting], month: date, today: date, window: list[str],
                 wsums: dict[str, dict[str, Flow]], flows: dict[str, Flow], *,
                 rows: dict[str, list[tuple[str, date, int, str | None]]] | None = None,
                 outside: int | None = None) -> list[dict]:
    """A month's Bills and Commitments (P4-P11) as Spending's Fixed costs show them, Bills first; Home's Bills sign and
    the verdict read the Bills. `rows` is the money out of these categories from six months before `month` to its
    end, when the caller already read it (month_view reads it with the paid-once-in-a-while categories); otherwise it
    is read here. `outside` (Giving outside these accounts) goes on Giving's row when given."""
    this = today.replace(day=1)
    current = month == this
    days = calendar.monthrange(month.year, month.month)[1]
    day = today.day if current else None
    end = month_add(month, 1)
    watched = [c for c in SPENDING_CATEGORIES if st[c].kind in WATCHED]
    if rows is None:
        rows = {}
        for r in _rows_out(db, month_add(month, -TYPICAL_MONTHS), end, watched):
            rows.setdefault(r[0], []).append(r)
    window_rows: dict[str, list[tuple[str, date, int, str | None]]] = {}
    for r in _rows_out(db, first_of(window[0]), this, watched) if window else []:
        window_rows.setdefault(r[0], []).append(r)
    fixed = []
    for c in watched:
        s = st[c]
        values = [spent(wsums[m].get(c)) for m in window]
        usual, expected = usual_of(s, values), is_expected(s, values)
        here = [r for r in rows.get(c, []) if r[1] >= month]
        if not expected and not here:
            continue                    # P4: not expected and not paid, it doesn't show
        # A Bill's new payee: a cleaned merchant the months before never had (ruling 12); none on a Commitment.
        seen = {r[3] for r in rows.get(c, []) if r[1] < month and r[3] is not None}
        new = None
        if s.kind == "fixed" and expected and seen:
            new = _largest([r for r in here if r[3] is not None and r[3] not in seen])
        sp_ = spent(flows.get(c))
        top = _largest(here)
        paid_days = []
        for m in window:
            big = _largest([r for r in window_rows.get(c, []) if ym(r[1]) == m])
            if big:
                paid_days.append(big[1].day)
        usual_day = median_low(paid_days) if paid_days else None
        state, tone = fixed_state(s.kind, sp_, usual, expected=expected, paid=bool(here), usual_day=usual_day,
                                  day=day, days=days, new_payee=new is not None)
        out = {"category": c, "kind": s.kind, "expected": expected, "expected_cents": usual if expected else None,
               "usual_cents": usual, "spent_cents": sp_, "refunds_cents": flows[c].in_cents if c in flows else 0,
               "state": state, "tone": tone,
               "came_out_on": top[1].isoformat() if top else None, "merchant": top[3] if top else None,
               "typical_day": usual_day, "new_payee": {"name": new[3], "cents": new[2]} if new else None}
        if c == "giving" and outside is not None:
            out["outside_cents"] = outside
        fixed.append(out)
    # P11: Bills first, then Commitments, each by what's expected, largest first, then the list's order.
    fixed.sort(key=lambda r: (r["kind"] != "fixed", -(r["expected_cents"] or 0), CATEGORIES.index(r["category"])))
    return fixed


def month_view(db: Session, today: date, month: date, *, earliest: str | None = _UNREAD) -> dict:
    """GET /api/spending (spec, API). `month` is the first day of today's month or an earlier one. Against the plan:
    everyday (Not sorted yet included) and fixed costs; money out adds the payments made once in a while
    (decision 17). The set-aside share counts as spent and planned (decision 16); matched payments are in money out
    and nowhere else. `earliest` is earliest_month's answer when the caller already has it (the API reads it first to
    refuse a month before history), so it is read once."""
    if earliest is _UNREAD:
        earliest = earliest_month(db)
    this = today.replace(day=1)
    current = month == this
    days = calendar.monthrange(month.year, month.month)[1]
    day = today.day if current else None
    end = month_add(month, 1)
    st = settings(db)
    window, wsums = window_sums(db, today)
    typ = typicals(window, wsums)
    flows = category_months(db, month, end).get(ym(month), {})
    section = sas.month_section(db, today, month, end)      # None before the first set-aside (engineering choice 8)
    monthly = section["monthly_cents"] if section else 0
    paid_cents = sum(p["cents"] for p in section["paid"]) if section else 0
    # Money out and income are Home's strip's figures by construction: matched payments stay in their category's net.
    all_flows = category_months(db, month, end, with_matched=True).get(ym(month), {})

    everyday = flexible_rows(st, flows, typ, day, days)
    # Money out only (ruling 16): uncategorized money in never shrinks it.
    unsorted = flows.get(UNSORTED)
    not_sorted = {"count": unsorted.out_rows if unsorted else 0, "cents": unsorted.out_cents if unsorted else 0}

    watched = [c for c in SPENDING_CATEGORIES if st[c].kind in WATCHED]
    occasional_cats = [c for c in SPENDING_CATEGORIES if st[c].kind == "occasional"]
    rows: dict[str, list[tuple[str, date, int, str | None]]] = {}
    for r in _rows_out(db, month_add(month, -TYPICAL_MONTHS), end, watched + occasional_cats):
        rows.setdefault(r[0], []).append(r)
    fixed = watched_rows(db, st, month, today, window, wsums, flows, rows=rows, outside=giving_outside(db))

    occasional = []
    for c in occasional_cats:
        s = spent(flows.get(c))
        if s == 0:
            continue
        top = _largest([r for r in rows.get(c, []) if r[1] >= month])
        occasional.append({"category": c, "kind": "occasional", "spent_cents": s,
                           "paid_on": top[1].isoformat() if top else None})
    occasional.sort(key=lambda r: (-r["spent_cents"], CATEGORIES.index(r["category"])))
    got = {c: received(flows.get(c)) for c in INCOME_CATEGORIES}
    income = sorted(({"category": c, "cents": cents} for c, cents in got.items() if cents > 0),
                    key=lambda r: (-r["cents"], CATEGORIES.index(r["category"])))

    every_spent = sum(r["spent_cents"] for r in everyday) + not_sorted["cents"]
    every_target = sum(r["target_cents"] or 0 for r in everyday)
    fixed_spent = sum(r["spent_cents"] for r in fixed)
    fixed_expected = sum(r["expected_cents"] or 0 for r in fixed)
    not_yet = sum(1 for r in fixed if r["state"] in ("waiting", "late"))
    more = sum(r["spent_cents"] - r["usual_cents"] for r in fixed if r["kind"] == "fixed" and r["state"] == "over")
    occasional_cents = sum(r["spent_cents"] for r in occasional)
    head = {"spent_cents": every_spent + fixed_spent + monthly, "planned_cents": every_target + fixed_expected + monthly,
            "everyday_spent_cents": every_spent, "everyday_target_cents": every_target,
            "fixed_spent_cents": fixed_spent, "fixed_expected_cents": fixed_expected,
            "fixed_more_cents": more, "fixed_not_yet": not_yet, "fixed_summary": _fixed_summary(fixed, current),
            "occasional_cents": occasional_cents, "money_out_cents": money_out_cents(all_flows),
            "set_aside_cents": monthly, "paid_from_set_aside_cents": paid_cents,
            "income_cents": income_cents(all_flows), "money_in_cents": money_in_cents(all_flows)}
    return {"month": ym(month), "as_of": today.isoformat(), "current": current, "day": day, "days": days,
            "days_left": days - today.day if current else None, "earliest": earliest, "head": head,
            "everyday": everyday, "not_sorted": not_sorted, "fixed": fixed, "occasional": occasional,
            "income": income,
            "has_targets": has_targets(db), "set_aside": section,
            "kinds": {c: st[c].kind for c in SPENDING_CATEGORIES},
            "target_check": _target_check(db, today, window, wsums, typ) if current else None}


def _target_check(db: Session, today: date, window: list[str], wsums: dict[str, dict[str, Flow]],
                  typ: dict[str, int | None]) -> dict | None:
    """P19: the one Flexible target to ask about: below its typical month, spent past it in at least 4 of the last 6
    window months, and not kept (check_after empty or come). The biggest gap between typical and target wins; ties
    go to the list's order."""
    rows = {t.category: t for t in db.scalars(select(SpendingTarget).where(
        SpendingTarget.kind == "everyday", SpendingTarget.monthly_cents.is_not(None)))}
    best: tuple[int, dict] | None = None
    for c in SPENDING_CATEGORIES:
        t = rows.get(c)
        if t is None or typ.get(c) is None or t.monthly_cents >= typ[c]:
            continue
        if t.check_after is not None and t.check_after > today:
            continue
        missed = sum(1 for m in window[-TYPICAL_MONTHS:] if spent(wsums[m].get(c)) > t.monthly_cents)
        if missed < CHECK_MISSED:
            continue
        gap = typ[c] - t.monthly_cents
        if best is None or gap > best[0]:
            best = (gap, {"category": c, "target_cents": t.monthly_cents, "typical_cents": typ[c]})
    return best[1] if best else None


def target_check(db: Session, today: date) -> dict | None:
    """GET /api/spending's target_check, worked out on its own (month_view passes what it already read)."""
    window, wsums = window_sums(db, today)
    return _target_check(db, today, window, wsums, typicals(window, wsums))


def _varies(values: list[int], line: int | None) -> bool:
    """A fixed cost that varies (decision 6): any window month different from its line by decision 1's threshold."""
    return line is not None and any(differs_from_usual(v, line) for v in values)


def _by_line(cats: list[str], line: dict[str, int | None], st: dict[str, Setting]) -> list[str]:
    """Bills, then Commitments, each by their line, largest first, then the list's order (as month_view sorts)."""
    return sorted(cats, key=lambda c: (st[c].kind != "fixed", -(line[c] or 0), CATEGORIES.index(c)))


def _trend(c: str, kind: str, group: str, target: int | None, expected: int | None, typical: int | None,
           series: list[int], over_in: int, over_of: int) -> dict:
    return {"category": c, "kind": kind, "group": group, "target_cents": target, "expected_cents": expected,
            "typical_cents": typical, "spent": series, "over_in": over_in, "over_of": over_of, "order": 0}


def trends_view(db: Session, today: date, months: int) -> dict:
    """GET /api/spending/trends (spec, Pages): each category's last `months` months, this one last (so far), and how
    often it went over today's target in the last `months` complete months that have data (window_sums with n =
    months: "Over in N of the last 12 months" in the 12-month view; this month is never counted, ruling 23; a young
    book counts the months it has). The typical month stays the last 6 of them. Groups in order: everyday, fixed (costs that vary), steady (fixed costs the same every month:
    named, not drawn), occasional (for the category page; not drawn), unjudged (a fixed cost with no window or no
    expectation: ruling 24 makes no claim about it, so Over time leaves it out, but its category page still draws its
    months)."""
    this = today.replace(day=1)
    start = month_add(this, -(months - 1))
    span = [ym(month_add(start, i)) for i in range(months)]
    sums = category_months(db, start, month_add(this, 1))
    # One read for both: the count's months (the last `months` complete months with data) end with the typical
    # month's last 6.
    recent, wsums = window_sums(db, today, max(months, TYPICAL_MONTHS))
    counted, window = recent[-months:], recent[-TYPICAL_MONTHS:]
    typ = typicals(window, wsums)
    st = settings(db)

    def series(c: str) -> list[int]:
        return [spent(sums.get(m, {}).get(c)) for m in span]

    def in_window(c: str) -> list[int]:
        return [spent(wsums[m].get(c)) for m in window]

    def over(c: str, target: int) -> int:
        return sum(1 for m in counted if spent(wsums[m].get(c)) > target)

    groups: dict[str, list[dict]] = {g: [] for g in ("everyday", "fixed", "steady", "unjudged", "occasional")}
    every = [c for c in SPENDING_CATEGORIES if st[c].kind == "everyday"]
    for c in everyday_order([(c, st[c].monthly_cents, typ[c]) for c in every]):
        target, s = st[c].monthly_cents, series(c)
        if target is None and not any(s) and not typ[c]:
            continue
        over_in = 0 if target is None else over(c, target)
        groups["everyday"].append(_trend(c, "everyday", "everyday", target, None, typ[c], s, over_in, len(counted)))
    watched = [c for c in SPENDING_CATEGORIES if st[c].kind in WATCHED]
    line = {c: watched_line(st[c], in_window(c)) for c in watched}       # no window: a set amount or nothing
    for c in _by_line(watched, line, st):
        s = series(c)
        # Nothing to draw against (or a set $0) and nothing in the span: nothing to draw.
        if not line[c] and not any(s):
            continue
        # Ruling 24: with no window or no line there is nothing to judge it by, so it is neither "the same every
        # month" nor varying.
        if not window or line[c] is None:
            group = "unjudged"
        else:
            group = "fixed" if _varies(in_window(c), line[c]) else "steady"
        groups[group].append(_trend(c, st[c].kind, group, st[c].monthly_cents, line[c], typ[c], s, 0, len(counted)))
    for c in SPENDING_CATEGORIES:
        s = series(c)
        if st[c].kind == "occasional" and any(s):
            groups["occasional"].append(_trend(c, "occasional", "occasional", None, None, typ[c], s, 0, len(counted)))
    out = [r for g in groups.values() for r in g]
    for i, r in enumerate(out):
        r["order"] = i
    return {"as_of": today.isoformat(), "months": span, "current": ym(this), "categories": out}


def targets_view(db: Session, today: date) -> dict:
    """GET /api/spending/targets (spec, Pages): every spending category in Spending's order with its typical month,
    the suggestion (the typical month when above $0) and its range over the window. The API names updated_by_id."""
    st = settings(db)
    window, wsums = window_sums(db, today)
    typ = typicals(window, wsums)
    every = everyday_order([(c, st[c].monthly_cents, typ[c]) for c in SPENDING_CATEGORIES if st[c].kind == "everyday"])
    watched = [c for c in SPENDING_CATEGORIES if st[c].kind in WATCHED]
    values = {c: [spent(wsums[m].get(c)) for m in window] for c in SPENDING_CATEGORIES}
    watched = _by_line(watched, {c: watched_line(st[c], values[c]) for c in watched}, st)
    occasional = [c for c in SPENDING_CATEGORIES if st[c].kind == "occasional"]
    categories = []
    for i, c in enumerate([*every, *watched, *occasional]):
        v = values[c]
        categories.append({"category": c, "kind": st[c].kind, "monthly_cents": st[c].monthly_cents,
                           "typical_cents": typ[c], "usual_cents": usual_cents(v), "suggested_cents": suggested_cents(v),
                           "low_cents": min(v) if v else None, "high_cents": max(v) if v else None,
                           "order": i})
    stamps = [(r.updated_at, r.updated_by) for r in db.scalars(select(SpendingTarget))]
    last_at, last_by = max(stamps, key=lambda s: s[0]) if stamps else (None, None)
    kept = [{"category": t.category, "target_cents": t.monthly_cents, "until": t.check_after.isoformat()}
            for t in db.scalars(select(SpendingTarget).where(SpendingTarget.check_after > today)
                                .order_by(SpendingTarget.check_after, SpendingTarget.category))
            if t.monthly_cents is not None]
    return {"as_of": today.isoformat(), "categories": categories, "kept": kept,
            "updated_at": last_at.isoformat() if last_at else None, "updated_by_id": last_by,
            "has_targets": has_targets(db), "typical_income_cents": typical_income(window, wsums)}


class TargetsError(ValueError):
    """A refusal in plain words; PUT /api/spending/targets answers 422 with it."""


NOT_UNDERSTOOD = "That request wasn't understood."
NOT_A_CATEGORY = "That isn't a category Spending tracks."
BAD_KIND = "Choose Bill, Commitment, Flexible or Once in a while."
BAD_CENTS = "Enter a target from $0 to $1,000,000, or leave it blank."
OCCASIONAL_HAS_NO_TARGET = "A category paid once in a while has no target."
LISTED_TWICE = "List each category once."
MAX_TARGET_CENTS = 100_000_000


# Not api/body.py's whole(): that accepts whole floats and raises HTTPException; the service takes ints only and
# raises TargetsError.
def _whole(value, lo: int, hi: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise TargetsError(message)
    return value


def parse_targets(body: dict) -> list[tuple[str, str, int | None]]:
    """PUT /api/spending/targets' body: {"targets": [{category, kind, monthly_cents}]}. A "prefs" key, which older
    pages send, is ignored (P17). monthly_cents 0 is a target of $0 (ruling 21); null or missing is none. Raises
    TargetsError."""
    if not isinstance(body, dict):
        raise TargetsError(NOT_UNDERSTOOD)
    targets = body.get("targets")
    if not isinstance(targets, list):
        raise TargetsError(NOT_UNDERSTOOD)
    out: list[tuple[str, str, int | None]] = []
    seen: set[str] = set()
    for t in targets:
        if not isinstance(t, dict):
            raise TargetsError(NOT_UNDERSTOOD)
        c, kind, cents = t.get("category"), t.get("kind"), t.get("monthly_cents")
        if not isinstance(c, str) or c not in DEFAULT_KINDS:
            raise TargetsError(NOT_A_CATEGORY)
        if c in seen:
            raise TargetsError(LISTED_TWICE)
        seen.add(c)
        if not isinstance(kind, str) or kind not in KINDS:
            raise TargetsError(BAD_KIND)
        if cents is not None:
            cents = _whole(cents, 0, MAX_TARGET_CENTS, BAD_CENTS)
            if kind == "occasional":
                raise TargetsError(OCCASIONAL_HAS_NO_TARGET)
        out.append((c, kind, cents))
    return out


_KIND_WORDS = {"everyday": "flexible", "fixed": "bill", "commitment": "commitment", "occasional": "once in a while"}


def _dollars(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def _amount(s: Setting) -> str:
    if s.monthly_cents is not None:
        return _dollars(s.monthly_cents)
    return "the typical month" if s.kind in WATCHED else "no target"


def _phrase(c: str, old: Setting, new: Setting) -> str:
    """One change as the save bar words it (ruling 4): a kind change with no amount either side names only the
    kind."""
    bits = []
    if old.kind != new.kind:
        bits.append(f"{_KIND_WORDS[old.kind]} → {_KIND_WORDS[new.kind]}")
    if (old.monthly_cents is not None or new.monthly_cents is not None) and _amount(old) != _amount(new):
        bits.append(f"{_amount(old)} → {_amount(new)}")
    return f"{LABELS[c]} {', '.join(bits)}"


def save_targets(db: Session, targets: list[tuple[str, str, int | None]], *, user_id: int, who: str,
                 at: datetime) -> list[str]:
    """Writes what changed, nothing else (so updated_at stays truthful), and one event_log line naming each change
    (spec, Data). A target of 0 is stored as 0, a cleared one as null (ruling 21). A changed row's check_after is
    cleared: any change to a target asks again (P19). Returns the change phrases; with none, writes nothing. The caller
    commits. Takes parse_targets' output and trusts it (no second validation)."""
    st = settings(db)
    changes = []
    for c, kind, cents in targets:
        new = Setting(kind, cents)
        if st[c] == new:
            continue
        row = db.get(SpendingTarget, c)
        if row is None:
            row = SpendingTarget(category=c)
            db.add(row)
        row.kind, row.monthly_cents, row.updated_at, row.updated_by = kind, cents, at, user_id
        row.check_after = None
        changes.append(_phrase(c, st[c], new))
    if changes:
        log_event(db, "info", "spending", f"{who} changed Spending: {'; '.join(changes)}.")
    return changes


def set_kind(db: Session, category: str, kind: str, *, user_id: int, who: str, at: datetime) -> list[str]:
    """The category page's select (P12): one category's kind, saved at once. Its amount stays, except that a
    category paid once in a while has none. Returns the change phrase, as save_targets does; the caller commits."""
    cur = settings(db)[category]
    cents = None if kind == "occasional" else cur.monthly_cents
    return save_targets(db, [(category, kind, cents)], user_id=user_id, who=who, at=at)


TARGET_CHANGED = "That target changed since."
NOT_KEPT = "That target isn't kept."


class TargetChanged(TargetsError):
    """The card's target is no longer the row's: POST …/check answers 409."""


class NotKept(TargetsError):
    """Check again on a target that isn't kept: DELETE …/kept answers 404."""


def check_target(db: Session, today: date, category: str, seen: int) -> tuple[SpendingTarget, int]:
    """The monthly target check's answer is about the target the card showed (`seen`): the row must still hold it.
    Returns the row and the typical month now (what Set writes). Raises TargetsError for a category Spending doesn't
    track, TargetChanged otherwise."""
    if category not in DEFAULT_KINDS:
        raise TargetsError(NOT_A_CATEGORY)
    row = db.get(SpendingTarget, category)
    if row is None or row.kind != "everyday" or row.monthly_cents is None or row.monthly_cents != seen:
        raise TargetChanged(TARGET_CHANGED)
    window, wsums = window_sums(db, today)
    typical = typicals(window, wsums)[category]
    if typical is None:
        raise TargetChanged(TARGET_CHANGED)
    return row, typical


def keep_target(db: Session, row: SpendingTarget, today: date, *, who: str) -> date:
    """Keep (P19): the check leaves this category alone until the first of the month three months on. The target and
    its updated_at stay: nothing about the target changed."""
    row.check_after = month_add(today.replace(day=1), KEEP_MONTHS)
    log_event(db, "info", "spending", f"{who} kept {LABELS[row.category]}'s target at {_dollars(row.monthly_cents)} "
                                      f"until {calendar.month_abbr[row.check_after.month]} {row.check_after.year}.")
    return row.check_after


def check_again(db: Session, category: str, *, who: str) -> None:
    """Kept targets' Check again (P20): clears check_after. Raises NotKept when the category isn't kept."""
    row = db.get(SpendingTarget, category) if category in DEFAULT_KINDS else None
    if row is None or row.check_after is None:
        raise NotKept(NOT_KEPT)
    row.check_after = None
    log_event(db, "info", "spending", f"{who} asked Steward to check {LABELS[category]}'s target again.")
