"""How a bank's CSV is read (import/export spec, Layout detection; P7-P9, P12, P17, P36, P37). The header is searched
for in the first 15 lines; lines above it are title lines, never kept. A file with no header is read by its cells'
shapes. The key is a hash of the normalized header (or the shapes), so the next file like it asks nothing. Everything
here is pure: it reads text in memory and returns rows, and no model sees a cell (P1)."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from steward.services.importers import dates as D
from steward.services.importers.base import ParsedRow
from steward.services.importers.decode import DECIMAL_COMMA, DELIMITERS, NO_ROWS, UNREADABLE, FileRefused
from steward.services.importers.money import parse_cents

HEADER_LINES = 15
SHAPE_ROWS = 200
DATE_CELLS = 2000            # P13 decides on at most this many of the date column's cells, spread over the file
SAMPLE_ROWS = 5
HOLD_ROWS = 10
HOLD_SHARE = 0.05
FIELDS = ("date", "description", "memo", "amount", "debit", "credit", "direction", "status", "id")
CHOOSE_AMOUNT = "Choose an amount column, or both a money-out and a money-in column."
NOT_UNDERSTOOD = "That column mapping wasn't understood."

# Matching is exact after normalization, first synonym first; a column serves one field. Columns named account
# number, card, check, category, balance or currency get no field (the last two are read for P17 and the sign).
SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("transaction date", "trans date", "date", "txn date", "datetime", "posting date", "post date",
             "posted date", "date posted", "posted", "effective date", "value date", "booking date"),
    "description": ("description", "transaction description", "payee", "name", "merchant", "merchant name",
                    "original description", "appears on your statement as", "narrative", "transaction details"),
    "memo": ("memo", "note", "notes", "extended details", "extended description", "comments"),
    "amount": ("amount", "transaction amount", "amount usd", "amount total", "net", "total"),
    "debit": ("debit", "debits", "debit amount", "amount debit", "withdrawal", "withdrawals", "withdrawal amount",
              "money out", "paid out", "charges", "outflow"),
    "credit": ("credit", "credits", "credit amount", "amount credit", "deposit", "deposits", "deposit amount",
               "money in", "paid in", "inflow"),
    "direction": ("transaction type", "type", "details", "dr cr", "debit credit", "credit debit indicator"),
    "status": ("status", "transaction status"),
    "id": ("transaction id", "id", "reference", "reference number", "ref", "fitid", "transaction number"),
}
ACCOUNT_NUMBER = frozenset({"account number", "account", "card no", "card number", "card"})
BALANCE = frozenset({"balance", "running balance", "running bal"})
OUT_WORDS = frozenset({"debit", "dr", "withdrawal", "sale", "purchase", "check", "fee", "dslip"})
IN_WORDS = frozenset({"credit", "cr", "deposit", "refund", "return"})
PENDING = frozenset({"pending", "denied", "declined", "failed", "cancelled", "canceled"})
_BALANCE_LINE = re.compile(r"^(?:beginning|ending|opening|closing|starting|previous) balance\b", re.I)
_TOTAL = re.compile(r"^(?:(?:account|grand|statement)\s+)?totals?(?:\s+(?:debits|credits|charges|payments|activity))?:?$",
                    re.I)
_DECIMAL_COMMA = re.compile(r"[-+]?\s*\$?\s*\d{1,3}(?:\.\d{3})*,\d{2}")


def norm(cell: str) -> str:
    """'Trans. Date' -> 'trans date'; 'Amount (total)' -> 'amount total' (as positions._norm)."""
    return re.sub(r"[^a-z0-9]+", " ", cell.lower()).strip()


@dataclass(frozen=True)
class Table:
    delimiter: str
    header: tuple[str, ...]                          # as written; "Column 1…n" for a headerless file
    headerless: bool
    rows: tuple[tuple[int, tuple[str, ...]], ...]    # (line number, cells); blank lines and title lines are never kept

    def column(self, i: int, limit: int | None = None) -> list[str]:
        rows = self.rows if limit is None else self.rows[:limit]
        return [cells[i] if i < len(cells) else "" for _, cells in rows]


@dataclass(frozen=True)
class Layout:
    key: str
    state: str                                       # known | builtin | remembered | new
    label: str | None
    fmt: str                                         # import_batch.format: chase_card, paypal, amex, …, or "layout"
    mapping: dict[str, int] = field(hash=False)
    negate: bool | None                              # None: the sign is asked (P10)
    date_format: str | None                          # None: the date is asked (P13)
    sign_fixed: bool = False                         # the format, debit and credit, or a direction column says it
    id: int | None = None                            # import_layout.id, for a remembered layout
    date_example: str | None = None
    date_options: tuple[str, str] | None = None

    @property
    def needs_sign(self) -> bool:
        return not self.sign_fixed and "amount" in self.mapping and "direction" not in self.mapping

    def signature(self) -> list:
        return [self.key, sorted(self.mapping.items()), self.negate, self.date_format]


@dataclass(frozen=True)
class RowError:
    row: int
    text: str


@dataclass(frozen=True)
class Parsed:
    rows: tuple[ParsedRow, ...]
    errors: tuple[RowError, ...]
    left_out: dict[str, int] = field(hash=False)
    balances: tuple[int | None, ...] = ()            # the running balance beside each row, when the file has one
    raw: tuple[int, ...] = ()                        # each row's amount before negate: the sign evidence reads these

    @property
    def held(self) -> bool:
        """P17: at most 10 unreadable rows, and at most 5% of the rows, import the good ones; more holds the file."""
        n = len(self.errors)
        return n > HOLD_ROWS or n > HOLD_SHARE * (n + len(self.rows))

    @property
    def held_text(self) -> str:
        return f"{len(self.errors)} rows can't be read. Check the columns."


# Known formats (P7): matched by their header, with their own row rules. Built-ins: matched by their exact key.
CHASE_CARD = ("Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo")
CHASE_CHECKING = ("Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #")
KNOWN: dict[str, tuple[str, dict[str, str], str]] = {
    "chase_card": ("Chase card", {"date": "Transaction Date", "description": "Description", "amount": "Amount"}, "%m/%d/%Y"),
    "chase_checking": ("Chase checking", {"date": "Posting Date", "description": "Description", "amount": "Amount"},
                       "%m/%d/%Y"),
    "paypal": ("PayPal", {"date": "Date", "description": "Name", "status": "Status", "amount": "Net",
                          "id": "Transaction ID"}, "%m/%d/%Y"),
    "venmo": ("Venmo", {"id": "ID", "date": "Datetime", "status": "Status", "memo": "Note", "amount": "Amount (total)"},
              D.ISO_DATETIME),
}


@dataclass(frozen=True)
class Builtin:
    fmt: str
    label: str
    header: tuple[str, ...]
    names: dict[str, str] = field(hash=False)
    negate: bool
    date_format: str


BUILTINS = (
    Builtin("amex", "Amex", ("Date", "Description", "Card Member", "Account #", "Amount", "Extended Details",
                             "Appears On Your Statement As", "Address", "City/State", "Zip Code", "Country", "Reference",
                             "Category"),
            {"date": "Date", "description": "Description", "amount": "Amount", "id": "Reference"}, True, "%m/%d/%Y"),
    Builtin("discover", "Discover", ("Trans. Date", "Post Date", "Description", "Amount", "Category"),
            {"date": "Trans. Date", "description": "Description", "amount": "Amount"}, True, "%m/%d/%Y"),
    Builtin("boa_card", "Bank of America", ("Posted Date", "Reference Number", "Payee", "Address", "Amount"),
            {"date": "Posted Date", "id": "Reference Number", "description": "Payee", "amount": "Amount"}, False, "%m/%d/%Y"),
    Builtin("citi", "Citi", ("Status", "Date", "Description", "Debit", "Credit"),
            {"status": "Status", "date": "Date", "description": "Description", "debit": "Debit", "credit": "Credit"},
            False, "%m/%d/%Y"),
    Builtin("capital_one", "Capital One", ("Transaction Date", "Posted Date", "Card No.", "Description", "Category",
                                           "Debit", "Credit"),
            {"date": "Transaction Date", "description": "Description", "debit": "Debit", "credit": "Credit"}, False,
            "%Y-%m-%d"),
    Builtin("capital_one_360", "Capital One 360", ("Account Number", "Transaction Description", "Transaction Date",
                                                   "Transaction Type", "Transaction Amount", "Balance"),
            {"description": "Transaction Description", "date": "Transaction Date", "direction": "Transaction Type",
             "amount": "Transaction Amount"}, False, "%m/%d/%y"),
)


def _hkey(cells) -> str:
    return "h:" + hashlib.sha256("\x1f".join(norm(c) for c in cells).encode()).hexdigest()


def _index(header, name: str) -> int | None:
    want = norm(name)
    return next((i for i, c in enumerate(header) if norm(c) == want), None)


def _by_names(header, names: dict[str, str]) -> dict[str, int]:
    return {f: i for f, n in names.items() if (i := _index(header, n)) is not None}


_BUILTIN_BY_KEY = {_hkey(b.header): b for b in BUILTINS}


def _records(text: str, d: str) -> list[tuple[int, list[str]]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=d)
    try:
        return [(reader.line_num, [c.strip() for c in cells]) for cells in reader]
    except csv.Error:
        raise FileRefused(UNREADABLE) from None


def _data(recs) -> tuple[tuple[int, tuple[str, ...]], ...]:
    return tuple((n, tuple(cells)) for n, cells in recs if any(cells))


def _guess(cells: list[str]) -> dict[str, int]:
    used: set[int] = set()
    out: dict[str, int] = {}
    for f in FIELDS:
        for syn in SYNONYMS[f]:
            i = next((i for i, n in enumerate(cells) if n == syn and i not in used), None)
            if i is not None:
                out[f] = i
                used.add(i)
                break
    return out


def _usable(m: dict[str, int]) -> bool:
    return "date" in m and "description" in m and ("amount" in m or ("debit" in m and "credit" in m))


def _known(cells: list[str]) -> str | None:
    if cells == [norm(c) for c in CHASE_CARD]:
        return "chase_card"
    if cells == [norm(c) for c in CHASE_CHECKING]:
        return "chase_checking"
    s = set(cells)
    if {"gross", "fee", "net", "transaction id"} <= s:
        return "paypal"
    if {"id", "datetime", "amount total"} <= s:
        return "venmo"
    return None


def _is_header(cells: list[str]) -> bool:
    n = [norm(c) for c in cells]
    return len(cells) > 1 and (_known(n) is not None or _usable(_guess(n)))


def cell_cents(s: str) -> int:
    """parse_cents, plus a trailing minus ("64.18-")."""
    s = s.strip()
    if s.endswith("-") and not s.startswith(("-", "+")):
        s = "-" + s[:-1].strip()
    return parse_cents(s)


def _is_date(c: str) -> bool:
    if not any(ch.isdigit() for ch in c):
        return False
    for f in D.CANDIDATES:
        try:
            D.parse_day(c, f)
            return True
        except ValueError:
            continue
    return False


def _is_amount(c: str) -> bool:
    try:
        cell_cents(c)
        return True
    except ValueError:
        return False


def _is_data(cells: list[str]) -> bool:
    """A record shaped like a transaction: more than one cell, one a date and another an amount."""
    return len(cells) > 1 and any(_is_date(c) for c in cells) and any(_is_amount(c) and not _is_date(c) for c in cells)


def read_table(text: str) -> Table:
    text = text.lstrip("﻿")
    if not text.strip():
        raise FileRefused(NO_ROWS)
    head = "".join(text.splitlines(keepends=True)[:HEADER_LINES])
    for d in DELIMITERS:
        try:
            recs = _records(head, d)
        except FileRefused:
            continue
        for i, (_, cells) in enumerate(recs):
            if _is_header(cells):
                full = _records(text, d)
                rows = _data(full[i + 1:])
                if not rows:
                    raise FileRefused(NO_ROWS)
                return Table(d, tuple(full[i][1]), False, rows)
    for d in DELIMITERS:
        # A header whose names guess too little ("Run Date,Payee Name,Amount") is still a header when a data row
        # follows it: the confirm maps it once (P12). A line that is itself data is left to the headerless check.
        try:
            recs = _records(head, d)
            full = _records(text, d)
        except FileRefused:
            continue
        for i, (_, cells) in enumerate(recs):
            if not any(cells) or _is_data(cells) or not (len(cells) > 1 or _guess([norm(c) for c in cells])):
                continue
            after = next((c for _, c in full[i + 1:] if any(c)), None)
            if after is not None and _is_data(after):
                return Table(d, tuple(full[i][1]), False, _data(full[i + 1:]))
    for d in DELIMITERS:
        try:
            recs = _records(head, d)
        except FileRefused:
            continue
        first = next((cells for _, cells in recs if any(cells)), None)
        if first and _is_data(first):
            rows = _data(_records(text, d))
            width = max(len(c) for _, c in rows[:SHAPE_ROWS])
            return Table(d, tuple(f"Column {n}" for n in range(1, width + 1)), True, rows)
    raise FileRefused(UNREADABLE)


@dataclass(frozen=True)
class Shape:
    """Spec, Shape features: per column, from at most the first 200 data rows. P1's later model would see only these."""
    date_share: float
    amount_share: float
    minus_share: float
    parens_share: float
    positive_share: float
    empty_share: float
    distinct: int
    mean_length: float

    @property
    def length(self) -> str:
        m = self.mean_length
        return "0-4" if m <= 4 else "5-12" if m <= 12 else "13-40" if m <= 40 else "over 40"

    @property
    def letter(self) -> str:
        if self.empty_share == 1:
            return "e"
        if self.date_share >= 0.95:
            return "d"
        if self.amount_share >= 0.95:
            return "a"
        return "t" if self.mean_length >= 5 else "s"


