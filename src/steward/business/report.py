"""The Business view (spec 5; rulings 7-10): year-to-date income, expenses by Schedule C line, profit, and the
expected full-year range. Business rows are transactions with a business share that aren't transfers; each counts
its share. Meals count at the table's share; the car is miles × rate or its charges; the home office is computed and
never makes a loss."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.business.lines import EXPENSE_LINES, LINE_BY_KEY, LINES, line_for
from steward.business.rules_table import BusinessRules, business_rules
from steward.business.settings import HomeOffice, expect_for, miles_for, read_settings
from steward.business.tagging import share
from steward.db.models import Account, Transaction


@dataclass(frozen=True)
class LineTotal:
    key: str
    number: str
    label: str
    spent_cents: int        # what the rows' shares add up to: money in for income, costs (positive) otherwise
    counts_cents: int       # what counts on Schedule C
    count: int              # rows on the line
    note: str | None


@dataclass(frozen=True)
class ProfitRange:
    """Schedule C profit (after the home office and mileage), for tax, and cash profit (income less what the business
    paid out, meals in full and car charges counted), for the plan's cash (final review ruling I3)."""
    year: int
    ytd_cents: int
    low_cents: int
    high_cents: int
    entered: bool
    cash_ytd_cents: int = 0
    cash_low_cents: int = 0
    cash_high_cents: int = 0
    ask_expect: bool = False    # January with no range yet: year to date is only weeks of profit (final review M1)

    @property
    def mid_cents(self) -> int:
        return (self.low_cents + self.high_cents) // 2

    @property
    def cash_mid_cents(self) -> int:
        return (self.cash_low_cents + self.cash_high_cents) // 2


@dataclass(frozen=True)
class Report:
    year: int
    through: date
    type: str
    income_cents: int
    expenses_cents: int
    profit_cents: int
    lines: tuple[LineTotal, ...]
    range: ProfitRange
    left_out: int
    using_note: str | None
    home_office_limited: bool


def _through(year: int, today: date) -> date:
    return today if year == today.year else date(year, 12, 31)


def _rows(db: Session, year: int, through: date) -> list[tuple[Transaction, str]]:
    return [(t, n) for t, n in db.execute(
        select(Transaction, Account.name).join(Account, Account.id == Transaction.account_id)
        .where(Transaction.business_pct > 0, Transaction.is_transfer.is_(False),
               Transaction.posted_at >= date(year, 1, 1), Transaction.posted_at <= through)
        .order_by(Transaction.posted_at.desc(), Transaction.id.desc())).all()]


def home_office_full(ho: HomeOffice, rules: BusinessRules) -> int:
    if ho.method == "simplified":
        return min(ho.office_sqft, rules.home_office_max_sqft) * rules.home_office_rate_cents
    if ho.method == "actual" and ho.home_sqft > 0:
        return ho.home_costs_cents * ho.office_sqft // ho.home_sqft
    return 0


def _home_office_note(ho: HomeOffice, rules: BusinessRules) -> str:
    if ho.method == "simplified":
        sq = min(ho.office_sqft, rules.home_office_max_sqft)
        return (f"{sq:,} sq ft at ${rules.home_office_rate_cents / 100:g} a square foot, up to "
                f"{rules.home_office_max_sqft} ({rules.year} rules).")
    return f"{round(100 * ho.office_sqft / ho.home_sqft)}% of the home's yearly costs."


