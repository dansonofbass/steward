"""The my Social Security earnings record (spec 2.2 item 2, 2.4). Keeps years and Social Security taxed
earnings; names, birth date, estimates and every other element are never read into the database.

Shape (OSSS schema 2.0): <osss:OnlineSocialSecurityStatementData> / <osss:EarningsRecord> /
<osss:Earnings startYear endYear> with <osss:FicaEarnings> (dollars; -1 = not yet posted).
defusedxml refuses entity declarations and external references, so a hostile file can't expand in memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from steward.db.models import PERSONS, SsEarnings

NS = "http://ssa.gov/osss/schemas/2.0"
ROOT = f"{{{NS}}}OnlineSocialSecurityStatementData"
NOT_A_RECORD = "That file doesn't look like a Social Security earnings record."
NOT_YET_POSTED = Decimal(-1)
FIRST_YEAR = 1937
MAX_DOLLARS = Decimal(1_000_000_000)


class NotAnEarningsRecord(ValueError):
    def __init__(self) -> None:
        super().__init__(NOT_A_RECORD)


@dataclass(frozen=True)
class ParsedEarnings:
    years: tuple[tuple[int, int], ...]   # (year, earnings_cents), ascending
    skipped: int                          # not yet posted, or a row spanning several years


def parse_earnings(raw: bytes, latest_year: int) -> ParsedEarnings:
    try:
        root = SafeET.fromstring(raw)
    except (ParseError, DefusedXmlException, ValueError, UnicodeError):
        raise NotAnEarningsRecord() from None
    if root.tag != ROOT:
        raise NotAnEarningsRecord()
    record = root.find(f"{{{NS}}}EarningsRecord")
    if record is None:
        raise NotAnEarningsRecord()
    years: dict[int, int] = {}
    skipped = 0
    for el in record.findall(f"{{{NS}}}Earnings"):
        try:
            start, end = int(el.get("startYear", "")), int(el.get("endYear", ""))
        except ValueError:
            raise NotAnEarningsRecord() from None
        fica = el.find(f"{{{NS}}}FicaEarnings")
        if fica is None or fica.text is None:
            raise NotAnEarningsRecord()
        try:
            amount = Decimal(fica.text.strip())
        except InvalidOperation:
            raise NotAnEarningsRecord() from None
        if not amount.is_finite():
            raise NotAnEarningsRecord()
        if amount == NOT_YET_POSTED or start != end:
            skipped += 1
            continue
        if amount < 0 or amount > MAX_DOLLARS or not FIRST_YEAR <= start <= latest_year or start in years:
            raise NotAnEarningsRecord()
        years[start] = int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if not years:
        raise NotAnEarningsRecord()
    return ParsedEarnings(tuple(sorted(years.items())), skipped)


def replace_earnings(db: Session, person: str, parsed: ParsedEarnings, now: datetime) -> None:
    if person not in PERSONS:
        raise ValueError(person)
    db.execute(delete(SsEarnings).where(SsEarnings.person == person))
    db.add_all([SsEarnings(person=person, year=y, earnings_cents=c, imported_at=now) for y, c in parsed.years])
    db.flush()


def earnings_summary(db: Session) -> dict[str, dict | None]:
    rows = db.execute(select(SsEarnings.person, func.count(), func.min(SsEarnings.year), func.max(SsEarnings.year),
                             func.max(SsEarnings.imported_at)).group_by(SsEarnings.person)).all()
    found = {p: {"years": n, "first_year": lo, "last_year": hi, "imported_at": at.isoformat() if at else None}
             for p, n, lo, hi, at in rows}
    return {p: found.get(p) for p in PERSONS}
