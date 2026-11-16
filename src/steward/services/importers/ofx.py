import html
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from steward.services.importers.base import ParseError, ParsedRow
from steward.services.importers.layouts import RowError
from steward.services.importers.money import parse_cents

_TRN = (re.compile(r"<STMTTRN>", re.I), re.compile(r"</STMTTRN>", re.I))
_STMT = (re.compile(r"<(CC)?STMTRS>", re.I), re.compile(r"</(?:CC)?STMTRS>", re.I))
_TAG = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)", re.I)


def _blocks(text: str, tags: tuple[re.Pattern, re.Pattern]) -> Iterator[tuple[re.Match, str]]:
    """Each opening tag, and the text from it to the next closing tag. Found by searching forward, never with a
    `.*?` span, so the time grows in step with the text (SEC-3): with one, every unclosed opening tag scanned to the
    end of the file. Once no closing tag is left, no later opening tag has one either."""
    opening, closing = tags
    pos = 0
    while (start := opening.search(text, pos)) is not None:
        end = closing.search(text, start.end())
        if end is None:
            return
        yield start, text[start.end():end.start()]
        pos = end.end()


def _fields(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag, value in _TAG.findall(block):
        out.setdefault(tag.upper(), html.unescape(value.strip()))  # first occurrence wins
    return out


def _date(s: str) -> date:
    digits = re.match(r"\d{8}", s.strip())
    if not digits:
        raise ValueError(s)
    d = digits.group(0)
    return date(int(d[:4]), int(d[4:6]), int(d[6:8]))


def _error(n: int, reason: str) -> ParseError:
    err = ParseError(n, reason)
    err.args = (f"Transaction {n}: {reason}" if n else reason,)  # n counts transactions, not lines
    return err


def _row(i: int, f: dict[str, str]) -> ParsedRow:
    if "DTPOSTED" not in f:
        raise _error(i, "this transaction is missing its date (DTPOSTED).")
    if "TRNAMT" not in f:
        raise _error(i, "this transaction is missing its amount (TRNAMT).")
    try:
        posted = _date(f["DTPOSTED"])
    except ValueError:
        raise _error(i, f"the date {f['DTPOSTED']!r} isn't a date.") from None
    try:
        cents = parse_cents(f["TRNAMT"])
    except ValueError:
        raise _error(i, f"the amount {f['TRNAMT']!r} isn't a dollar amount.") from None
    name = f.get("NAME", "").strip()
    memo = f.get("MEMO", "").strip()
    desc = name if not memo or memo == name else f"{name} — {memo}" if name else memo
    return ParsedRow(posted, cents, desc, f.get("FITID") or None)


def parse_ofx(text: str) -> list[ParsedRow]:
    """Parse OFX/QFX text. For this parser ParseError.row is the 1-based transaction
    number, not a line number; 0 means the file has no transactions at all."""
    rows = [_row(i, _fields(block)) for i, (_, block) in enumerate(_blocks(text, _TRN), start=1)]
    if not rows:
        raise _error(0, "No transactions were found in this OFX/QFX file.")
    return rows


@dataclass(frozen=True)
class Statement:
    """One account's part of an OFX/QFX file (import/export spec P21). The account number is never kept: only its
    last 4 characters, for the line's name and the hint key ("ofx:<ORG or BANKID>:<last 4>", P5)."""
    last4: str | None
    hint_key: str | None
    card: bool
    rows: tuple[ParsedRow, ...]
    errors: tuple[RowError, ...]


def _first(text: str, tag: str) -> str:
    m = re.search(rf"<{re.escape(tag)}>([^<\r\n]*)", text, re.I)
    return m.group(1).strip() if m else ""


def statements(text: str) -> list[Statement]:
    org, bid = _first(text, "ORG"), _first(text, "INTU.BID")
    blocks = [(bool(m.group(1)), block) for m, block in _blocks(text, _STMT)] or [(False, text)]
    out: list[Statement] = []
    for card, block in blocks:
        last4 = _first(block, "ACCTID")[-4:] or None
        bank = org or _first(block, "BANKID") or bid
        rows: list[ParsedRow] = []
        errors: list[RowError] = []
        for i, (_, trn) in enumerate(_blocks(block, _TRN), start=1):
            try:
                rows.append(_row(i, _fields(trn)))
            except ParseError as e:
                errors.append(RowError(i, str(e)))
        out.append(Statement(last4, f"ofx:{bank}:{last4}" if bank and last4 else None, card, tuple(rows),
                             tuple(errors)))
    return out
