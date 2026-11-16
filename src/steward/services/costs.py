"""Fund costs (investment views spec, Costs). A holding's expense ratio comes from the household's override, then the
built-in table of common funds (src/steward/data/expense_ratios.json, kept offline: Steward never looks a fund up), then
nothing. Ratios are percents as funds publish them ("0.015"), kept as text so they stay exact; a holding's
expense_ratio_bp is the same figure rounded half up to whole basis points, for the Plan's Mix.fee_bp."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import ExpenseRatioOverride, Holding

DATA = Path(__file__).resolve().parent.parent / "data" / "expense_ratios.json"
RATIO = re.compile(r"\d{1,2}(?:\.\d{1,3})?")
MAX_RATIO = Decimal("5")
RATIO_RULE = "Enter the fund's expense ratio as a percent, like 0.04."
SYMBOL_RULE = "Enter the fund's ticker symbol."
_NOT_SYMBOL = re.compile(r"[^A-Z0-9.\-]")


@dataclass(frozen=True)
class Fund:
    symbol: str
    name: str
    ratio_pct: Decimal
    source: str
    checked: date


def clean_symbol(raw: str | None) -> str | None:
    """' vti ' -> 'VTI', 'SPAXX**' -> 'SPAXX'. None when nothing usable is left, or it's longer than 20."""
    if not raw:
        return None
    s = _NOT_SYMBOL.sub("", raw.strip().upper())
    return s if 0 < len(s) <= 20 else None


def parse_ratio(text: object) -> Decimal:
    if not isinstance(text, str) or not RATIO.fullmatch(text.strip()):
        raise ValueError(RATIO_RULE)
    pct = Decimal(text.strip())
    if pct > MAX_RATIO:
        raise ValueError(RATIO_RULE)
    return pct


def pct_text(pct: Decimal) -> str:
    """'0.040' -> '0.04', '0' -> '0'."""
    return format(pct.normalize(), "f")


@cache
def table() -> dict[str, Fund]:
    """The table's checked entries. One whose figure wasn't verified ("checked": null) is left out, so it never shows
    as a fact."""
    raw = json.loads(DATA.read_text())
    out: dict[str, Fund] = {}
    for f in raw["funds"]:
        if f.get("checked") is None:
            continue
        out[f["symbol"]] = Fund(f["symbol"], f["name"], parse_ratio(f["ratio_pct"]), f["source"],
                                date.fromisoformat(f["checked"]))
    return out


def overrides(db: Session) -> dict[str, Decimal]:
    return {r.symbol: Decimal(r.ratio_pct) for r in db.scalars(select(ExpenseRatioOverride))}


def lookup(symbol: str | None, ovr: dict[str, Decimal]) -> tuple[Decimal | None, str | None]:
    """The lookup order: the household's override, then the table, then nothing."""
    s = clean_symbol(symbol)
    if s is None:
        return None, None
    if s in ovr:
        return ovr[s], "override"
    fund = table().get(s)
    return (fund.ratio_pct, "table") if fund is not None else (None, None)


def to_bp(pct: Decimal) -> int:
    return int((pct * 100).to_integral_value(rounding=ROUND_HALF_UP))


def yearly_cost_cents(value_cents: int, pct: Decimal) -> int:
    return int((Decimal(value_cents) * pct / 100).to_integral_value(rounding=ROUND_HALF_UP))


def fill_ratios(db: Session, holdings: Iterable[Holding]) -> None:
    ovr = overrides(db)
    for h in holdings:
        pct, _ = lookup(h.symbol, ovr)
        h.expense_ratio_bp = to_bp(pct) if pct is not None else None


def set_override(db: Session, symbol: object, ratio: object, by: int, now: datetime) -> str:
    """Save (or, with ratio None, remove) the household's ratio for a symbol, and refill every holding of it."""
    s = clean_symbol(symbol) if isinstance(symbol, str) else None
    if s is None:
        raise ValueError(SYMBOL_RULE)
    row = db.get(ExpenseRatioOverride, s)
    if ratio is None:
        if row is not None:
            db.delete(row)
    else:
        text = pct_text(parse_ratio(ratio))
        if row is None:
            db.add(ExpenseRatioOverride(symbol=s, ratio_pct=text, updated_at=now, updated_by=by))
        else:
            row.ratio_pct, row.updated_at, row.updated_by = text, now, by
    db.flush()
    held = db.scalars(select(Holding).where(func.upper(func.trim(Holding.symbol)) == s)).all()
    fill_ratios(db, held)
    db.flush()
    return s
