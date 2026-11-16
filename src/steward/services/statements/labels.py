"""One matcher for a layout's labels (spec P16, P18). Validation (validate.py) and reading (rules.py) both call it, so
a label is applied exactly as it was validated: against the child's masked cells (the text the model saw), whitespace
runs collapsed, case kept (ruling F5), at word boundaries (an edge that is a letter or digit can't touch another), and
only when it holds at least 3 letters and normalizes to something, so "a", ":" or "ate" (inside "Date") never match.

Steward's own never-row phrases (rules.NEVER) and the header-cell search (rules.header_cells, which validation also
uses) aren't model labels matched here; the fingerprint (layouts.py) only picks a remembered layout, whose labels are
then applied here."""
from __future__ import annotations

import re
from functools import lru_cache

from steward.services.statements.extract import line_text, norm

MIN_LETTERS = 3


def squash(text: str) -> str:
    return " ".join(text.split())


def short(label: str) -> bool:
    """Fewer than 3 letters, or nothing left after normalizing: never a label."""
    return sum(ch.isalpha() for ch in label) < MIN_LETTERS or not norm(label)


@lru_cache(maxsize=512)
def _pattern(label: str) -> re.Pattern:
    s = squash(label)
    return re.compile(("(?<!\\w)" if re.match(r"\w", s[0]) else "") + re.escape(s)
                      + ("(?!\\w)" if re.match(r"\w", s[-1]) else ""))


def occurs(label: str, text: str) -> bool:
    """The label is in the text, whole."""
    return not short(label) and _pattern(label).search(squash(text)) is not None


def starts(label: str, text: str) -> bool:
    """The text starts with the label, whole."""
    return not short(label) and _pattern(label).match(squash(text)) is not None


def fills_cell(label: str, line: dict) -> bool:
    return not short(label) and any(squash(c["text"]) == squash(label) for c in line["cells"])


def opens(label: str, line: dict) -> bool:
    """A skip label's rule: it starts the line or is one of its cells."""
    return starts(label, line_text(line)) or fills_cell(label, line)


def after(label: str, line: dict) -> str:
    """The line's text after the label's first whole occurrence; the whole line when it isn't there."""
    text = squash(line_text(line))
    m = None if short(label) else _pattern(label).search(text)
    return text[m.end():] if m else text


def find(label: str, lines: list[dict]) -> int | None:
    """P18's fact line: the first line the label starts, else the first that holds it."""
    texts = [line_text(ln) for ln in lines]
    hit = next((i for i, t in enumerate(texts) if starts(label, t)), None)
    return hit if hit is not None else next((i for i, t in enumerate(texts) if occurs(label, t)), None)
