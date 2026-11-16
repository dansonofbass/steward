"""The statement reader's wire contract (PDF statements spec P12-P16, P21, P29): what the NAS sends the gateway for a new
layout and what may come back. The NAS and the gateway both import it, as both import vocab for the categorizer (plan
Engineering choice 1). Labels and limits only: nothing here reads a table or holds a page, and no advisor or turn
module imports it (tests/advisor/test_tools_never_read_notes.py)."""
from __future__ import annotations

import math
import zlib
from typing import NamedTuple

KINDS = ("bank", "card", "investment", "retirement", "loan")
TABLE_FIELDS = ("date", "post_date", "description", "amount", "debit", "credit", "balance", "ignore")
WAYS = ("in", "out", "signed", "skip")
NEGATIVE = ("minus", "parens", "trailing_minus", "cr")
# The import round's candidates without "%Y%m%d" and "iso-datetime", plus the four short forms (Engineering choice 2).
# The order is the NAS's trial order: month-first before day-first, so a US date never reads day-first.
MONTH_FIRST = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y")
ISO = ("%Y-%m-%d", "%Y/%m/%d")
WORDS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d-%b-%Y")
SHORT = ("%m/%d", "%m-%d", "%b %d", "%d %b")
DAY_FIRST = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%d.%m.%y")
DATE_FORMATS = MONTH_FIRST + ISO + WORDS + SHORT + DAY_FIRST

MAX_PAGES = 4                 # P13: page 1 plus the first 3 pages with transactions
MAX_LINES = 150               # across those pages
MAX_CELLS = 16                # a line
MAX_CELL = 120                # characters a cell
MAX_PAGE_N = 60
MAX_POINTS = 5000.0           # a page's side, and any x or y
MAX_LABEL = 120
MAX_INSTITUTION = 60
MAX_COLUMNS = 16
MAX_SECTIONS = 12
MAX_SKIP = 20
MAX_HINT_LINES = 20
MAX_HINT_LINE = 300
MAX_CENTS = 10**13

_STR = {"type": "string"}
_NSTR = {"type": ["string", "null"]}
_LABEL = {"type": "object", "properties": {"label": _STR}, "required": ["label"]}
TABLE_SCHEMA = {"type": "object", "properties": {
    "columns": {"type": "array", "items": {"type": "object", "properties": {
        "header": _STR, "field": {"type": "string", "enum": list(TABLE_FIELDS)}}, "required": ["header", "field"]}},
    "date_format": {"type": "string", "enum": list(DATE_FORMATS)},
    "negative": {"type": "string", "enum": list(NEGATIVE)},
    "sections": {"type": "array", "items": {"type": "object", "properties": {
        "title": _STR, "way": {"type": "string", "enum": list(WAYS)}, "total_label": _NSTR},
        "required": ["title", "way", "total_label"]}},
    "skip": {"type": "array", "items": _STR}},
    "required": ["columns", "date_format", "negative", "sections", "skip"]}
HOLDING_FIELDS = ("symbol", "name", "shares", "price", "value", "cost_basis", "ignore")
MAX_CASH = 3
HOLD_SCHEMA = {"type": "object", "properties": {
    "columns": {"type": "array", "items": {"type": "object", "properties": {
        "header": _STR, "field": {"type": "string", "enum": list(HOLDING_FIELDS)}}, "required": ["header", "field"]}},
    "total_label": _STR, "cash_labels": {"type": "array", "items": _STR}, "ending": _LABEL},
    "required": ["columns", "total_label", "cash_labels", "ending"]}
LAYOUT_SCHEMA = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": list(KINDS)},
    "institution": _STR, "account_label": _STR, "account_marker": _NSTR,
    "period": {"type": "object", "properties": {"label": _STR, "date_format": {"type": "string", "enum": list(DATE_FORMATS)}},
               "required": ["label", "date_format"]},
    "opening": _LABEL, "closing": _LABEL,
    "table": {"anyOf": [TABLE_SCHEMA, {"type": "null"}]},
    "holdings": {"anyOf": [HOLD_SCHEMA, {"type": "null"}]}},
    "required": ["kind", "institution", "account_label", "account_marker", "period", "opening", "closing", "table",
                 "holdings"]}