def business_report(db: Session, year: int, today: date) -> Report:
    through = _through(year, today)
    months = through.month if year == today.year else 12
    rules = business_rules(year)
    s = read_settings(db, year)
    spent: dict[str, int] = defaultdict(int)
    count: dict[str, int] = defaultdict(int)
    left_out = 0
    for t, _ in _rows(db, year, through):
        line = line_for(t.category, t.amount_cents, t.business_line)
        if line is None:
            left_out += 1
            continue
        part = share(t.amount_cents, t.business_pct)
        spent[line] += part if line == "income" else -part
        count[line] += 1
    out: list[LineTotal] = []
    income = spent["income"]
    if count["income"]:
        out.append(LineTotal("income", "1", "Income", income, income, count["income"], None))
    costs = 0
    for key in EXPENSE_LINES:
        if key == "home_office":
            continue
        line = LINE_BY_KEY[key]
        sp, counts, note = spent[key], spent[key], None
        if key == "meals" and count[key]:
            counts = share(sp, rules.meals_pct)
            note = f"Half of business meals counts ({rules.year} rules)." if rules.meals_pct == 50 else \
                f"{rules.meals_pct}% of business meals counts ({rules.year} rules)."
        if key == "car" and s.car_method == "standard":
            miles = miles_for(db, year, len(rules.mileage))
            counts = sum(m * p.tenths_of_cent for m, p in zip(miles, rules.mileage)) // 10
            total = sum(miles)
            note = (f"{total:,} business miles at the IRS rates ({rules.year} rules); car charges aren't counted."
                    if total else "Add business miles in Settings, Business.")
            if not count[key] and not total:
                continue
        elif not count[key]:
            continue
        costs += counts
        out.append(LineTotal(key, line.number, line.label, sp, counts, count[key], note))
    before_ho = income - costs
    ho_full = home_office_full(s.home_office, rules)
    limited = False
    ho_counts = 0
    if ho_full > 0:
        ho_ytd = ho_full * months // 12
        ho_counts = min(ho_ytd, max(0, before_ho))
        limited = ho_counts < ho_ytd
        note = _home_office_note(s.home_office, rules)
        if limited:
            note += " Limited to profit before the home office."
        out.append(LineTotal("home_office", "30", "Home office", ho_ytd, ho_counts, 0, note))
    expenses = costs + ho_counts
    profit = income - expenses
    cash = income - sum(spent[k] for k in EXPENSE_LINES if k != "home_office")
    e = expect_for(db, year) if year == today.year else None
    if e is not None:
        def full(rest: int) -> int:
            b = before_ho + rest
            return b - min(ho_full, max(0, b))
        rng = ProfitRange(year, profit, full(e.low_cents), full(e.high_cents), True,
                          cash, cash + e.low_cents, cash + e.high_cents)
    else:
        rng = ProfitRange(year, profit, profit, profit, False, cash, cash, cash,
                          ask_expect=year == today.year and today.month == 1)
    order = {l.key: i for i, l in enumerate(LINES)}
    out.sort(key=lambda l: order[l.key])
    return Report(year, through, s.type, income, expenses, profit, tuple(out), rng, left_out, rules.using_note,
                  limited)


def profit_range(db: Session, year: int, today: date) -> ProfitRange:
    """The year's business profit as a range (D7), for the plan and part 1's projection."""
    return business_report(db, year, today).range


def line_rows(db: Session, year: int, line: str, today: date) -> list[tuple[Transaction, str, int]]:
    if line == "home_office":
        return []
    return [(t, n, share(t.amount_cents, t.business_pct)) for t, n in _rows(db, year, _through(year, today))
            if line_for(t.category, t.amount_cents, t.business_line) == line]


def range_out(p: ProfitRange) -> dict:
    return {"year": p.year, "ytd_cents": p.ytd_cents, "low_cents": p.low_cents, "high_cents": p.high_cents,
            "mid_cents": p.mid_cents, "entered": p.entered, "cash_ytd_cents": p.cash_ytd_cents,
            "cash_low_cents": p.cash_low_cents, "cash_high_cents": p.cash_high_cents,
            "cash_mid_cents": p.cash_mid_cents, "ask_expect": p.ask_expect}


def report_out(r: Report, this_year: int) -> dict:
    return {"year": r.year, "this_year": this_year, "through": r.through.isoformat(), "type": r.type, "income_cents": r.income_cents,
            "expenses_cents": r.expenses_cents, "profit_cents": r.profit_cents,
            "lines": [{"key": l.key, "number": l.number, "label": l.label, "spent_cents": l.spent_cents,
                       "counts_cents": l.counts_cents, "count": l.count, "note": l.note} for l in r.lines],
            "range": range_out(r.range), "left_out": r.left_out, "using_note": r.using_note,
            "home_office_limited": r.home_office_limited}
