"""The one canonical normaliser (Task 2.5; spec 4.3, 4.5, 11.1). Every layer that matches text uses it: protected
aliases, the text rule, the exact pass (known.py), fingerprints and the date-of-birth rule. The stages, in order:

1. plain: NFKC, with invisible format characters (zero-width spaces and joiners, soft hyphens, direction marks)
   dropped. This is the text that is sent, and every edit refers to it.
2. fold: look-alike Cyrillic and Greek letters to Latin, every dash to "-", every decimal digit to ASCII. One
   character for one, so offsets don't move.
3. casefold, with accents dropped ("Straße" is "strasse", "Zoë" is "zoe").
4. separators collapsed: each run of whitespace becomes one space, and the ends are cut.

view() returns the plain text, the normal text and a map from each normal character back to the plain character it
came from, so a layer matches on the normal text and makes its edits on the plain text. With split=True the view
also parts words where the plain text hid a break: at a dropped invisible character, between a lower-case and an
upper-case letter, and between a letter and a digit ("MargaretEllis", "Margaret<ZWSP>ellis", "Acct123456")."""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass

# Cyrillic and Greek letters that look like Latin ones (spec 11.1, "homoglyphs"), by code point.
_LOOKALIKES = {c: latin for c, latin in (
    (0x430, "a"), (0x435, "e"), (0x43E, "o"), (0x440, "p"), (0x441, "c"), (0x443, "y"), (0x445, "x"), (0x456, "i"),
    (0x458, "j"), (0x455, "s"), (0x501, "d"), (0x4BB, "h"), (0x4CF, "l"), (0x410, "A"), (0x412, "B"), (0x415, "E"),
    (0x41A, "K"), (0x41C, "M"), (0x41D, "H"), (0x41E, "O"), (0x420, "P"), (0x421, "C"), (0x422, "T"), (0x425, "X"),
    (0x406, "I"), (0x408, "J"), (0x405, "S"), (0x3B1, "a"), (0x3BF, "o"), (0x3C1, "p"), (0x3B5, "e"), (0x3B9, "i"),
    (0x3BA, "k"), (0x3BD, "v"), (0x3C4, "t"), (0x3C5, "u"), (0x3C7, "x"), (0x391, "A"), (0x392, "B"), (0x395, "E"),
    (0x396, "Z"), (0x397, "H"), (0x399, "I"), (0x39A, "K"), (0x39C, "M"), (0x39D, "N"), (0x39F, "O"), (0x3A1, "P"),
    (0x3A4, "T"), (0x3A5, "Y"), (0x3A7, "X"))}


class _FoldTable(dict):
    """str.translate's table, filled in as characters are first seen (scanning all of Unicode at import is slow)."""

    def __missing__(self, cp: int):
        c = chr(cp)
        if cp in _LOOKALIKES:
            out: int | str = _LOOKALIKES[cp]
        elif cp == 0x2212 or unicodedata.category(c) == "Pd":
            out = "-"
        elif c.isdigit() and unicodedata.digit(c, None) is not None:
            out = str(unicodedata.digit(c))
        else:
            out = cp
        self[cp] = out
        return out


_FOLD = _FoldTable({cp: cp for cp in range(128)})


def plain(text: str) -> str:
    """NFKC, with invisible format characters (zero-width spaces and joiners, direction marks) dropped."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")


def fold(text: str) -> str:
    """Look-alike letters to Latin, dashes to "-", digits to ASCII, one character for one, so offsets into the text
    don't move. Used for matching, never to change what is sent."""
    return text.translate(_FOLD)


@dataclass(frozen=True)
class View:
    plain: str                 # the text edits refer to
    norm: str                  # the canonical normal form that layers match on
    src: tuple[int, ...]       # src[i]: the index in plain of norm[i]; src[len(norm)] == len(plain)
    breaks: frozenset[int] = frozenset()    # plain indices where an invisible character was dropped before them
    split: bool = False

    def to_plain(self, start: int, end: int) -> tuple[int, int]:
        """The stretch of plain text that norm[start:end] came from."""
        if end <= start:
            return self.src[start], self.src[start]
        return self.src[start], self.src[end - 1] + 1

    def to_norm(self, start: int, end: int) -> tuple[int, int]:
        """The stretch of norm that came from plain[start:end]."""
        return bisect.bisect_left(self.src, start), bisect.bisect_left(self.src, end)


def _plain_and_breaks(text: str) -> tuple[str, frozenset[int]]:
    out: list[str] = []
    breaks: set[int] = set()
    for c in unicodedata.normalize("NFKC", text):
        if unicodedata.category(c) == "Cf":
            breaks.add(len(out))
        else:
            out.append(c)
    return "".join(out), frozenset(breaks)


def _view_ascii(p: str, breaks: frozenset[int] = frozenset()) -> View:
    """The fast path for ASCII plain text: casefold is lower(), one for one."""
    parts: list[str] = []
    src: list[int] = []
    prev_end = 0
    for m in re.finditer(r"\S+", p):
        if parts:
            parts.append(" ")
            src.append(prev_end)
        parts.append(m.group().lower())
        src.extend(range(m.start(), m.end()))
        prev_end = m.end()
    src.append(len(p))
    return View(p, "".join(parts), tuple(src), breaks)


def _parts(a: str, b: str) -> bool:
    return (a.islower() and b.isupper()) or (a.isalpha() and b.isdigit()) or (a.isdigit() and b.isalpha())


def _view_full(p: str, *, split: bool, breaks: frozenset[int] = frozenset()) -> View:
    f = fold(p)
    out: list[str] = []
    src: list[int] = []
    pending: int | None = None          # where a run of separators began
    for i, c in enumerate(f):
        if c.isspace():
            if pending is None:
                pending = i
            continue
        if split and pending is None and i > 0 and (i in breaks or _parts(f[i - 1], c)):
            pending = i
        if pending is not None:
            if out:
                out.append(" ")
                src.append(pending)
            pending = None
        for ch in unicodedata.normalize("NFD", c.casefold()):
            if not unicodedata.combining(ch):
                out.append(ch)
                src.append(i)
    src.append(len(p))
    return View(p, "".join(out), tuple(src), breaks, split)


def view(text: str, *, split: bool = False) -> View:
    """The plain text and its normal form, with the map between them. `text` may be raw: the view plains it, and
    with split=True it also parts words at the invisible characters it dropped."""
    p, breaks = _plain_and_breaks(text)
    if not split and p.isascii():
        return _view_ascii(p, breaks)
    return _view_full(p, split=split, breaks=breaks)


def split_view(v: View) -> View:
    """The same text with words parted where the plain text hid a break (see the module docstring)."""
    return v if v.split else _view_full(v.plain, split=True, breaks=v.breaks)


def as_view(text: str | View) -> View:
    """A View as given, or the view of a string that must already be plain: edits made from it refer to that
    string, so a caller can't compute them on one string and apply them to another."""
    if isinstance(text, View):
        return text
    if plain(text) != text:
        raise ValueError("edits are computed on plain text only: call plain() first, or pass a view")
    return view(text)


def normal(text: str) -> str:
    """The canonical normal form: plain, fold, casefold (accents dropped), separators collapsed."""
    return view(text).norm
