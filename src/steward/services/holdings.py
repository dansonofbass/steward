"""Holdings (investment views spec, Holdings): an account's positions for a day, from SimpleFIN or a positions CSV.
Saving a day replaces that day's rows for the account and keeps the other days; the page shows the newest day. The mix
bar's classes follow asset_classes (the household's overrides, then the built-ins); a target-date fund splits by its
glide path, its stocks TARGET_DATE_US_SHARE in the US."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from steward.db.models import Holding
from steward.services import asset_classes as ac
from steward.services.costs import clean_symbol, fill_ratios

BAR: tuple[str, ...] = ("us_stock", "intl_stock", "bond", "cash", "other")
# Vanguard Target Retirement funds hold about 60% of their stocks in Total Stock Market and 40% in Total International
# Stock (each fund's published allocation; checked in Task 3, Step 5).
TARGET_DATE_US_SHARE = 0.6


@dataclass(frozen=True)
class Position:
    symbol: str | None
    name: str
    shares_milli: int
    value_cents: int
    cost_basis_cents: int | None = None


def replace_holdings(db: Session, account_id: int, as_of: date, positions: Sequence[Position],
                     import_id: int | None = None) -> list[Holding]:
    db.execute(delete(Holding).where(Holding.account_id == account_id, Holding.as_of == as_of))
    rows = []
    for p in positions:
        symbol = clean_symbol(p.symbol)
        rows.append(Holding(account_id=account_id, as_of=as_of, symbol=symbol, name=(p.name.strip() or symbol or "")[:200],
                            shares_milli=p.shares_milli, cost_basis_cents=p.cost_basis_cents,
                            market_value_cents=p.value_cents, import_id=import_id))
    db.add_all(rows)
    fill_ratios(db, rows)
    db.flush()
    return rows


def newest(db: Session, account_id: int) -> list[Holding]:
    day = db.scalar(select(func.max(Holding.as_of)).where(Holding.account_id == account_id))
    if day is None:
        return []
    return list(db.scalars(select(Holding).where(Holding.account_id == account_id, Holding.as_of == day)
                           .order_by(Holding.market_value_cents.desc(), Holding.id)))


def bar_parts(symbol: str | None, class_overrides: dict[str, str], year: int) -> list[tuple[str, float]]:
    s = clean_symbol(symbol)
    if s is None:
        return [("other", 1.0)]
    cls = class_overrides.get(s) or ac.BUILTIN.get(s)
    if cls:
        return [(cls, 1.0)]
    if s in ac.TARGET_DATE:
        stock = ac.glide_stock_share(ac.TARGET_DATE[s], year)
        return [("us_stock", stock * TARGET_DATE_US_SHARE), ("intl_stock", stock * (1 - TARGET_DATE_US_SHARE)),
                ("bond", 1.0 - stock)]
    return [("other", 1.0)]


def mix_bar(holdings: Iterable[Holding], class_overrides: dict[str, str], year: int) -> list[dict]:
    totals = dict.fromkeys(BAR, 0.0)
    for h in holdings:
        if h.market_value_cents <= 0:
            continue
        for cls, share in bar_parts(h.symbol, class_overrides, year):
            totals[cls] += h.market_value_cents * share
    return [{"class": c, "cents": round(v)} for c, v in totals.items() if round(v) > 0]
