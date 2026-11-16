"""Regular-expression detectors for the shapes Presidio's pattern recognizers find: email, phone, US SSN, card numbers
with Luhn, ABA routing numbers with their checksum, IBAN, dates next to "born", "DOB" or "birthday", and long digit
runs as account numbers. Used in tests in place of Presidio (ruling 8). The date-of-birth pattern and the PIN,
password or code rule are the boundary's own (steward_boundary.text.DOB_RE, preflight ruling 6; secret_edits), so the
exact pass, the text rule and this detector agree."""
from __future__ import annotations

import re

from steward_boundary.text import DOB_RE as DOB
from steward_boundary.text import secret_edits
from steward_gateway.redact import Span

EMAIL = re.compile(r"[\w.+%'-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w])")
SSN = re.compile(r"(?<![\w])\d{3}[\s-]\d{2}[\s-]\d{4}(?![\w])")
CARD = re.compile(r"(?<![\w])\d(?:[\s-]?\d){12,18}(?![\w])")
ROUTING = re.compile(r"(?<![\w])\d{9}(?![\w])")
IBAN = re.compile(r"(?<![\w])[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?(?![\w])")
LONG = re.compile(r"(?<![\w])\d(?:[\s-]?\d){7,}(?![\w])")  # no upper bound: a capped run left its tail bare


def luhn(digits: str) -> bool:
    total, odd = 0, True
    for ch in reversed(digits):
        d = int(ch)
        if not odd:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        odd = not odd
    return total % 10 == 0


def aba(digits: str) -> bool:
    d = [int(c) for c in digits]
    return len(d) == 9 and (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class PatternDetector:
    name = "presidio"

    def detect(self, text: str) -> list[Span]:
        # Every match is returned, overlapping or not, as Presidio's recognizers do; redact() merges overlaps into one
        # edit covering all of them. (Task 8.5: dropping a match that overlapped an earlier, narrower one left the
        # rest of a number in the text: "900-12-3456-7890-12" became "[ssn]-7890-12".) On equal spans the earlier
        # pattern's label wins, so the order below is the order of preference.
        out: list[Span] = []

        def add(start: int, end: int, label: str) -> None:
            out.append(Span(start, end, label, "presidio"))
        for m in EMAIL.finditer(text):
            add(m.start(), m.end(), "[email]")
        for m in DOB.finditer(text):
            add(m.start(1), m.end(1), "[date of birth]")
        for m in IBAN.finditer(text):
            add(m.start(), m.end(), "[iban]")
        for m in CARD.finditer(text):
            if luhn(_digits(m.group())):
                add(m.start(), m.end(), "[card number]")
        for m in SSN.finditer(text):
            add(m.start(), m.end(), "[ssn]")
        for m in PHONE.finditer(text):
            add(m.start(), m.end(), "[phone]")
        for m in ROUTING.finditer(text):
            if aba(m.group()):
                add(m.start(), m.end(), "[routing number]")
        for m in LONG.finditer(text):
            add(m.start(), m.end(), "[account number]")
        return out + secrets(text)


def secrets(text: str) -> list[Span]:
    """A PIN, password or code next to its word (steward_boundary.text.secret_edits), as spans on `text`. `text` is
    the detectors' canonical view, which is already plain, so the rule's edits are on it as they stand."""
    return [Span(e.start, e.end, e.label, "presidio") for e in secret_edits(text)]
