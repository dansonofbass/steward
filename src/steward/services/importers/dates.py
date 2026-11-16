"""Date formats (import/export spec, Dates; P13). The candidates that read at least 98% of the column's cells are
kept; a first part over 12 means day first and a second part over 12 means month first; then the reading that keeps
the file in date order wins; otherwise one question shows a real date from the file."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

ISO_DATETIME = "iso-datetime"
ISO = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", ISO_DATETIME)
MONTH_FIRST = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y")
DAY_FIRST = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%d.%m.%y")
WORDS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d-%b-%Y")
CANDIDATES = ISO + MONTH_FIRST + DAY_FIRST + WORDS
READS = 0.98
_ISO_DT = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_PARTS = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def parse_day(text: str, fmt: str) -> date:
    s = text.strip()
    if fmt == ISO_DATETIME:
        m = _ISO_DT.fullmatch(s)
        if m is None:
            raise ValueError(s)
        return date(int(m[1]), int(m[2]), int(m[3]))
    if fmt == "%Y%m%d" and not re.fullmatch(r"\d{8}", s):
        raise ValueError(s)                      # strptime reads "2024103" as Oct 3
    return datetime.strptime(s, fmt).date()


def reading(fmt: str) -> str:
    if fmt in ISO:
        return "year-month-day"
    if fmt in DAY_FIRST or fmt in ("%d %b %Y", "%d-%b-%Y"):
        return "day/month/year"
    return "month/day/year"


def day_label(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.day}"


@dataclass(frozen=True)
class DateChoice:
    format: str | None                       # None: asked (example set) or nothing reads (example None)
    example: str | None = None
    options: tuple[str, str] | None = None   # (the month-first format, the day-first format)


def _days(cells: list[str], fmt: str) -> list[date]:
    out = []
    for c in cells:
        try:
            out.append(parse_day(c, fmt))
        except ValueError:
            continue
    return out


def _ordered(days: list[date]) -> bool:
    pairs = list(zip(days, days[1:]))
    return all(a <= b for a, b in pairs) or all(a >= b for a, b in pairs)


def choose(cells: list[str]) -> DateChoice:
    cells = [c.strip() for c in cells if c.strip()]
    if not cells:
        return DateChoice(None)
    kept = [f for f in CANDIDATES if len(_days(cells, f)) >= READS * len(cells)]
    if not kept:
        return DateChoice(None)
    mf = next((f for f in kept if f in MONTH_FIRST), None)
    df = next((f for f in kept if f in DAY_FIRST), None)
    if mf is None or df is None:
        return DateChoice(kept[0])
    parts = [m for c in cells if (m := _PARTS.fullmatch(c))]
    if any(int(m[1]) > 12 for m in parts):
        return DateChoice(df)
    if any(int(m[2]) > 12 for m in parts):
        return DateChoice(mf)
    by_month, by_day = _ordered(_days(cells, mf)), _ordered(_days(cells, df))
    if by_month != by_day:
        return DateChoice(mf if by_month else df)
    example = next((m[0] for m in parts if m[1] != m[2]), cells[0])
    return DateChoice(None, example, (mf, df))