_TOP = {"kind", "institution", "account_label", "account_marker", "period", "opening", "closing", "table", "holdings"}
_TABLE = {"columns", "date_format", "negative", "sections", "skip"}


def _text(v, n: int = MAX_LABEL) -> bool:
    return isinstance(v, str) and bool(v.strip()) and len(v) <= n and v.isprintable()


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and abs(v) <= MAX_CENTS


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= MAX_POINTS


def _holdings_errors(h) -> list[str]:
    if h is None:
        return []
    if not isinstance(h, dict) or set(h) != {"columns", "total_label", "cash_labels", "ending"}:
        return ["holdings"]
    cols = h["columns"]
    if not isinstance(cols, list) or not 2 <= len(cols) <= MAX_COLUMNS or not all(
            isinstance(c, dict) and set(c) == {"header", "field"} and _text(c.get("header"))
            and c.get("field") in HOLDING_FIELDS for c in cols):
        return ["holdings columns"]
    cash = h["cash_labels"]
    if not _text(h["total_label"]) or not isinstance(cash, list) or len(cash) > MAX_CASH or not all(_text(x) for x in cash):
        return ["holdings labels"]
    e = h["ending"]
    return [] if isinstance(e, dict) and set(e) == {"label"} and _text(e["label"]) else ["holdings ending"]


def shape_errors(p) -> list[str]:
    """P15, P16's strict part: exactly the schema's keys, the enums, the lengths and the counts. Labels against the page
    are the NAS's check (validate.py), which has the lines."""
    if not isinstance(p, dict):
        return ["not an object"]
    errs: list[str] = []
    if set(p) != _TOP:
        errs.append("keys")
    if p.get("kind") not in KINDS:
        errs.append("kind")
    if not _text(p.get("institution"), MAX_INSTITUTION):
        errs.append("institution")
    if not _text(p.get("account_label")):
        errs.append("account_label")
    if p.get("account_marker") is not None and not _text(p.get("account_marker")):
        errs.append("account_marker")
    period = p.get("period")
    if not isinstance(period, dict) or set(period) != {"label", "date_format"} or not _text(period.get("label")) \
            or period.get("date_format") not in DATE_FORMATS:
        errs.append("period")
    for k in ("opening", "closing"):
        v = p.get(k)
        if not isinstance(v, dict) or set(v) != {"label"} or not _text(v.get("label")):
            errs.append(k)
    errs += _holdings_errors(p.get("holdings"))
    t = p.get("table")
    if t is None:
        return errs
    if not isinstance(t, dict) or set(t) != _TABLE:
        return [*errs, "table"]
    cols = t.get("columns")
    if not isinstance(cols, list) or not 2 <= len(cols) <= MAX_COLUMNS or not all(
            isinstance(c, dict) and set(c) == {"header", "field"} and _text(c.get("header"))
            and c.get("field") in TABLE_FIELDS for c in cols):
        errs.append("columns")
    if t.get("date_format") not in DATE_FORMATS:
        errs.append("date_format")
    if t.get("negative") not in NEGATIVE:
        errs.append("negative")
    secs = t.get("sections")
    if not isinstance(secs, list) or not 1 <= len(secs) <= MAX_SECTIONS or not all(
            isinstance(s, dict) and set(s) == {"title", "way", "total_label"} and _text(s.get("title"))
            and s.get("way") in WAYS and (s.get("total_label") is None or _text(s.get("total_label"))) for s in secs):
        errs.append("sections")
    skip = t.get("skip")
    if not isinstance(skip, list) or len(skip) > MAX_SKIP or not all(_text(s) for s in skip):
        errs.append("skip")
    return errs


