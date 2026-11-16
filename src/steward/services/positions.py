"""Positions from a CSV (investment views spec, From a positions CSV): Betterment's, a 401(k) site's or a brokerage's
export. The columns are guessed from their names and confirmed once; then they're remembered per institution (per
account for one entered by hand, since those share the Manual institution), so the next file asks nothing. Rows
without a value, totals rows and pending activity are skipped. Saving replaces the account's holdings for the chosen
day. The file is read in memory and never kept; only its name is, for the page's source line."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, Holding, PositionsImport, PositionsMapping, Source
from steward.services.accounts import latest_balance
from steward.services.costs import clean_symbol
from steward.services.holdings import Position, replace_holdings
from steward.services.importers.csv_formats import read_rows

Mapping = dict[str, str | None]
FIELDS = ("symbol", "name", "shares", "value", "cost_basis")
GUESSES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "ticker", "ticker symbol", "fund symbol"),
    "name": ("name", "description", "security", "security name", "security description", "fund name", "investment",
             "investment name", "holding"),
    "shares": ("shares", "quantity", "qty", "units", "share balance", "shares held"),
    "value": ("value", "market value", "current value", "total value", "ending value", "ending balance"),
    "cost_basis": ("cost basis", "cost basis total", "total cost basis", "cost"),
}
TOTAL_CELL = re.compile(r"^(?:(?:account|grand|portfolio)\s+)?totals?:?$", re.I)
PENDING_CELL = re.compile(r"^pending\b", re.I)
MAX_CENTS = 10**13  # beyond this a figure is unreadable (SQLite ints are 64-bit)
MAX_SHARES_MILLI = 10**15
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")
MAX_POSITIONS = 2000
HEADER_LINES = 10
TOO_MANY = "That file has more than 2,000 rows. Export one account's positions and try again."
NO_POSITIONS = "No positions with a value were found in that file."
CHOOSE_COLUMNS = "Choose the value column, and a symbol or a name column."
MAPPING_NOT_UNDERSTOOD = "That column mapping wasn't understood."


def _norm(header: str) -> str:
    """'Market Value ($)' -> 'market value'."""
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def guess_mapping(header: list[str]) -> Mapping:
    norm = {h: _norm(h) for h in header}
    return {field: next((h for name in names for h in header if norm[h] == name), None) for field, names in GUESSES.items()}


def usable(m: Mapping, header: list[str]) -> bool:
    return bool(m.get("value")) and bool(m.get("symbol") or m.get("name")) and all(v in header for v in m.values() if v)


def mapping_from(raw: str | None) -> Mapping | None:
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        raise ValueError(MAPPING_NOT_UNDERSTOOD) from None
    if not isinstance(d, dict) or not set(d) <= set(FIELDS) or not all(v is None or isinstance(v, str) for v in d.values()):
        raise ValueError(MAPPING_NOT_UNDERSTOOD)
    return {f: (d.get(f) or None) for f in FIELDS}


def from_header(text: str) -> str:
    """Drop a title above the header (Schwab's "Positions for account …" line): the header is the first of the first
    HEADER_LINES lines whose cells guess a value column and a symbol or name column."""
    lines = text.lstrip("\ufeff").splitlines(keepends=True)
    for i, line in enumerate(lines[:HEADER_LINES]):
        try:
            cells = next(csv.reader([line]), [])
        except csv.Error:
            continue
        m = guess_mapping([c.strip() for c in cells])
        if m["value"] and (m["symbol"] or m["name"]):
            return "".join(lines[i:])
    return text


def _amount(text: str) -> int | None:
    """'$1,234.5678' -> 123457 (half up); '(12.00)' -> -1200; '', '--' or 'n/a' -> None."""
    s = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    if s and s[0] in "+-":
        neg, s = neg or s[0] == "-", s[1:]
    if not _NUMBER.fullmatch(s):
        return None
    cents = int((Decimal(s) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    if cents > MAX_CENTS:
        return None
    return -cents if neg else cents


def _shares(text: str) -> int:
    s = text.strip().replace(",", "")
    neg = s[:1] == "-"
    if s[:1] in ("+", "-"):
        s = s[1:]
    if not _NUMBER.fullmatch(s):
        return 0
    milli = int((Decimal(s) * 1000).to_integral_value(rounding=ROUND_HALF_UP))
    if milli > MAX_SHARES_MILLI:
        return 0
    return -milli if neg else milli


def _skipped(*cells: str) -> bool:
    return any(TOTAL_CELL.match(c.strip()) or PENDING_CELL.match(c.strip()) for c in cells if c and c.strip())


def parse_positions(text: str, m: Mapping) -> tuple[list[Position], int]:
    _, rows = read_rows(text)
    if len(rows) > MAX_POSITIONS:
        raise ValueError(TOO_MANY)
    out: list[Position] = []
    skipped = 0
    for _, r in rows:
        raw_symbol = r.get(m["symbol"], "") if m["symbol"] else ""
        name = (r.get(m["name"], "") if m["name"] else "").strip()
        symbol = clean_symbol(raw_symbol)
        value = _amount(r.get(m["value"], "") or "")
        if value is None or _skipped(raw_symbol, name) or not (symbol or name):
            skipped += 1
            continue
        basis = _amount(r.get(m["cost_basis"], "") or "") if m["cost_basis"] else None
        shares = _shares(r.get(m["shares"], "") or "") if m["shares"] else 0
        out.append(Position(symbol, name or symbol or "", shares, value, basis))
    return out, skipped


def mapping_key(account: Account) -> str:
    return f"inst:{account.institution_id}" if account.source == Source.simplefin else f"acct:{account.id}"


def _remembered(db: Session, account: Account) -> Mapping | None:
    row = db.get(PositionsMapping, mapping_key(account))
    return mapping_from(row.mapping) if row is not None else None


def _remember(db: Session, account: Account, m: Mapping, now: datetime) -> None:
    key, text = mapping_key(account), json.dumps(m, sort_keys=True)
    row = db.get(PositionsMapping, key)
    if row is None:
        db.add(PositionsMapping(key=key, mapping=text, updated_at=now))
    else:
        row.mapping, row.updated_at = text, now


def _position_out(p: Position) -> dict:
    return {"symbol": p.symbol, "name": p.name, "shares_milli": p.shares_milli, "value_cents": p.value_cents,
            "cost_basis_cents": p.cost_basis_cents}


def preview(db: Session, account: Account, text: str, mapping: Mapping | None) -> dict:
    body = from_header(text)
    header, rows = read_rows(body)
    remembered = _remembered(db, account) if mapping is None else None
    m = mapping if mapping is not None else (remembered if remembered and usable(remembered, header) else None)
    if m is None:
        return {"needs_mapping": True, "remembered": False, "headers": header, "mapping": guess_mapping(header),
                "sample": [[row.get(h, "") for h in header] for _, row in rows[:5]]}
    if not usable(m, header):
        raise ValueError(CHOOSE_COLUMNS)
    found, skipped = parse_positions(body, m)
    if not found:
        raise ValueError(NO_POSITIONS)
    total = sum(p.value_cents for p in found)
    bal = latest_balance(db, account.id)
    return {"needs_mapping": False, "remembered": mapping is None, "headers": header, "mapping": m,
            "count": len(found), "total_cents": total, "skipped": skipped,
            "balance_cents": bal[1] if bal else None, "balance_as_of": bal[0].isoformat() if bal else None,
            "difference_cents": total - bal[1] if bal else None, "positions": [_position_out(p) for p in found]}


def commit(db: Session, account: Account, text: str, filename: str, mapping: Mapping | None, as_of: date, by: int,
           now: datetime) -> dict:
    body = from_header(text)
    header, _ = read_rows(body)
    if mapping is None or not usable(mapping, header):
        raise ValueError(CHOOSE_COLUMNS)
    found, _ = parse_positions(body, mapping)
    if not found:
        raise ValueError(NO_POSITIONS)
    first = db.scalar(select(Holding.id).where(Holding.account_id == account.id).limit(1)) is None
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1][:200] or "positions.csv"
    imp = PositionsImport(account_id=account.id, as_of=as_of, filename=name, row_count=len(found), imported_at=now,
                          imported_by=by)
    db.add(imp)
    db.flush()
    replace_holdings(db, account.id, as_of, found, import_id=imp.id)
    _remember(db, account, mapping, now)
    db.flush()
    return {"count": len(found), "total_cents": sum(p.value_cents for p in found), "as_of": as_of.isoformat(), "first": first}