def shapes(table: Table) -> list[Shape]:
    out = []
    for i in range(len(table.header)):
        cells = table.column(i, SHAPE_ROWS)
        full = [c for c in cells if c]
        n = len(full) or 1
        amounts = []
        for c in full:
            try:
                amounts.append(cell_cents(c))
            except ValueError:
                continue
        out.append(Shape(
            date_share=sum(_is_date(c) for c in full) / n, amount_share=len(amounts) / n,
            minus_share=sum(c.startswith("-") or c.endswith("-") for c in full) / n,
            parens_share=sum(c.startswith("(") and c.endswith(")") for c in full) / n,
            positive_share=(sum(a > 0 for a in amounts) / len(amounts)) if amounts else 0.0,
            empty_share=(len(cells) - len(full)) / (len(cells) or 1), distinct=len(set(full)),
            mean_length=sum(len(c) for c in full) / n))
    return out


def layout_key(table: Table) -> str:
    if table.headerless:
        return f"n:{len(table.header)}:" + "".join(s.letter for s in shapes(table))
    return _hkey(table.header)


def _guess_by_shape(table: Table) -> dict[str, int]:
    sh = shapes(table)
    out: dict[str, int] = {}
    day = next((i for i, s in enumerate(sh) if s.date_share >= 0.95), None)
    if day is not None:
        out["date"] = day
    amounts = [i for i, s in enumerate(sh) if s.amount_share >= 0.95 and i != day]
    if amounts:
        out["amount"] = max(amounts, key=lambda i: sh[i].distinct)
    texts = [i for i, s in enumerate(sh) if s.letter == "t" and i not in out.values()]
    if texts:
        out["description"] = max(texts, key=lambda i: sh[i].mean_length)
    return out


