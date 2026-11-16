"""Known identifiers in free text (spec 4.3, Task 2.5): the matcher the NAS's exact pass uses, and its post-check.

It matches on the canonical normal form with the same tokens and the same forms as the fingerprint scan
(fingerprint.windows, fingerprint.identifier_forms), so the exact pass and the gateway's fingerprints reach the same
verdict on every spelling of an identifier (tests/boundary/test_known.py holds them to it). Edits refer to the view's
plain text. survivors() is the final post-check: after every edit, no known identifier may be left."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from steward_boundary.fingerprint import digit_runs, identifier_forms, token_spans, tokens, windows
from steward_boundary.normal import View, as_view, split_view, view
from steward_boundary.spans import Edit, merge


@dataclass(frozen=True)
class Known:
    text: str                  # the identifier as the book stores it
    replacement: str           # what replaces it: an alias, or a bracket token
    name: bool = False         # a person's name: each part of 3 or more letters is matched alone too


def forms_table(knowns: Iterable[Known]) -> dict[str, str]:
    """Each form of each identifier and its replacement; the first identifier to claim a form keeps it."""
    table: dict[str, str] = {}
    for k in knowns:
        for form in sorted(identifier_forms(k.text, name=k.name)):
            table.setdefault(form, k.replacement)
    return table


def _widen(plain: str, start: int, end: int) -> int:
    """Take in an opening parenthesis whose closing one is inside the match: "(714) 555-0102" goes whole."""
    inside = plain[start:end]
    if start > 0 and plain[start - 1] == "(" and ")" in inside and ("(" not in inside or inside.index(")") < inside.index("(")):
        return start - 1
    return start


def find_known(text: str | View, knowns: Sequence[Known] | dict[str, str]) -> list[Edit]:
    """Edits (layer "steward") that replace every known identifier in the text, merged. A string must already be
    plain; a view may come from raw text, and then hidden breaks (a zero-width space between two words) count."""
    v = as_view(text)
    table = knowns if isinstance(knowns, dict) else forms_table(knowns)
    if not table:
        return []
    edits = []
    for w in (v, split_view(v)):
        spans = token_spans(w)
        for i, j, form in windows([t for t, _, _ in spans]):
            label = table.get(form)
            if label is not None:
                start, end = w.to_plain(spans[i][1], spans[j - 1][2])
                edits.append(Edit(_widen(w.plain, start, end), end, label, "steward"))
    return merge(edits)


def survivors(text: str, knowns: Sequence[Known] | dict[str, str]) -> list[tuple[int, int]]:
    """Where a known identifier is still in `text` (any text, raw or not), in its plain form's offsets. The exact
    pass must end with this empty, or refuse to send."""
    return [(e.start, e.end) for e in find_known(view(text), knowns)]


def known_digits(knowns: Iterable[Known]) -> frozenset[str]:
    """The long numbers in the known identifiers (5 digits or more, joined), for the text rule's `known`."""
    out = set()
    for k in knowns:
        toks = tokens(k.text)
        out |= {d for i, j in digit_runs(toks) if len(d := "".join(toks[i:j])) > 4}
    return frozenset(out)
