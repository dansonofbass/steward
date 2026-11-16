"""Levers (spec section 3.6): their scales, clamping, try values and impact wording."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from steward.engine.inputs import COST_LEVELS, Child, Household, Levers


@dataclass(frozen=True)
class Scale:
    lo: int
    hi: int
    step: int


SAVE_MORE = Scale(0, 300_000, 5_000)            # $0-$3,000 a month, $50 steps (cents)
SPENDING = Scale(60, 130, 5)                    # percent of the spending basis
CONSULTING = Scale(0, 15_000_000, 100_000)      # $0-$150,000 a year, $1,000 steps
GIFT = Scale(0, 5_000_000, 50_000)              # $0-$50,000 a year, $500 steps
SPOUSE_EARNINGS = Scale(0, 12_000_000, 100_000) # $0-$120,000 a year, $1,000 steps
CLAIM_AGE = Scale(62, 70, 1)
LATEST_AGE = 70


def snap(value: int, scale: Scale) -> int:
    """Clamp to the scale, then round half-up to the nearest step."""
    v = min(max(int(value), scale.lo), scale.hi)
    v = scale.lo + (v - scale.lo + scale.step // 2) // scale.step * scale.step
    return min(max(v, scale.lo), scale.hi)


def _year(value: int, plan_year: int) -> int:
    """0 means unset and stays 0; any other year is lifted to the plan year at the earliest."""
    return 0 if value == 0 else max(value, plan_year)


def clamp(levers: Levers, hh: Household) -> Levers:
    """Bring every lever onto its scale. Values outside a scale are clamped server-side (spec 3.6)."""
    jr_age = hh.plan_year - hh.jr.birth_year
    sp_age = hh.plan_year - hh.spouse.birth_year
    levels = levers.college_levels
    if levels is not None and (len(levels) != len(hh.children) or any(l not in COST_LEVELS for l in levels)):
        levels = None
    if levels is None:
        levels = tuple(c.cost_level for c in hh.children)   # spelled out, so the same plan always has the same digest
    return replace(
        levers,
        save_more_monthly_cents=snap(levers.save_more_monthly_cents, SAVE_MORE),
        spending_pct=snap(levers.spending_pct, SPENDING),
        consulting_cents=snap(levers.consulting_cents, CONSULTING),
        consulting_until_age=min(max(levers.consulting_until_age, jr_age), LATEST_AGE),
        gift_cents=snap(levers.gift_cents, GIFT),
        gift_until_year=_year(levers.gift_until_year, hh.plan_year),
        spouse_earnings_cents=snap(levers.spouse_earnings_cents, SPOUSE_EARNINGS),
        spouse_start_year=_year(levers.spouse_start_year, hh.plan_year),
        spouse_stop_age=min(max(levers.spouse_stop_age, sp_age), LATEST_AGE),
        jr_claim_age=snap(levers.jr_claim_age, CLAIM_AGE),
        spouse_claim_age=snap(levers.spouse_claim_age, CLAIM_AGE),
        college_levels=levels,
        full_ss_benefits=bool(levers.full_ss_benefits),
    )


@dataclass(frozen=True)
class LeverSpec:
    key: str
    label: str
    kind: Literal["money", "pct", "age", "level", "switch"]
    fields: tuple[str, ...]


LEVERS: tuple[LeverSpec, ...] = (
    LeverSpec("save_more", "Save more each month", "money", ("save_more_monthly_cents",)),
    LeverSpec("spending", "Spending in retirement", "pct", ("spending_pct",)),
    LeverSpec("consulting", "Consulting income, a year", "money", ("consulting_cents", "consulting_until_age")),
    LeverSpec("gift", "Yearly gift", "money", ("gift_cents", "gift_until_year")),
    LeverSpec("spouse_earnings", "Spouse's earnings, a year", "money", ("spouse_earnings_cents", "spouse_start_year", "spouse_stop_age")),
    LeverSpec("jr_claim", "{person1} claims Social Security at", "age", ("jr_claim_age",)),
    LeverSpec("spouse_claim", "Spouse claims Social Security at", "age", ("spouse_claim_age",)),
    LeverSpec("college", "College type", "level", ("college_levels",)),
    LeverSpec("full_ss", "Full Social Security benefits", "switch", ("full_ss_benefits",)),
)
LEVER_BY_KEY = {spec.key: spec for spec in LEVERS}
# P13: the try lowers a level one step on today's ladder and never proposes two-year on its own.
TRY_LOWER: dict[str, str] = {"private": "out_of_state_public", "out_of_state_public": "in_state_public",
                             "in_state_public": "in_state_public", "two_year": "two_year"}


def college_levels_of(levers: Levers, children: tuple[Child, ...]) -> tuple[str, ...]:
    """Each child's level: the override if set, else the child's own."""
    return levers.college_levels if levers.college_levels is not None else tuple(c.cost_level for c in children)


def with_try(assumed: Levers, trial: Levers, key: str, *, children: tuple[Child, ...] = (), child_index: int | None = None) -> Levers:
    """The assumed levers with one lever's fields taken from the try values."""
    spec = LEVER_BY_KEY[key]
    if key == "college":
        if child_index is None:
            return replace(assumed, college_levels=college_levels_of(trial, children))
        levels = list(college_levels_of(assumed, children))
        levels[child_index] = college_levels_of(trial, children)[child_index]
        return replace(assumed, college_levels=tuple(levels))
    return replace(assumed, **{f: getattr(trial, f) for f in spec.fields})


