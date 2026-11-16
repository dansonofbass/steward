"""Care costs (spec 4.2, D5): typical California figures from the dated table data/rules/care_costs_<year>.json, each
with its source and year, and a family's quote in its place ("your quote, <date>"). A figure is brought to this year at
the care growth rate (spec 3.4; ruling 7), so a 2025 survey reads in this year's dollars; a quote from an earlier year
is raised the same way. In-home help is the hourly rate times hours a week; adult day is the daily rate times days a
week (ruling 6)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from steward.care.vocab import COST_KEYS
from steward.engine.tax import rules
from steward.inventory.present import MINUS, long_date, short_usd

WEEKS_A_YEAR = 52
PER_WORDS = {"hour": "an hour", "day": "a day", "month": "a month"}
LABELS = {"in_home_hourly": "In-home help", "adult_day_daily": "Adult day", "assisted_living_monthly": "Assisted living",
          "memory_care_monthly": "Memory care", "nursing_home_shared_monthly": "Nursing home, shared room",
          "nursing_home_private_monthly": "Nursing home, private room"}


@dataclass(frozen=True)
class Quote:
    key: str
    cents: int
    quoted_on: date


@dataclass(frozen=True)
class Figure:
    key: str
    label: str
    per: str                 # "hour", "day" or "month"
    cents: int               # in this year's dollars
    base_cents: int          # as published, or as quoted
    base_year: int           # the survey's year, or the quote's
    survey: str | None       # None for a quote
    url: str | None
    quoted_on: date | None
    line: str                # what the screen shows beside the figure


def dollars(cents: int) -> str:
    """Whole dollars, rounded half up: 13_000_000 -> "$130,000", -500 -> "−$5"."""
    whole = (abs(int(cents)) + 50) // 100
    return f"{MINUS if cents < 0 and whole else ''}${whole:,}"


def _raise(cents: int, years: int, care_inflation: float) -> int:
    return int(cents * (1.0 + care_inflation) ** max(years, 0) + 0.5)


def _pct(rate: float) -> str:
    return f"{rate * 100:g}%"


def typical(key: str, this_year: int, care_inflation: float) -> Figure:
    f = rules.table("care_costs", this_year)["figures"][key]
    line = f["survey"] if f.get("estimate") else f"Typical in California: {f['survey']}"
    if f["survey_year"] < this_year and care_inflation > 0:
        line += f", raised {_pct(care_inflation)} a year to {this_year}"
    return Figure(key, LABELS[key], f["per"], _raise(f["cents"], this_year - f["survey_year"], care_inflation),
                  f["cents"], f["survey_year"], f["survey"], f["url"], None, line + ".")


def from_quote(q: Quote, this_year: int, care_inflation: float) -> Figure:
    per = rules.table("care_costs", this_year)["figures"][q.key]["per"]
    return Figure(q.key, LABELS[q.key], per, _raise(q.cents, this_year - q.quoted_on.year, care_inflation), q.cents,
                  q.quoted_on.year, None, None, q.quoted_on, f"Your quote, {long_date(q.quoted_on)}.")


def figures(quotes: dict[str, Quote], this_year: int, care_inflation: float) -> dict[str, Figure]:
    return {k: from_quote(quotes[k], this_year, care_inflation) if k in quotes else typical(k, this_year, care_inflation)
            for k in COST_KEYS}


def per_month(cents_per_unit: int, units_a_week: int) -> int:
    """A rate times units a week, as a monthly figure (x 52 / 12), rounded half up to the cent."""
    total = cents_per_unit * units_a_week * WEEKS_A_YEAR
    return (2 * total + 12) // 24


def monthly_cents(level: str, figs: dict[str, Figure], *, hours_week: int | None = None,
                  adult_day_days: int | None = None, room: str | None = None) -> int:
    if level == "at_home":
        return 0
    if level == "in_home_help":
        return per_month(figs["in_home_hourly"].cents, hours_week or 0) + per_month(figs["adult_day_daily"].cents,
                                                                                   adult_day_days or 0)
    if level == "nursing_home":
        return figs[f"nursing_home_{room or 'shared'}_monthly"].cents
    return figs[f"{level}_monthly"].cents


def figure_text(f: Figure) -> str:
    """"$7,280 a month", "$41.60 an hour"."""
    return f"{short_usd(f.cents)} {PER_WORDS[f.per]}"
