"""The Medi-Cal check (spec 4.3, 3.6; D9): each projected year's countable assets against the asset limit in force
that year, from part 1's dated table. An estimate, never an application or legal advice.

Ruling 2: cash, the taxable account and Roth money count; traditional money counts until its owner reaches RMD age,
when it is "in payout" and exempt (the table's retirement_accounts_in_payout). The home is exempt and never in the
balances; sale proceeds land in the taxable account and count. A married parent uses the two-person limit.
Ruling 1: over the limit in a year care is paid reads "Eligible after spending down $X"; in a year without care, "Not
yet: countable assets are $X over the limit". A scheduled change is used only once its status is "confirmed" (spec
3.6); the reported 2027 drop is not."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from steward.care.costs import dollars
from steward.engine.project import YearRow
from steward.engine.tax import rules
from steward.inventory.present import long_date

Status = Literal["eligible", "over_limit", "after_spend_down"]
DISCLAIMER = "An estimate to take to an elder-law attorney, not legal advice."
_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class Limit:
    cents: int
    people: int
    rules_year: int
    effective_from: date
    source: str              # "DHCS All County Welfare Directors Letter 25-14"
    url: str | None


@dataclass(frozen=True)
class MediCalYear:
    year: int
    status: Status
    countable_cents: int
    over_cents: int          # 0 when eligible
    limit: Limit


def _short_source(text: str) -> str:
    """"DHCS All County Welfare Directors Letter 25-14 (2025-06-30): property limit …" -> the letter's name."""
    return re.sub(r"\s*\([^)]*\)$", "", text.split(":", 1)[0]).strip()


def asset_limit(year: int, people: int) -> Limit:
    t = rules.table("medi_cal", year)
    limit, start, rules_year = t["asset_limit"], t.effective_from, t.year
    for s in t["scheduled"]:
        on = date.fromisoformat(s["effective_from"])
        if s["status"] == "confirmed" and on <= date(year, 12, 31):
            limit, start, rules_year = s["asset_limit"], on, on.year
    n = max(1, min(people, limit["max_household"]))
    dollars_total = limit["first_person"]
    if n >= 2:
        dollars_total += limit.get("each_additional_first", limit["each_additional"])
    dollars_total += limit["each_additional"] * max(n - 2, 0)
    url = _URL.search(t.source[0])
    return Limit(dollars_total * 100, n, rules_year, start, _short_source(t.source[0]), url.group(0) if url else None)


def in_payout(owner_birth_year: int, year: int) -> bool:
    return year - owner_birth_year >= rules.rmd_start_age(owner_birth_year, year)


def countable_cents(row: YearRow, owner_birth_year: int) -> int:
    trad = 0 if in_payout(owner_birth_year, row.year) else row.traditional_cents
    return row.cash_cents + row.taxable_cents + row.roth_cents + trad


def check_year(row: YearRow, owner_birth_year: int, people: int) -> MediCalYear:
    lim = asset_limit(row.year, people)
    countable = countable_cents(row, owner_birth_year)
    over = max(countable - lim.cents, 0)
    status: Status = "eligible" if over == 0 else "after_spend_down" if row.care_cents > 0 else "over_limit"
    return MediCalYear(row.year, status, countable, over, lim)


def status_line(m: MediCalYear) -> str:
    if m.status == "eligible":
        return "Eligible"
    if m.status == "after_spend_down":
        return f"Eligible after spending down {dollars(m.over_cents)}"
    return f"Not yet: countable assets are {dollars(m.over_cents)} over the limit"


def rule_line(lim: Limit) -> str:
    who = "one person" if lim.people == 1 else f"{lim.people} people"
    return (f"Limit {dollars(lim.cents)} for {who}, from {long_date(lim.effective_from)} "
            f"({lim.rules_year} rules, {lim.source}).")


def first_eligible(checks: Iterable[MediCalYear]) -> int | None:
    return next((m.year for m in checks if m.status == "eligible"), None)


def topics(look_back_months: int, rules_year: int) -> list[str]:
    return ["Estate recovery after a death", "Protections for a spouse who stays at home",
            f"The {look_back_months}-month look-back on gifts and transfers ({rules_year} rules)"]