def pages_errors(pages) -> list[str]:
    """P13's request: 1-4 pages, 150 lines in all, 16 cells a line, 120 characters a cell, finite positions."""
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        return ["pages"]
    lines = 0
    for pg in pages:
        if not isinstance(pg, dict) or set(pg) != {"n", "width", "height", "lines"}:
            return ["page"]
        if not _int(pg["n"]) or not 1 <= pg["n"] <= MAX_PAGE_N or not _num(pg["width"]) or not _num(pg["height"]):
            return ["page"]
        if not isinstance(pg["lines"], list):
            return ["lines"]
        lines += len(pg["lines"])
        for ln in pg["lines"]:
            if not isinstance(ln, dict) or set(ln) != {"y", "cells"} or not _num(ln["y"]) \
                    or not isinstance(ln["cells"], list) or not 1 <= len(ln["cells"]) <= MAX_CELLS:
                return ["line"]
            for c in ln["cells"]:
                if not isinstance(c, dict) or set(c) != {"x0", "x1", "text"} or not _num(c["x0"]) or not _num(c["x1"]) \
                        or not isinstance(c["text"], str) or not 0 < len(c["text"]) <= MAX_CELL:
                    return ["cell"]
    return ["lines"] if lines > MAX_LINES else []


def hint_errors(hint) -> list[str]:
    """P21's retry hint: the gap, each section's sum against its printed total, the failing lines, the first proposal."""
    if hint is None:
        return []
    if not isinstance(hint, dict) or set(hint) != {"gap_cents", "sections", "lines", "previous"} or not _int(hint["gap_cents"]):
        return ["hint"]
    secs, lines = hint["sections"], hint["lines"]
    if not isinstance(secs, list) or len(secs) > MAX_SECTIONS or not all(
            isinstance(s, dict) and set(s) == {"title", "sum_cents", "total_cents"} and _text(s["title"])
            and _int(s["sum_cents"]) and (s["total_cents"] is None or _int(s["total_cents"])) for s in secs):
        return ["hint sections"]
    if not isinstance(lines, list) or len(lines) > MAX_HINT_LINES or not all(_text(x, MAX_HINT_LINE) for x in lines):
        return ["hint lines"]
    return ["hint previous"] if shape_errors(hint["previous"]) else []


# ---------------------------------------------------------------- a scanned page (P25, P26, P29)
PAGE_KINDS = ("transactions", "holdings", "summary", "other")
ROW_WAYS = ("in", "out", "unknown")
WANTS = ("rows", "holdings")
MAX_PAGE_ROWS = 150
MAX_PAGE_HOLDINGS = 40
MAX_VALUE = 200
MAX_PNG = 3 * 1024 * 1024
MAX_PNG_SIDE = 2400
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PERIOD = {"anyOf": [{"type": "object", "properties": {"start": _STR, "end": _STR}, "required": ["start", "end"]},
                     {"type": "null"}]}
PAGE_SCHEMA = {"type": "object", "properties": {
    "page_kind": {"type": "string", "enum": list(PAGE_KINDS)},
    "institution": _NSTR, "account_last4": _NSTR, "period": _PERIOD, "opening": _NSTR, "closing": _NSTR,
    "rows": {"type": "array", "items": {"type": "object", "properties": {
        "date": _STR, "description": _STR, "amount": _STR, "way": {"type": "string", "enum": list(ROW_WAYS)},
        "section": _NSTR}, "required": ["date", "description", "amount", "way", "section"]}},
    "holdings": {"type": "array", "items": {"type": "object", "properties": {
        "symbol": _NSTR, "name": _STR, "shares": _NSTR, "value": _STR}, "required": ["symbol", "name", "shares", "value"]}},
    "total": _NSTR},
    "required": ["page_kind", "institution", "account_last4", "period", "opening", "closing", "rows", "holdings", "total"]}
