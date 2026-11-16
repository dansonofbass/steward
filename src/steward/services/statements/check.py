"""The balance check (spec P20): exact to the cent. A bank statement's closing − opening equals the sum of its rows as
Steward stores them (money out negative); a card's or loan's (printed owed positive) equals minus that sum. Section
totals, when the layout names them, are checked too, so row review can say "Purchases are off by $12.40". "Adds up"
doesn't prove the dates or descriptions are right: a new layout still needs a person's Looks right."""
from __future__ import annotations

from collections.abc import Iterable

from steward.services.statements.rules import OWED, Reading


def gap(kind: str, opening: int | None, closing: int | None, cents: Iterable[int]) -> int | None:
    if opening is None or closing is None:
        return None
    moved = sum(cents)
    return (closing - opening) + moved if kind in OWED else (closing - opening) - moved


def section_report(reading: Reading) -> list[dict]:
    return [{"title": t, "sum_cents": reading.sums.get(t, 0), "total_cents": total} for t, total in reading.totals.items()]


def off_sections(report: list[dict]) -> list[tuple[str, int]]:
    return [(s["title"], s["total_cents"] - s["sum_cents"]) for s in report
            if s["total_cents"] is not None and s["total_cents"] != s["sum_cents"]]


WITHIN = 100          # P39: holdings, cash sweep included, within $1 of the total


def holdings_gap(total: int | None, values) -> int | None:
    """0 when the holdings come within $1 of the total (which counts as adding up), else the total minus their sum."""
    if total is None:
        return None
    gap = total - sum(values)
    return 0 if abs(gap) <= WITHIN else gap
