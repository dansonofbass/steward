"""Statement amounts (spec P18; "What's there today"): importers.money.parse_cents reads a leading sign, $ and
parentheses; a statement also prints a trailing minus ("12.40-") and CR/DR ("12.40 CR"). CSV parsing doesn't change.
DR is a debit, which on a card is money owed: positive."""
from __future__ import annotations

import re

from steward_boundary.statements_wire import MAX_CENTS

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}"
TOKEN = re.compile(rf"\(?[+-]?\s?\$?\s?[+-]?{_NUM}\)?(?:\s?(?:CR|DR)\b|-(?!\d))?", re.I)
_FULL = re.compile(rf"(?P<s1>[+-])?\s*\$?\s*(?P<s2>[+-])?\s*(?P<num>{_NUM})\s*(?P<suf>-|CR|DR)?", re.I)


def parse_amount(text: str | None) -> int | None:
    """Cents from one printed amount, or None when it isn't one."""
    if text is None:
        return None
    s = text.strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    m = _FULL.fullmatch(s)
    if m is None:
        return None
    cents = int(m["num"].replace(",", "").replace(".", ""))
    if cents > MAX_CENTS:
        return None
    if "-" in (m["s1"], m["s2"]) or (m["suf"] or "").upper() in ("-", "CR"):
        neg = True
    return -cents if neg else cents


def amounts(text: str) -> list[int]:
    """Every amount printed in a line, left to right."""
    return [v for m in TOKEN.finditer(text) if (v := parse_amount(m.group(0))) is not None]
