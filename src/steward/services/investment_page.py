"""One investment account's page as JSON (investment views spec, The investment account page): what the bank sends,
this year's three figures, the chart's series, what it's invested in with its costs, and, for a retirement account,
the contributions against the year's limit. A read only: nothing here writes."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from steward.db.models import RETIREMENT_TYPES, Account, Holding, PositionsImport, Source
from steward.services import asset_classes as ac
from steward.services import contributed, costs, growth, holdings, limits
from steward.services.accounts import latest_balance
from steward.services.plan_inputs import latest_facts


def _ratio(h: Holding, ovr: dict[str, Decimal]) -> tuple[Decimal | None, str | None]:
    pct, src = costs.lookup(h.symbol, ovr)
    if pct is None and h.expense_ratio_bp is not None:   # a row written before this phase
        return Decimal(h.expense_ratio_bp) / 100, "stored"
    return pct, src


def _holdings_out(db: Session, a: Account, today: date) -> dict | None:
    hs = holdings.newest(db, a.id)
    if not hs:
        return None
    ovr = costs.overrides(db)
    rows, known, unknown = [], 0, 0
    for h in hs:
        pct, src = _ratio(h, ovr)
        cost = costs.yearly_cost_cents(h.market_value_cents, pct) if pct is not None else None
        if cost is None:
            unknown += 1
        else:
            known += cost
        rows.append({"id": h.id, "symbol": h.symbol, "name": h.name, "value_cents": h.market_value_cents,
                     "ratio_pct": costs.pct_text(pct) if pct is not None else None, "ratio_from": src, "cost_cents": cost})
    imp_id = next((h.import_id for h in hs if h.import_id is not None), None)
    imp = db.get(PositionsImport, imp_id) if imp_id is not None else None
    statement = imp is not None and imp.source in ("pdf", "pdf_scan")
    return {"as_of": hs[0].as_of.isoformat(), "source": "statement" if statement else "import" if imp else "feed",
            "statement_month": f"{imp.as_of:%b} {imp.as_of.year}" if statement else None,
            "filename": imp.filename if imp and not statement else None,
            "rows": rows, "total_cents": sum(h.market_value_cents for h in hs),
            "mix": holdings.mix_bar(hs, ac.overrides(db), today.year), "unknown": unknown, "known_cost_cents": known}


def investment_out(db: Session, a: Account, today: date) -> dict:
    c = contributed.this_year(db, a, today, latest_facts(db))
    year = growth.year_figures(db, a, today, c)
    since, points = growth.series(db, a, today, c)
    held = _holdings_out(db, a, today)
    advisory = all_in = None
    if a.advisory_fee_bp is not None:
        base = held["total_cents"] if held else (latest_balance(db, a.id) or (today, 0))[1]
        advisory = {"fee_bp": a.advisory_fee_bp, "cost_cents": (max(0, base) * a.advisory_fee_bp + 5_000) // 10_000}
    if held and (held["unknown"] < len(held["rows"]) or advisory):
        cents = held["known_cost_cents"] + (advisory["cost_cents"] if advisory else 0)
        total = held["total_cents"]
        all_in = {"cents": cents, "pct": f"{cents * 100 / total:.2f}" if total > 0 else "0.00"}
    contrib = None
    if a.type in RETIREMENT_TYPES:
        line = contributed.line_for(contributed.limit_lines(db, today), a.id)
        contrib = {"this_year": contributed.contributed_out(c), "line": contributed.line_out(line) if line else None,
                   "missing": not limits.have_year(today.year)}
    connected = a.source == Source.simplefin
    return {
        "account_id": a.id, "type": a.type.value, "institution": a.institution.name if connected else a.name,
        "manual": a.source == Source.manual,
        "sends": {"holdings": a.holdings_seen_at is not None, "transactions": a.transactions_seen_at is not None}
        if connected else None,
        "year": year.out() if year else None, "since": since.isoformat() if since else None, "series": points,
        "holdings": held, "advisory": advisory, "all_in": all_in, "contributions": contrib,
    }
