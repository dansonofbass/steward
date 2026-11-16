"""Statement dates (spec P18, P19; plan Engineering choice 2). The model's format is a hint: it is tried first, then
every allowed format in the wire's order. %b and %B read alike. A row printed without a year takes P19's year."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from steward_boundary.statements_wire import DATE_FORMATS

_PART = {"%m": r"\d{1,2}", "%d": r"\d{1,2}", "%Y": r"\d{4}", "%y": r"\d{2}", "%b": r"[A-Za-z]{3,9}\.?",
         "%B": r"[A-Za-z]{3,9}\.?"}
SPAN_DAYS = 100                       # the longest statement period read (a quarter is 92)


def _body(fmt: str) -> str:
    out, i = "", 0
    while i < len(fmt):
        if fmt[i:i + 2] in _PART:
            out += _PART[fmt[i:i + 2]]
            i += 2
        else:
            out += re.escape(fmt[i])
            i += 1
    return out


_FULL = {f: re.compile(_body(f)) for f in DATE_FORMATS}
_SCAN = {f: re.compile(r"(?<![\dA-Za-z])" + _body(f) + r"(?![\dA-Za-z])") for f in DATE_FORMATS}


def has_year(fmt: str) -> bool:
    return "%Y" in fmt or "%y" in fmt


def _strp(text: str, fmt: str) -> datetime | None:
    t = text.strip()
    if "%b" in fmt or "%B" in fmt:
        t = t.replace(".", "")
    f = fmt
    if not has_year(fmt):
        t, f = t + " 2000", fmt + " %Y"            # 2000 is a leap year, so Feb 29 reads
    for g in (f, f.replace("%b", "%B"), f.replace("%B", "%b")):
        try:
            return datetime.strptime(t, g)
        except ValueError:
            continue
    return None


def parse(text: str, fmt: str) -> tuple[int | None, int, int] | None:
    """(year or None, month, day) when the whole text is one date in fmt."""
    if fmt not in _FULL or not _FULL[fmt].fullmatch(text.strip()):
        return None
    d = _strp(text, fmt)
    if d is None:
        return None
    return (d.year if has_year(fmt) else None, d.month, d.day)


def find_dates(text: str, fmt: str) -> list[date]:
    out = []
    for m in _SCAN[fmt].finditer(text):
        p = parse(m.group(0), fmt)
        if p is not None and p[0] is not None:
            out.append(date(p[0], p[1], p[2]))
    return out


def _order(hint: str | None) -> list[str]:
    return ([hint] if hint in DATE_FORMATS else []) + [f for f in DATE_FORMATS if f != hint]


def period_dates(text: str, hint: str | None) -> tuple[date, date] | None:
    """P18: the period's two dates on one line, in any allowed format with a year, 0-100 days apart."""
    for fmt in _order(hint):
        if not has_year(fmt):
            continue
        found = find_dates(text, fmt)
        if len(found) >= 2 and 0 <= (found[1] - found[0]).days <= SPAN_DAYS:
            return found[0], found[1]
    return None


def infer_year(month: int, day: int, end: date) -> date | None:
    """P19: the period end's year, unless that lands more than 7 days after the period end; then the year before."""
    for year in (end.year, end.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d <= end + timedelta(days=7):
            return d
    return None


def row_date(text: str, hint: str | None, end: date) -> date | None:
    for fmt in _order(hint):
        p = parse(text, fmt)
        if p is None:
            continue
        if p[0] is not None:
            return date(p[0], p[1], p[2])
        return infer_year(p[1], p[2], end)
    return None
