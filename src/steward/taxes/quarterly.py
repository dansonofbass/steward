"""The Quarterly taxes card and the Home notice (spec 7.1; rulings 2-10). This year's tax at the high end of the
business range, last year's figures from the return, withholding scaled to the full year, payments found in
transactions; the engine's worksheets do the rest. Steward never pays or files anything."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

from sqlalchemy.orm import Session

from steward.engine.tax import annual_tax
from steward.engine.tax import estimates as E
from steward.engine.tax.state import state_name
from steward.taxes import store
from steward.taxes.household import HouseholdTax, household_tax
from steward.taxes.payments import Payment, counted, find_payments

NOTICE_DAYS = 14
AGENCY_SHORT = {"CA": "FTB"}
NO_WITHHOLDING = "Add what your {year} paychecks withheld; until then none of it is counted."
NEVER = "Steward never pays or files anything."


def dollars(cents: int) -> str:
    return f"${round(cents / 100):,}" if cents >= 0 else f"-${round(-cents / 100):,}"


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def long_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def short_date(d: date) -> str:
    return f"{d:%B} {d.day}"


def agency_label(agency: str, state: str) -> str:
    return "Federal (IRS)" if agency == "federal" else f"{state_name(state)} ({AGENCY_SHORT.get(state, 'state')})"


def full_year_withholding(w: store.Withholding | None, year: int) -> tuple[int, int]:
    """Ruling 4: year to date scaled to the whole year. The store keeps the pay date inside the year (final review I1)."""
    if w is None:
        return 0, 0
    days = (w.as_of - date(year, 1, 1)).days + 1
    in_year = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    return round(w.federal_ytd_cents * in_year / days), round(w.state_ytd_cents * in_year / days)


@dataclass(frozen=True)
class NextDue:
    due: date
    federal_cents: int
    state_cents: int


@dataclass(frozen=True)
class Quarterly:
    year: int
    state: str
    hh: HouseholdTax
    federal: E.AgencyPlan
    state_plan: E.AgencyPlan | None
    low_tax_cents: int | None          # federal and state tax at the range's low end, when a range is entered
    prior: store.ReturnFigures | None
    withholding: store.Withholding | None
    needs_withholding: bool
    payments: tuple[Payment, ...]
    next_due: NextDue | None
    rules_note: str
    notes: tuple[str, ...]


def _prior(figs: store.ReturnFigures | None, tax_key: str, agi_key: str) -> E.PriorYear | None:
    if figs is None:
        return None
    tax, agi = getattr(figs, tax_key), getattr(figs, agi_key)
    return None if tax is None or agi is None else E.PriorYear(tax, agi)


def _next_due(plans: tuple[E.AgencyPlan | None, E.AgencyPlan | None], today: date) -> NextDue | None:
    by_date: dict[date, list[int]] = {}
    for i, p in enumerate(plans):
        if p is None:
            continue
        for d in p.dues:
            if d.due >= today:
                by_date.setdefault(d.due, [0, 0])[i] += d.still_due_cents
    for d in sorted(by_date):
        fed, st = by_date[d]
        if fed + st > 0:
            return NextDue(d, fed, st)
    return None


def rules_note(year: int, fed_year: int, state_year: int | None, state: str) -> str:
    if state_year is None or state_year == fed_year:
        return f"{year} tax rules" if fed_year == year else f"Using {fed_year} rules"
    return f"{fed_year} federal and {state_year} {state_name(state)} rules"


def quarterly(db: Session, today: date) -> Quarterly:
    year = E.tax_year_for(today)
    hh = household_tax(db, year, today, point="high")
    state = hh.facts.state
    high = annual_tax(hh.facts, year, marginal=False)
    low_tax = None
    if hh.range is not None and hh.range.entered and hh.range.low_cents != hh.range.high_cents:
        low = annual_tax(replace(hh.facts, business_profit_cents=hh.range.low_cents), year, marginal=False)
        low_tax = max(low.federal_total_cents, 0) + low.state.tax_cents
    prior = store.read_return(db, year - 1)
    w = store.read_withholding(db, year)
    fed_w, st_w = full_year_withholding(w, year)
    pays = tuple(find_payments(db, year, state))
    fed = E.agency_plan("federal", year=year, state=state, current_tax_cents=high.federal_total_cents,
                        current_agi_cents=high.agi_cents, prior=_prior(prior, "federal_tax_cents", "federal_agi_cents"),
                        withholding_cents=fed_w, payments=counted(pays, "federal"))
    assert fed is not None                                 # the federal schedule always exists
    st = None
    if high.state.calculated:
        st = E.agency_plan("state", year=year, state=state, current_tax_cents=high.state.tax_cents,
                           current_agi_cents=high.state.agi_cents,
                           prior=_prior(prior, "state_tax_cents", "state_agi_cents"),
                           withholding_cents=st_w, payments=counted(pays, "state"))
    needs = hh.salary_cents > 0 and w is None
    notes = list(hh.notes)
    if needs:
        notes.append(NO_WITHHOLDING.format(year=year))
    if not high.state.calculated:
        notes.extend(high.state.explain[:1])
    return Quarterly(year, state, hh, fed, st, low_tax, prior, w, needs, pays, _next_due((fed, st), today),
                     rules_note(year, fed.rules_year, st.rules_year if st else None, state), tuple(notes))


def notice(q: Quarterly, today: date) -> NextDue | None:
    """Ruling 10: from 14 days before the next due date through the date itself, while something is still due and
    withholding isn't missing."""
    n = q.next_due
    if n is None or q.needs_withholding:
        return None
    return n if n.due - timedelta(days=NOTICE_DAYS) <= today <= n.due else None


