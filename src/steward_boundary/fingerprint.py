"""Identifier fingerprints (spec 4.5, check 4; ruling 4). The NAS sends, once per turn, salted SHA-256 hashes of the
book's known identifiers; the gateway hashes every window of 1 to 5 tokens of every outgoing string with the same salt
and stops on a match. The gateway never sees the identifiers. Numbers are compared by their digits joined, so spacing
and dashes don't matter.

Hardened in Task 2.5 (the Task 5 security review): tokens come from the canonical normal form (normal.view), the
same one the exact pass (known.py) matches on, so a variant spelling can't match one and miss the other. Each text
is tokenised twice: as written, and with words parted at hidden breaks (camel case, a dropped zero-width space, a
letter against a digit). A run of digit tokens longer than a window is also joined, so "7 1 4 5 5 5 0 1 0 2" is a
phone number; and the digits of an identifier that mixes words and a long number are a form of their own."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator, Sequence

from steward_boundary.normal import View, view
from steward_boundary.text import spelled_digits
from steward_boundary.vocab import GENERIC_WORDS, generic

WINDOW = 5
RUN_LIMIT = 40                 # digit tokens joined at most, so a long list of numbers stays cheap
_TOKEN = re.compile(r"[^\W_]+")


def token_spans(v: View) -> list[tuple[str, int, int]]:
    """The tokens of a view's normal form with their offsets in it."""
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(v.norm)]


def tokens(text: str, *, split: bool = False) -> list[str]:
    return [t for t, _, _ in token_spans(view(text, split=split))]


def canon(toks: Sequence[str]) -> str:
    return "".join(toks) if toks and all(t.isdigit() for t in toks) else " ".join(toks)


def digest(salt: str, text: str) -> str:
    return hashlib.sha256(f"{salt}\x00{text}".encode()).hexdigest()


def digit_runs(toks: Sequence[str]) -> Iterator[tuple[int, int]]:
    i = 0
    while i < len(toks):
        if toks[i].isdigit():
            j = i
            while j < len(toks) and toks[j].isdigit():
                j += 1
            yield i, j
            i = j
        else:
            i += 1


def windows(toks: Sequence[str]) -> Iterator[tuple[int, int, str]]:
    """Every form a text's tokens can take, with the tokens it spans: each window of 1 to 5 tokens, and each stretch
    of more than 5 digit tokens in a row, joined. The fingerprint scan and the exact pass both use this."""
    for size in range(1, WINDOW + 1):
        for i in range(len(toks) - size + 1):
            yield i, i + size, canon(toks[i:i + size])
    for i, j in digit_runs(toks):
        for a in range(i, j):
            for b in range(a + WINDOW + 1, min(j, a + RUN_LIMIT) + 1):
                yield a, b, "".join(toks[a:b])


def _forms(toks: list[str], name: bool) -> set[str]:
    if not toks:
        return set()
    if all(t.isdigit() for t in toks):
        if len("".join(toks)) <= 4:          # 4 digits are allowed to leave (a last 4)
            return set()
    elif generic(toks):
        return set()
    if len(toks) <= WINDOW:
        forms = {canon(toks)}
    else:
        forms = {canon(toks[i:i + WINDOW]) for i in range(len(toks) - WINDOW + 1)}
    forms |= {j for i, k in digit_runs(toks) if len(j := "".join(toks[i:k])) > 4}
    if name:
        forms |= {t for t in toks if len(t) >= 3 and not t.isdigit() and t not in GENERIC_WORDS}
    return forms


def identifier_forms(identifier: str, *, name: bool) -> set[str]:
    return _forms(tokens(identifier), name) | _forms(tokens(identifier, split=True), name)


def hashes_for(identifiers: Iterable[tuple[str, bool]], salt: str) -> set[str]:
    return {digest(salt, f) for text, is_name in identifiers for f in identifier_forms(text, name=is_name)}


def string_forms(text: str) -> Iterator[str]:
    for split in (False, True):
        for _, _, form in windows(tokens(text, split=split)):
            yield form
    # A number spelled out in words ("nine zero zero ...") is a number too: every stretch of 5 or more of its digits,
    # the way a run of digit tokens is joined (privacy approach review, 2026-10-24).
    for digits in spelled_digits(view(text).norm):
        for a in range(len(digits)):
            for b in range(a + 5, min(len(digits), a + RUN_LIMIT) + 1):
                yield digits[a:b]


def scan(strings: Iterable[tuple[str, str]], salt: str, hashes: set[str] | frozenset[str]) -> str | None:
    if not hashes:
        return None
    for path, text in strings:
        for form in string_forms(text):
            if digest(salt, form) in hashes:
                return path
    return None
