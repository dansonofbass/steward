"""Dated rule tables (spec 3.2): one JSON file per topic and year under data/rules/, named <topic>_<year>.json.

Every table says what year it is for (`year`, or `effective_from` / `effective_to` for rules that start on a date),
where its numbers come from (`source`) and when they were last checked against that source (`checked`). Values are
entered from the sources at build time, never from memory. A year with no table of its own uses the latest earlier
table; `RuleTable.year` says which one was used, so the UI can say "using <year> rules".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

RULES_DIR = Path(__file__).resolve().parent.parent / "data" / "rules"
_NAME = re.compile(r"^(?P<topic>[a-z_]+?)_(?P<year>\d{4})\.json$")


class RulesError(RuntimeError):
    """A rule table is missing, or doesn't carry its year, source and checked date."""


@dataclass(frozen=True)
class RuleTable:
    topic: str
    year: int                    # the year in the file name: the tax year, or the year the rule took effect
    effective_from: date
    effective_to: date | None    # None: still in force
    source: tuple[str, ...]
    checked: date
    data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


def _date(value: object, path: Path, key: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise RulesError(f"{path.name}: {key} must be a date like 2026-10-20") from None


def load(path: Path) -> RuleTable:
    m = _NAME.match(path.name)
    if not m:
        raise RulesError(f"{path.name}: rule tables are named <topic>_<year>.json")
    raw = json.loads(path.read_text())
    year = int(m["year"])
    if raw.get("topic") != m["topic"]:
        raise RulesError(f"{path.name}: topic must be {m['topic']!r}")
    if "year" in raw:
        if raw["year"] != year:
            raise RulesError(f"{path.name}: year {raw['year']} doesn't match the file name")
        start, end = date(year, 1, 1), date(year, 12, 31)
    elif "effective_from" in raw:
        start = _date(raw["effective_from"], path, "effective_from")
        if start.year != year:
            raise RulesError(f"{path.name}: effective_from {start} doesn't match the file name")
        end = None if raw.get("effective_to") is None else _date(raw["effective_to"], path, "effective_to")
    else:
        raise RulesError(f"{path.name}: needs a year, or an effective_from date")
    source = raw.get("source")
    if isinstance(source, str):          # one URL or publication; the list form is for several
        source = [source]
    if not source or not isinstance(source, list) or not all(isinstance(s, str) and s.strip() for s in source):
        raise RulesError(f"{path.name}: needs a source (a publication or URL, or a list of them)")
    if "checked" not in raw:
        raise RulesError(f"{path.name}: needs the date it was checked against its source")
    data = {k: v for k, v in raw.items() if k not in ("topic", "year", "effective_from", "effective_to", "source", "checked")}
    return RuleTable(topic=m["topic"], year=year, effective_from=start, effective_to=end, source=tuple(source),
                     checked=_date(raw["checked"], path, "checked"), data=data)


@cache
def all_tables() -> tuple[RuleTable, ...]:
    """Every table on disk, checked. Sorted by topic, then year."""
    return tuple(sorted((load(p) for p in RULES_DIR.glob("*.json")), key=lambda t: (t.topic, t.year)))


@cache
def table(topic: str, year: int) -> RuleTable:
    """The table for `topic` in force in `year`: its own, or the latest earlier one. Raises RulesError if none."""
    found = [t for t in all_tables() if t.topic == topic and t.year <= year]
    if not found:
        raise RulesError(f"There are no {topic} rules for {year} or any earlier year.")
    return found[-1]


def latest_year(topic: str) -> int:
    years = [t.year for t in all_tables() if t.topic == topic]
    if not years:
        raise RulesError(f"There are no {topic} rules.")
    return max(years)


def irmaa_monthly(magi: float, filing: str, year: int) -> tuple[float, float]:
    """Medicare Part B premium and the Part D adjustment for one person, a month, from the MAGI two years before.

    Every tier but the top starts *above* its bound; the top starts *at* it (CMS fact sheet)."""
    t = table("medicare", year)
    part_b, part_d = t["part_b_monthly"], 0.0
    for bound, inclusive, b_add, d_add in t["irmaa"][filing]:
        if magi > bound or (inclusive and magi >= bound):
            part_b, part_d = t["part_b_monthly"] + b_add, d_add
    return round(part_b, 2), part_d


def rmd_start_age(birth_year: int, year: int) -> int:
    for born_by, age in table("rmd", year)["start_age"]:
        if birth_year <= born_by:
            return age
    raise RulesError(f"No required beginning age for someone born in {birth_year}.")


def rmd_divisor(age: int, year: int) -> float:
    divisors = table("rmd", year)["uniform_lifetime"]
    return float(divisors[str(min(max(age, 72), 120))])
