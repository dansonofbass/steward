"""Asset mix for each engine bucket (spec 2.5): holdings through asset classes, a built-in table of common
index and target-date funds, the household's overrides, and a default by account type for anything unknown."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, AssetClass, Holding
from steward.engine import Mix

CASH_MIX = Mix(0.0, 0.0, 1.0)
TAXABLE_DEFAULT = Mix(0.6, 0.4, 0.0)
RETIREMENT_DEFAULT = Mix(0.7, 0.3, 0.0)
CASH_TYPES = frozenset({AccountType.checking, AccountType.savings})
CLASS_MIX = {"us_stock": Mix(1.0, 0.0, 0.0), "intl_stock": Mix(1.0, 0.0, 0.0), "bond": Mix(0.0, 1.0, 0.0), "cash": Mix(0.0, 0.0, 1.0)}

_US = ("VTI VTSAX VOO VFIAX VV VUG VTV VB VO VXF VIG FXAIX FSKAX FZROX FNILX SWTSX SWPPX ITOT IVV SPY SCHB SCHX SCHD")
_INTL = "VXUS VTIAX VEA VWO IXUS IEFA IEMG FTIHX FSPSX FZILX SCHF SWISX"
_BOND = "BND VBTLX AGG FXNAX SCHZ BNDX VTABX VGIT VGSH BSV BIV SWAGX"
_CASH = "VMFXX VUSXX SPAXX FDRXX FZFXX SPRXX SWVXX"
BUILTIN: dict[str, str] = {
    **{s: "us_stock" for s in _US.split()}, **{s: "intl_stock" for s in _INTL.split()},
    **{s: "bond" for s in _BOND.split()}, **{s: "cash" for s in _CASH.split()},
}
# Vanguard Target Retirement funds; 0 = the Income fund (past its glide path).
TARGET_DATE: dict[str, int] = {
    "VTINX": 0, "VTTVX": 2025, "VTHRX": 2030, "VTTHX": 2035, "VFORX": 2040, "VTIVX": 2045,
    "VFIFX": 2050, "VFFVX": 2055, "VTTSX": 2060, "VLXVX": 2065, "VSVNX": 2070,
}


def glide_stock_share(target_year: int, year: int) -> float:
    """90% stock until 25 years out, 50% at the target year, 30% seven years after it and from then on."""
    if target_year == 0:
        return 0.30
    left = target_year - year
    if left >= 25:
        return 0.90
    if left >= 0:
        return 0.50 + 0.40 * left / 25
    if left >= -7:
        return 0.30 + 0.20 * (left + 7) / 7
    return 0.30


def target_date_mix(target_year: int, year: int) -> Mix:
    stock = glide_stock_share(target_year, year)
    return Mix(stock, 1.0 - stock, 0.0)


def resolve(symbol: str | None, overrides: Mapping[str, str], plan_year: int) -> tuple[Mix | None, str]:
    if not symbol:
        return None, "default"
    s = symbol.strip().upper()
    if s in overrides:
        return CLASS_MIX[overrides[s]], "override"
    if s in BUILTIN:
        return CLASS_MIX[BUILTIN[s]], "builtin"
    if s in TARGET_DATE:
        return target_date_mix(TARGET_DATE[s], plan_year), "builtin"
    return None, "default"


def default_mix(account_type: AccountType) -> Mix:
    if account_type in CASH_TYPES:
        return CASH_MIX
    if account_type == AccountType.brokerage_taxable:
        return TAXABLE_DEFAULT
    return RETIREMENT_DEFAULT


def _mix(stock: float, bond: float, cash: float, fee: float) -> Mix:
    total = stock + bond + cash
    return Mix(stock / total, bond / total, cash / total, fee_bp=int(round(fee)))


@dataclass(frozen=True)
class AccountMix:
    mix: Mix
    unknown: tuple[str, ...]   # symbols (or fund names, for a holding without one) on the default mix
    no_holdings: bool


def account_mix(holdings: Sequence[Holding], account_type: AccountType, overrides: Mapping[str, str], plan_year: int) -> AccountMix:
    if account_type in CASH_TYPES:
        return AccountMix(CASH_MIX, (), False)
    fallback = default_mix(account_type)
    held = [h for h in holdings if h.market_value_cents > 0]
    if not held:
        return AccountMix(fallback, (), True)
    total = sum(h.market_value_cents for h in held)
    stock = bond = cash = fee = 0.0
    unknown: list[str] = []
    for h in held:
        w = h.market_value_cents / total
        mix, _ = resolve(h.symbol, overrides, plan_year)
        if mix is None:
            mix = fallback
            unknown.append(h.symbol.strip().upper() if h.symbol else h.name)
        stock += w * mix.stock
        bond += w * mix.bond
        cash += w * mix.cash
        fee += w * (h.expense_ratio_bp or 0)
    return AccountMix(_mix(stock, bond, cash, fee), tuple(dict.fromkeys(unknown)), False)


def blend(parts: Sequence[tuple[int, Mix]], fallback: Mix) -> Mix:
    weighted = [(w, m) for w, m in parts if w > 0]
    total = sum(w for w, _ in weighted)
    if total <= 0:
        return fallback
    return _mix(sum(w * m.stock for w, m in weighted) / total, sum(w * m.bond for w, m in weighted) / total,
                sum(w * m.cash for w, m in weighted) / total, sum(w * m.fee_bp for w, m in weighted) / total)


def latest_holdings(db: Session) -> dict[int, list[Holding]]:
    newest = (select(Holding.account_id, func.max(Holding.as_of).label("as_of"))
              .group_by(Holding.account_id).subquery())
    rows = db.scalars(select(Holding)
                      .join(newest, (newest.c.account_id == Holding.account_id) & (newest.c.as_of == Holding.as_of))
                      .order_by(Holding.account_id, Holding.id)).all()
    out: dict[int, list[Holding]] = {}
    for h in rows:
        out.setdefault(h.account_id, []).append(h)
    return out


def overrides(db: Session) -> dict[str, str]:
    return {r.symbol: r.asset_class for r in db.scalars(select(AssetClass).where(AssetClass.source == "override"))}


def symbol_rows(db: Session, plan_year: int) -> list[dict]:
    ovr = overrides(db)
    names = dict(db.execute(select(Account.id, Account.name)).all())
    seen: dict[str, dict] = {}
    for aid, hs in latest_holdings(db).items():
        for h in hs:
            if not h.symbol:
                continue
            row = seen.setdefault(h.symbol.strip().upper(), {"name": h.name, "accounts": []})
            if names[aid] not in row["accounts"]:
                row["accounts"].append(names[aid])
    for s in ovr:
        seen.setdefault(s, {"name": None, "accounts": []})
    out = []
    for s, row in seen.items():
        mix, source = resolve(s, ovr, plan_year)
        cls = ovr.get(s) or BUILTIN.get(s) or ("target_date" if s in TARGET_DATE else None)
        out.append({"symbol": s, **row, "class": cls, "source": source,
                    "mix": None if mix is None else {"stock": round(mix.stock, 4), "bond": round(mix.bond, 4), "cash": round(mix.cash, 4)}})
    out.sort(key=lambda r: (r["source"] != "default", r["symbol"]))
    return out
