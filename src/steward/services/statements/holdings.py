"""Investment and loan statements (PDF statements spec P15, P39, decision 2, "Investment statements"). The holdings
table is read like a transactions table: bands from its header line, a holding per line with a value and a symbol or
a name, from the header to the total label's line (a table after the total, such as a 401(k)'s balance by source, is
never read); a line naming one of the cash labels is the cash sweep and counts toward the total. The ending balance is
the first amount after its label. A loan gives its principal (its closing label) and nothing else. Labels go through
labels.py, exactly as validation matched them."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from steward.services.statements import labels
from steward.services.statements.extract import line_text, mask
from steward.services.statements.money import amounts, parse_amount
from steward.services.statements.rules import MAX_AGE_DAYS, _last4, _period, assign, bands, fact_amount, header_cells

MAX_HOLDINGS = 200
MAX_SHARES_MILLI = 10**15
_SHARES = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?")


@dataclass
class HoldingRow:
    symbol: str | None
    name: str
    shares_milli: int
    value_cents: int
    cash: bool
    page: int


@dataclass
class HoldingsReading:
    period: tuple[date, date] | None = None
    last4: str | None = None
    ending: int | None = None
    total: int | None = None
    holdings: list[HoldingRow] = field(default_factory=list)
    error: str | None = None


def shares_milli(text: str | None) -> int:
    """'1,204.5531' -> 1204553 (half up); anything that isn't a plain number is 0 (Engineering choice 5)."""
    t = (text or "").strip()
    if not t or not any(ch.isdigit() for ch in t) or _SHARES.fullmatch(t) is None:
        return 0
    try:
        d = Decimal(t.replace(",", ""))
        if not d.is_finite():
            return 0
        milli = int((d * 1000).to_integral_value(rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        return 0
    return milli if abs(milli) <= MAX_SHARES_MILLI else 0


def _facts(layout: dict, pages: list[dict], today: date) -> HoldingsReading:
    lines = [ln for p in pages for ln in p["lines"]]
    r = HoldingsReading()
    r.period = _period(lines, layout)
    if r.period is None or r.period[1] > today or (today - r.period[1]).days > MAX_AGE_DAYS:
        r.period, r.error = None, "no_period"
        return r
    r.last4 = _last4(lines, layout["account_label"])
    return r


def apply_loan(layout: dict, pages: list[dict], today: date) -> HoldingsReading:
    r = _facts(layout, pages, today)
    if r.error is None:
        r.ending = fact_amount([ln for p in pages for ln in p["lines"]], layout["closing"]["label"])
    return r


def apply_holdings(layout: dict, pages: list[dict], today: date) -> HoldingsReading:
    r = _facts(layout, pages, today)
    if r.error is not None:
        return r
    h = layout["holdings"]
    cols = h["columns"]
    fields = {c["field"] for c in cols}
    r.ending = fact_amount([ln for p in pages for ln in p["lines"]], h["ending"]["label"])
    inside = False
    for p in pages:
        bs = None
        for ln in p["lines"]:
            found = header_cells(cols, ln)
            if found is not None:
                bs, inside = bands(cols, found, p["width"]), True
                continue
            if not inside or bs is None:
                continue
            if labels.starts(h["total_label"], line_text(ln)):
                got = amounts(labels.after(h["total_label"], ln))
                r.total = got[0] if got else None
                inside = False
                continue
            got = assign(ln["cells"], bs)
            value = parse_amount(" ".join(got["value"])) if got.get("value") else None
            symbol = " ".join(got.get("symbol", [])).strip() or None
            name = " ".join(got.get("name", [])).strip()
            if value is None or not (symbol or name):
                continue
            words = f"{symbol or ''} {name}"
            r.holdings.append(HoldingRow(mask(symbol)[:20] if symbol else None, mask(name or symbol or "")[:200],
                                         shares_milli(" ".join(got.get("shares", []))) if "shares" in fields else 0,
                                         value, any(labels.occurs(c, words) for c in h["cash_labels"]), p["n"]))
            if len(r.holdings) > MAX_HOLDINGS:
                r.error = "too_many_holdings"
                return r
    return r
