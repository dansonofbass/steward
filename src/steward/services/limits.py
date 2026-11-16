"""This year's contribution limits (investment views spec, Contributions and limits). They are the rule tables Next
dollar reads, src/steward/engine/data/rules/retirement_<year>.json, through engine/decisions.py; this module adds only
whether this year has its own table. rules.table would quietly use last year's, which Next dollar labels; the account
pages say the limits are missing instead, and the CLI warns."""
from __future__ import annotations

from datetime import date

from steward.engine.decisions import hsa_limit, ira_limit_cents, k401_limit_cents
from steward.engine.tax import rules
from steward.engine.tax.rules import RulesError

MISSING = "This year's limits aren't in Steward yet."
CLI_MISSING = ("Steward has no contribution limits for {year} yet. Add src/steward/engine/data/rules/retirement_{year}.json "
               "from the IRS's published figures; until then the account pages say so.")


def have_year(year: int) -> bool:
    try:
        return rules.table("retirement", year).year == year
    except RulesError:
        return False


def k401_cents(age: int, year: int) -> int:
    return k401_limit_cents(age, year)


def ira_cents(age: int, year: int) -> int:
    return ira_limit_cents(age, year)


def hsa_cents(family: bool, ages: tuple[int, ...], year: int) -> int:
    return hsa_limit(family, ages, year)[0]


def cli_warning(today: date) -> str | None:
    return None if have_year(today.year) else CLI_MISSING.format(year=today.year)