def _get(cells: tuple[str, ...], i: int | None) -> str:
    return cells[i].strip() if i is not None and i < len(cells) else ""


def _direction_ok(table: Table, m: dict[str, int]) -> bool:
    """Spec: a Type column counts only when every amount is 0 or more and every row's value is a known word."""
    words = OUT_WORDS | IN_WORDS
    for _, cells in table.rows:
        amount = _get(cells, m.get("amount"))
        if not amount:
            continue
        try:
            if cell_cents(amount) < 0:
                return False
        except ValueError:
            return False
        if norm(_get(cells, m["direction"])) not in words:
            return False
    return True


def _date_cells(table: Table, i: int) -> list[str]:
    cells = table.column(i)
    step = max(1, len(cells) // DATE_CELLS)
    return cells[::step]


def _best(cells: list[str]) -> str | None:
    """For a column no format reads 98% of: the format that reads the most, so the unreadable rows are counted and
    the file is held (P17) rather than every row failing."""
    cells = [c for c in cells if c.strip()]
    scored = [(sum(_reads(c, f) for c in cells), -k, f) for k, f in enumerate(D.CANDIDATES)]
    n, _, f = max(scored, default=(0, 0, None))
    return f if n else None


def _reads(c: str, f: str) -> bool:
    try:
        D.parse_day(c, f)
        return True
    except ValueError:
        return False


def date_format_for(table: Table, column: int) -> str | None:
    """The date format for a column the person chose in the confirm (P13), worked out as guess() does. Where month
    first and day first both read every cell, it takes month first (today's reading); None when nothing reads."""
    cells = _date_cells(table, column)
    choice = D.choose(cells)
    if choice.format is not None:
        return choice.format
    if choice.options is not None:
        return choice.options[0]
    return _best(cells)


def guess(table: Table, key: str) -> Layout:
    m = _guess_by_shape(table) if table.headerless else _guess([norm(c) for c in table.header])
    if "direction" in m and not _direction_ok(table, m):
        del m["direction"]
    choice = D.choose(_date_cells(table, m["date"])) if "date" in m else D.DateChoice(None)
    fmt = choice.format
    if fmt is None and choice.example is None and "date" in m:
        fmt = _best(_date_cells(table, m["date"]))
    fixed = "direction" in m or ("amount" not in m and "debit" in m and "credit" in m)
    return Layout(key, "new", None, "layout", m, False if fixed else None, fmt, sign_fixed=fixed,
                  date_example=choice.example, date_options=choice.options)


def remembered(key: str, header, row_id: int, label: str, mapping: dict[str, int], negate: bool,
               date_format: str) -> Layout:
    fixed = "direction" in mapping or ("amount" not in mapping and "debit" in mapping and "credit" in mapping)
    return Layout(key, "remembered", label, "layout", dict(mapping), False if fixed else negate, date_format,
                  sign_fixed=fixed, id=row_id)


def identify(table: Table, key: str, remembered: Layout | None = None) -> Layout:
    """Spec, Order: a known format, then a remembered layout, then a built-in, then a new one (P7, P14)."""
    known = None if table.headerless else _known([norm(c) for c in table.header])
    if known is not None:
        label, names, fmt = KNOWN[known]
        return Layout(key, "known", label, known, _by_names(table.header, names), False, fmt, sign_fixed=True)
    if remembered is not None:
        return remembered
    b = _BUILTIN_BY_KEY.get(key)
    if b is not None:
        return Layout(key, "builtin", b.label, b.fmt, _by_names(b.header, b.names), b.negate, b.date_format,
                      sign_fixed=True)
    return guess(table, key)


def check_amounts(table: Table, layout: Layout) -> None:
    cols = [layout.mapping[f] for f in ("amount", "debit", "credit") if f in layout.mapping]
    cells = [c for i in cols for c in table.column(i, SHAPE_ROWS) if c]
    if cells and 2 * sum(1 for c in cells if _DECIMAL_COMMA.fullmatch(c)) >= len(cells):
        raise FileRefused(DECIMAL_COMMA)


class _NoAmount(ValueError):
    pass


def _cents(s: str) -> int:
    try:
        return cell_cents(s)
    except ValueError:
        raise ValueError(s) from None


def _amount(cells: tuple[str, ...], m: dict[str, int]) -> int:
    if "amount" in m:
        s = _get(cells, m["amount"])
        if not s:
            raise _NoAmount()
        cents = _cents(s)
        if "direction" in m:
            cents = -abs(cents) if norm(_get(cells, m["direction"])) in OUT_WORDS else abs(cents)
        return cents
    out, inn = _get(cells, m.get("debit")), _get(cells, m.get("credit"))
    if not out and not inn:
        raise _NoAmount()
    # The column says which way the money moved, so any sign in it is ignored (today's rule).
    return (abs(_cents(inn)) if inn else 0) - (abs(_cents(out)) if out else 0)


def parse(table: Table, layout: Layout, today: date) -> Parsed:
    m = layout.mapping
    header = [norm(c) for c in table.header]
    bal = None if table.headerless else next((i for i, n in enumerate(header) if n in BALANCE), None)
    cur = None if table.headerless else next((i for i, n in enumerate(header) if n == "currency"), None)
    venmo, paypal = layout.fmt == "venmo", layout.fmt == "paypal"
    frm, to = (_index(table.header, "From"), _index(table.header, "To")) if venmo else (None, None)
    kind = _index(table.header, "Type") if paypal else None
    fmt = layout.date_format or (layout.date_options[0] if layout.date_options else "")
    last = today + timedelta(days=1)
    rows: list[ParsedRow] = []
    raw: list[int] = []
    balances: list[int | None] = []
    ids: list[str] = []
    errors: list[RowError] = []
    left: Counter = Counter()
    for line, cells in table.rows:
        if venmo and not _get(cells, m.get("id")):
            left["balance"] += 1                        # Venmo's beginning and ending balance rows have no ID
            continue
        if "status" in m and _get(cells, m["status"]).lower() in PENDING:
            left["pending"] += 1
            continue
        desc = _get(cells, m.get("description"))
        if paypal and not desc:
            desc = _get(cells, kind)
        if _BALANCE_LINE.match(desc):
            left["balance"] += 1
            continue
        if _TOTAL.match(desc) or _TOTAL.match(_get(cells, m.get("date"))):
            left["totals"] += 1
            continue
        currency = _get(cells, cur)
        if currency and currency.upper() != "USD":
            left["currency"] += 1
            continue
        day = _get(cells, m.get("date"))
        try:
            if not fmt:
                raise ValueError(day)                   # no date column or format yet: strptime("", "") is Jan 1 1900
            posted = D.parse_day(day, fmt)
        except ValueError:
            errors.append(RowError(line, f'Row {line}: the date "{day}" isn\'t a date.'))
            continue
        if posted > last:
            errors.append(RowError(line, f"Row {line}: the date is in the future."))
            continue
        try:
            cents = _amount(cells, m)
        except _NoAmount:
            errors.append(RowError(line, f"Row {line}: this row has no amount."))
            continue
        except ValueError as e:
            errors.append(RowError(line, f'Row {line}: the amount "{e.args[0]}" isn\'t a dollar amount.'))
            continue
        raw.append(cents)
        if layout.negate:
            cents = -cents
        if venmo:
            desc = _get(cells, to if cents < 0 else frm)
        memo = _get(cells, m.get("memo"))
        if memo and memo != desc:
            desc = f"{desc} — {memo}" if desc else memo
        rows.append(ParsedRow(posted, cents, desc, None))
        ids.append(_get(cells, m.get("id")))
        if bal is not None:
            try:
                balances.append(cell_cents(_get(cells, bal)))
            except ValueError:
                balances.append(None)
    if "id" in m and rows and all(ids) and len(set(ids)) == len(ids):   # P37
        rows = [replace(r, external_id="csv:" + i.lstrip("'")) for r, i in zip(rows, ids)]
    return Parsed(tuple(rows), tuple(errors), dict(left), tuple(balances), tuple(raw))


def _mask(cell: str) -> str:
    digits = re.sub(r"\D", "", cell)
    return f"••••{digits[-4:]}" if digits else cell


def sample(table: Table, n: int = SAMPLE_ROWS) -> list[list[str]]:
    """P36: cells under an account or card number header are masked."""
    masked = {i for i, c in enumerate(table.header) if norm(c) in ACCOUNT_NUMBER}
    return [[_mask(c) if i in masked else c for i, c in enumerate(cells)] for _, cells in table.rows[:n]]


def account_digits(table: Table) -> str | None:
    """The last 4 digits of the account-number column, when every row has the same ones (for P5's suggestion)."""
    cols = [i for i, c in enumerate(table.header) if norm(c) in ACCOUNT_NUMBER]
    if not cols:
        return None
    lasts = {re.sub(r"\D", "", c)[-4:] for c in table.column(cols[0]) if re.sub(r"\D", "", c)}
    return lasts.pop() if len(lasts) == 1 else None


def mapping_from(value: object, width: int) -> dict[str, int]:
    """A layout the person confirmed (the confirm's selects), checked against the file's columns."""
    if not isinstance(value, dict):
        raise ValueError(NOT_UNDERSTOOD)
    out: dict[str, int] = {}
    for f, i in value.items():
        if f not in FIELDS or isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < width:
            raise ValueError(NOT_UNDERSTOOD)
        out[f] = i
    if len(set(out.values())) != len(out) or "date" not in out or "description" not in out:
        raise ValueError(NOT_UNDERSTOOD)
    if not _usable(out):
        raise ValueError(CHOOSE_AMOUNT)
    return out