def notice_line(n: NextDue, state: str) -> str:
    parts = []
    if n.federal_cents:
        parts.append(f"{dollars(n.federal_cents)} federal")
    if n.state_cents:
        parts.append(f"{dollars(n.state_cents)} {state_name(state)}")
    return f"Quarterly taxes due {short_date(n.due)}: {' and '.join(parts)}"


def _missing_prior(figs: store.ReturnFigures | None, agency: str, state: str) -> str:
    """Which of last year's figures the safe-harbor comparison is waiting on (final review m1)."""
    tax = getattr(figs, "federal_tax_cents" if agency == "federal" else "state_tax_cents", None)
    if tax is None:
        return "tax"
    return "adjusted gross income" if agency == "federal" else f"{state_name(state)} adjusted gross income"


def method_line(p: E.AgencyPlan, year: int, prior: store.ReturnFigures | None = None, state: str = "") -> str:
    if p.method == "none_needed":
        return f"No estimates needed: this year's tax less withholding is under {dollars(p.minimum_cents)}."
    if p.method == "prior_year":
        return (f"{_pct(p.prior_share)} of {year - 1}'s tax, {dollars(p.required_cents)}: less than 90% of this "
                f"year's ({dollars(p.current_required_cents)}), and it still avoids the penalty.")
    if p.prior_not_allowed:
        return (f"90% of this year's tax, {dollars(p.required_cents)}. At $1,000,000 of California income, last year's "
                "tax can't be used.")
    if p.prior_required_cents is None:
        return (f"90% of this year's tax, {dollars(p.required_cents)}. Add {year - 1}'s "
                f"{_missing_prior(prior, p.agency, state)} to compare with the safe harbor.")
    return (f"90% of this year's tax, {dollars(p.required_cents)}: no more than {_pct(p.prior_share)} of "
            f"{year - 1}'s ({dollars(p.prior_required_cents)}).")


def _status(d: E.Due, today: date) -> str:
    if d.installment_cents == 0:     # California's September date; an earlier shortfall shows on its own row (m6)
        return "nothing"
    if d.still_due_cents == 0:
        return "paid"
    return "short" if d.due < today else "upcoming"


def _agency_out(p: E.AgencyPlan, q: Quarterly, today: date) -> dict:
    last = p.dues[-1]
    skip = None
    if p.method != "none_needed" and last.still_due_cents > 0 and today <= last.due:
        skip = (f"You can skip the {short_date(last.due)} payment if you file your {q.year} return by "
                f"{long_date(p.skip_fourth_if_filed_by)} and pay the rest.")
    return {
        "agency": p.agency, "label": agency_label(p.agency, q.state), "method": p.method,
        "line": method_line(p, q.year, q.prior, q.state),
        "withholding_line": (f"Less {dollars(p.withholding_cents)} withheld from {q.year} pay."
                             if p.withholding_cents and p.method != "none_needed" else None),
        "skip_line": skip,
        "current_tax_cents": p.current_tax_cents, "current_required_cents": p.current_required_cents,
        "prior_required_cents": p.prior_required_cents, "required_cents": p.required_cents,
        "withholding_cents": p.withholding_cents, "balance_cents": p.balance_cents, "paid_cents": p.paid_cents,
        "dues": [{"due": d.due.isoformat(), "due_label": long_date(d.due), "installment_cents": d.installment_cents,
                  "by_then_cents": d.by_then_cents, "paid_cents": d.paid_cents, "still_due_cents": d.still_due_cents,
                  "status": _status(d, today)} for d in p.dues],
    }


def quarterly_out(q: Quarterly, today: date, email_on: bool) -> dict:
    n = notice(q, today)
    rng = q.hh.range
    return {
        "available": True, "year": q.year, "prior_year": q.year - 1, "state": q.state, "state_name": state_name(q.state),
        "rules_note": q.rules_note, "never": NEVER,
        "profit": None if rng is None else {"low_cents": rng.low_cents, "high_cents": rng.high_cents,
                                            "entered": rng.entered},
        "low_tax_cents": q.low_tax_cents,
        "agencies": [_agency_out(p, q, today) for p in (q.federal, q.state_plan) if p is not None],
        "next": None if q.next_due is None else {"due": q.next_due.due.isoformat(), "due_label": long_date(q.next_due.due),
                                                 "federal_cents": q.next_due.federal_cents,
                                                 "state_cents": q.next_due.state_cents},
        "notice": None if n is None else notice_line(n, q.state),
        "payments": [{"id": p.id, "posted_at": p.posted_at.isoformat(), "posted_label": long_date(p.posted_at),
                      "agency": p.agency,
                      "label": agency_label(p.agency, q.state), "amount_cents": p.amount_cents, "counts": p.counts,
                      "description": p.description} for p in q.payments],
        "prior": asdict(q.prior) if q.prior is not None else None,
        "withholding": None if q.withholding is None else {
            "federal_ytd_cents": q.withholding.federal_ytd_cents, "state_ytd_cents": q.withholding.state_ytd_cents,
            "as_of": q.withholding.as_of.isoformat(), "as_of_label": long_date(q.withholding.as_of)},
        "has_wages": q.hh.salary_cents > 0, "needs_withholding": q.needs_withholding,
        "notes": list(q.notes), "email_on": email_on,
    }
