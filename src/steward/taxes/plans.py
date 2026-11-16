"""Solo 401(k) or SEP (spec 7.2; rulings 2, 12-14): the room from profit so far and the range, side by side, with the
tax each lowers this year and the deadlines in plain words. A sole proprietor only. Steward never opens or funds a
plan."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy.orm import Session

from steward.business.settings import business_type
from steward.engine.decisions import SelfEmployedRoom, self_employed_room
from steward.engine.tax import annual_tax, rules
from steward.engine.tax import estimates as E
from steward.engine.tax.worksheets import schedule_se, whole
from steward.taxes.household import NotReady, household_tax
from steward.services.plan_inputs import latest_facts
from steward.taxes.quarterly import NEVER, dollars, long_date, rules_note

NO_BUSINESS = "Choose sole proprietor in Settings, Business, to see Solo 401(k) or SEP room."
SCORP_PLANS = "For an S-corp, contributions come from the salary; Steward works them out for a sole proprietor."
PAYROLL_K401 = "jr.payroll_k401_cents"
NO_PROFIT = "No room yet: the business needs a profit first."
POINT_LABELS = {"so_far": "So far", "low": "Low", "high": "High", "full_year": "Full year"}


def plans_year(today: date) -> int:
    """Ruling 2: last year until its return is due (its profit is final and it can still be funded), then this year."""
    return today.year - 1 if today <= E.return_due(today.year - 1) else today.year


@dataclass(frozen=True)
class Deadline:
    label: str
    due: date
    extended: date | None = None


def deadlines(year: int) -> tuple[tuple[Deadline, ...], tuple[Deadline, ...]]:
    """Ruling 13, from Publication 560 (2025)."""
    due, ext = E.return_due(year), E.extended_return_due(year)
    solo = [Deadline("Set up by", date(year, 12, 31))]
    if year >= rules.table("retirement", year)["solo_401k_after_year_end_from"]:
        solo.append(Deadline("Or open a new plan after the year ends, and pay in your own part, by", due))
    solo.append(Deadline("Pay in the business's part by", due, ext))
    return tuple(solo), (Deadline("Set up and pay in by", due, ext),)


def deadline_text(d: Deadline, today: date) -> str:
    when = long_date(d.due) + (f", or {long_date(d.extended)} with an extension" if d.extended else "")
    return f"{d.label} {when}" + (" (passed)" if today > (d.extended or d.due) else "")


@dataclass(frozen=True)
class PlanPoint:
    label: str                # so_far | low | high | full_year
    profit_cents: int
    room: SelfEmployedRoom
    solo_saves_cents: int     # how much this year's tax goes down with the Solo 401(k)'s most
    sep_saves_cents: int
    line: str


@dataclass(frozen=True)
class Plans:
    year: int
    points: tuple[PlanPoint, ...]
    default: str
    solo: tuple[Deadline, ...]
    sep: tuple[Deadline, ...]
    w2_deferrals_cents: int
    rules_note: str
    notes: tuple[str, ...]


def _line(room: SelfEmployedRoom) -> str:
    if room.net_earnings_cents <= 0:
        return NO_PROFIT
    more = room.solo_total_cents - room.sep_cents
    if more > 0:
        return f"A Solo 401(k) allows {dollars(more)} more at this profit: your own part isn't limited to 20% of earnings."
    if room.used_elsewhere_cents >= room.deferral_limit_cents:
        return (f"Both allow the same at this profit: your paychecks already use this year's "
                f"{dollars(room.deferral_limit_cents)} for your own part.")
    return "Both allow the same at this profit."


def plans(db: Session, today: date) -> Plans:
    btype = business_type(db)
    if btype == "none":
        raise NotReady(NO_BUSINESS)
    if btype == "s_corp":
        raise NotReady(SCORP_PLANS)
    year = plans_year(today)
    hh = household_tax(db, year, today, point="so_far")
    rng = hh.range
    if year < today.year:
        targets = [("full_year", rng.ytd_cents)]
    else:
        targets = [("so_far", rng.ytd_cents)] + ([("low", rng.low_cents), ("high", rng.high_cents)] if rng.entered else [])
    pay = rules.table("payroll", year)
    se = pay["se"]
    # Part 4's business owner: the owner's own wages and 401(k) deferrals are the only ones that count against the
    # owner's limit and wage base. Only Person 1 has W-2 pay in the model, so a business Person 2 runs has none.
    owner = hh.facts.business_owner
    owner_age = hh.facts.ages[owner]
    owner_wages = whole(hh.salary_cents / 100) if owner == 0 else 0
    deferrals_cents = hh.w2_deferrals_cents if owner == 0 else 0
    paid = latest_facts(db).get(PAYROLL_K401)       # what paychecks put in this year (part 4's fact), in its own year
    if owner == 0 and paid is not None and paid.as_of.year == year:
        deferrals_cents = max(deferrals_cents, int(paid.value))
    w2 = whole(deferrals_cents / 100)
    points: list[PlanPoint] = []
    fed_year = state_year = None
    for label, profit in targets:
        dollars_profit = whole(profit / 100)
        _, se_half, _ = schedule_se(max(dollars_profit, 0), owner_wages, pay["wage_base"], se["net_factor"],
                                    se["oasdi_rate"], se["medicare_rate"], se["minimum_net_earnings"])
        room = self_employed_room(dollars_profit, se_half, age=owner_age, w2_deferrals=w2, year=year)
        facts = replace(hh.facts, business_profit_cents=profit)
        base = annual_tax(facts, year, marginal=False)
        fed_year = base.rules_year
        state_year = base.state.rules_year if base.state.calculated else None

        def saves(cents: int) -> int:
            if cents <= 0:
                return 0
            return base.total_tax_cents - annual_tax(replace(facts, se_retirement_cents=cents), year,
                                                     marginal=False).total_tax_cents

        points.append(PlanPoint(label, profit, room, saves(room.solo_total_cents), saves(room.sep_cents), _line(room)))
    default = "low" if any(p.label == "low" for p in points) else points[0].label
    solo, sep = deadlines(year)
    limits_year = points[0].room.rules_year
    note = rules_note(year, min(fed_year, limits_year), state_year, hh.facts.state)
    return Plans(year, tuple(points), default, solo, sep, deferrals_cents, note, hh.notes)


def plans_out(p: Plans, today: date) -> dict:
    return {
        "available": True, "year": p.year, "rules_note": p.rules_note, "never": NEVER, "default_point": p.default,
        "w2_deferrals_cents": p.w2_deferrals_cents, "notes": list(p.notes),
        "points": [{"label": x.label, "label_text": POINT_LABELS[x.label], "profit_cents": x.profit_cents,
                    "net_earnings_cents": x.room.net_earnings_cents, "line": x.line,
                    "solo": {"own_cents": x.room.solo_own_cents, "business_cents": x.room.solo_business_cents,
                             "catch_up_cents": x.room.solo_catch_up_cents, "total_cents": x.room.solo_total_cents,
                             "saves_cents": x.solo_saves_cents},
                    "sep": {"total_cents": x.room.sep_cents, "saves_cents": x.sep_saves_cents}} for x in p.points],
        "deadlines": {"solo": [deadline_text(d, today) for d in p.solo], "sep": [deadline_text(d, today) for d in p.sep]},
    }