_PAGE_KEYS = set(PAGE_SCHEMA["required"])


def _value(v, n: int = MAX_VALUE, empty: bool = False) -> bool:
    return isinstance(v, str) and len(v) <= n and (empty or bool(v.strip())) and v.isprintable()


def _maybe(v, n: int = MAX_VALUE) -> bool:
    return v is None or _value(v, n)


class PngHeader(NamedTuple):
    width: int
    height: int
    depth: int
    colour: int
    compression: int
    filter: int
    interlace: int


def png_header(raw: bytes) -> PngHeader | None:
    """A PNG's IHDR, read from the bytes and never decoded: the signature, then a first chunk that is IHDR, exactly 13
    bytes long, with its CRC right; None for anything else."""
    if len(raw) < 33 or not raw.startswith(PNG_SIGNATURE) or raw[8:12] != b"\x00\x00\x00\x0d" or raw[12:16] != b"IHDR":
        return None
    if zlib.crc32(raw[12:29]) != int.from_bytes(raw[29:33], "big"):
        return None
    w, h = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    return PngHeader(w, h, *raw[24:29]) if w > 0 and h > 0 else None


def png_size(raw: bytes) -> tuple[int, int] | None:
    """A PNG's width and height from its header (png_header); never decodes the image."""
    head = png_header(raw)
    return (head.width, head.height) if head is not None else None


def page_request_errors(body) -> list[str]:
    if not isinstance(body, dict) or set(body) != {"page", "of", "image", "width_px", "height_px", "want"}:
        return ["page request"]
    n, of, w, h = body["page"], body["of"], body["width_px"], body["height_px"]
    if not all(_int(v) for v in (n, of, w, h)) or not 1 <= n <= of <= MAX_PAGE_N:
        return ["page numbers"]
    if not (0 < w <= MAX_PNG_SIDE and 0 < h <= MAX_PNG_SIDE) or body["want"] not in WANTS:
        return ["page size or want"]
    return [] if isinstance(body["image"], str) and len(body["image"]) <= (MAX_PNG * 4) // 3 + 4 else ["image"]


def page_answer_errors(a) -> list[str]:
    """P25's strict shape: the schema's keys, enums, at most 150 rows and 40 holdings, every value at most 200
    characters, the last 4 as four digits."""
    if not isinstance(a, dict) or set(a) != _PAGE_KEYS:
        return ["keys"]
    errs = []
    if a["page_kind"] not in PAGE_KINDS:
        errs.append("page_kind")
    if not _maybe(a["institution"], MAX_INSTITUTION):
        errs.append("institution")
    last4 = a["account_last4"]
    if last4 is not None and not (isinstance(last4, str) and len(last4) == 4 and last4.isdigit()):
        errs.append("account_last4")
    p = a["period"]
    if p is not None and not (isinstance(p, dict) and set(p) == {"start", "end"} and _value(p["start"]) and _value(p["end"])):
        errs.append("period")
    if not all(_maybe(a[k], 40) for k in ("opening", "closing", "total")):
        errs.append("balances")
    rows = a["rows"]
    if not isinstance(rows, list) or len(rows) > MAX_PAGE_ROWS or not all(
            isinstance(r, dict) and set(r) == {"date", "description", "amount", "way", "section"}
            and _value(r["date"], 40) and _value(r["description"]) and _value(r["amount"], 40) and r["way"] in ROW_WAYS
            and _maybe(r["section"]) for r in rows):
        errs.append("rows")
    hs = a["holdings"]
    if not isinstance(hs, list) or len(hs) > MAX_PAGE_HOLDINGS or not all(
            isinstance(x, dict) and set(x) == {"symbol", "name", "shares", "value"} and _maybe(x["symbol"], 20)
            and _value(x["name"]) and _maybe(x["shares"], 40) and _value(x["value"], 40) for x in hs):
        errs.append("holdings")
    return errs
