"""A new layout's proposal and its one retry (spec P16, P17, P21, P22). Ask, validate against the lines that were
sent, read every part, check; when it doesn't add up, ask once more with the gap, each section's sum against its
printed total, the failing lines and the first proposal (the gateway answers a hint at temperature 0.3 with a fixed
seed), and keep the second only when it makes the gap smaller. A learned layout that drifted comes in as `first`.
The reader uses this, and so does the gateway's eval, so the eval measures what the NAS does."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from steward.services.statements import check, validate
from steward.services.statements.extract import for_model
from steward.services.statements.rules import Reading, apply, part_count
from steward_boundary.statements_wire import MAX_HINT_LINE, MAX_HINT_LINES, MAX_SECTIONS

READ_KINDS = ("bank", "card", "investment", "retirement", "loan")


@dataclass
class Proposal:
    layout: dict | None
    readings: list[Reading] = field(default_factory=list)
    gap: int | None = None             # every part's gap, summed as sizes; 0 adds up; None can't be checked
    asked: int = 0
    failed: int = 0
    retry_failed: bool = False


def read_all(layout: dict, pages: list[dict], today: date) -> tuple[list, int | None]:
    from steward.services.statements.holdings import apply_holdings, apply_loan
    if layout["kind"] == "loan":
        r = apply_loan(layout, pages, today)
        return [r], (None if r.error or r.ending is None else 0)
    if layout["kind"] in ("investment", "retirement"):
        r = apply_holdings(layout, pages, today)
        if r.error or not r.holdings:
            return [r], None
        return [r], check.holdings_gap(r.total if r.total is not None else r.ending, [h.value_cents for h in r.holdings])
    readings = [apply(layout, pages, today, k) for k in range(part_count(pages, layout.get("account_marker")))]
    if any(r.error for r in readings):
        return readings, None
    gaps = [check.gap(layout["kind"], r.opening, r.closing, [x.amount_cents for x in r.rows]) for r in readings]
    return readings, None if any(g is None for g in gaps) else sum(abs(g) for g in gaps)


def hint_for(layout: dict, reading, gap: int | None) -> dict:
    sections = check.section_report(reading)[:MAX_SECTIONS] if hasattr(reading, "sums") else []
    return {"gap_cents": gap or 0, "sections": sections,
            "lines": [text[:MAX_HINT_LINE] for _, text in getattr(reading, "unreadable", [])][:MAX_HINT_LINES],
            "previous": layout}


def better(a: int | None, b: int | None) -> bool:
    return a is not None and (b is None or abs(a) < abs(b))


def propose(ask: Callable[[list[dict], dict | None], dict | None], pages: list[dict], today: date,
            first: dict | None = None) -> Proposal:
    sent = for_model(pages)
    out = Proposal(None)
    if first is None:
        answer = ask(sent, None)
        out.asked += 1
        if answer is None or validate.errors(answer, sent):
            out.failed += 1
            return out
        first = answer
    out.layout = first
    if first["kind"] not in READ_KINDS:
        return out
    out.readings, out.gap = read_all(first, pages, today)
    if out.gap == 0:
        return out
    again = ask(sent, hint_for(first, out.readings[0] if out.readings else Reading(), out.gap))
    out.asked += 1
    if again is None or validate.errors(again, sent) or again["kind"] not in READ_KINDS:
        out.failed += 1
        out.retry_failed = True
        return out
    readings, g = read_all(again, pages, today)
    if better(g, out.gap):
        out.layout, out.readings, out.gap = again, readings, g
    return out