@dataclass(frozen=True)
class ObservedTry:
    """What the vault shows for the data-derived try defaults (spec 3.6)."""
    consulting_12mo_cents: int = 0
    gift_12mo_cents: int = 0
    spouse_earnings_cents: int = 0


def default_try(hh: Household, assumed: Levers, observed: ObservedTry) -> tuple[Levers, tuple[str, ...]]:
    """Spec 3.6 try defaults. A lever with no history uses the scale's first non-zero step and gets a note."""
    notes: list[str] = []

    def observed_or_first(value: int, scale: Scale, key: str) -> int:
        snapped = snap(value, scale)
        if snapped > 0:
            return snapped
        notes.append(f"{key}: No history yet")
        return scale.lo + scale.step

    consulting = observed_or_first(observed.consulting_12mo_cents, CONSULTING, "consulting")
    gift = observed_or_first(observed.gift_12mo_cents, GIFT, "gift")
    spouse = observed_or_first(observed.spouse_earnings_cents, SPOUSE_EARNINGS, "spouse_earnings")
    lower = tuple(TRY_LOWER[level] for level in college_levels_of(assumed, hh.children))
    levers = Levers(
        save_more_monthly_cents=snap(assumed.save_more_monthly_cents + 50_000, SAVE_MORE),
        spending_pct=90,
        consulting_cents=consulting, consulting_until_age=60,
        gift_cents=gift, gift_until_year=hh.plan_year + 10,
        spouse_earnings_cents=spouse, spouse_start_year=hh.plan_year + 1, spouse_stop_age=65,
        jr_claim_age=70, spouse_claim_age=70,
        college_levels=lower,
        full_ss_benefits=True,
    )
    return clamp(levers, hh), tuple(notes)


def try_value(spec: LeverSpec, levers: Levers, child_index: int | None = None, children: tuple[Child, ...] = ()) -> int | bool | str:
    if spec.key == "college":
        return college_levels_of(levers, children)[child_index]
    return getattr(levers, spec.fields[0])


def impact_text(delta_months: int | None, base_age: int | None, new_age: int | None) -> str:
    if base_age is None and new_age is None:
        return "Still not by 70"
    if base_age is None:
        return f"Comfortable by {new_age}"
    if new_age is None:
        return "Not by 70"
    if not delta_months:
        return "No change"
    months = abs(delta_months)
    direction = "earlier" if delta_months < 0 else "later"
    if months < 12:
        return f"about {months} month{'s' if months != 1 else ''} {direction}"
    years = (months + 6) // 12
    return f"about {years} year{'s' if years != 1 else ''} {direction}"
