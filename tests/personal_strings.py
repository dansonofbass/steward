"""The personal-string scanner, with no terms in it: a tokenizer and a matcher over SHA-256 hashes of lowercased terms.

The terms are private. They're read from the file STEWARD_PRIVATE_TERMS names or, when that isn't set, from
export/private_terms.txt if this checkout has one. With neither, private_matcher() is None and the checks that need it
skip; everything else here still works on made-up terms.

A term file has one line per term, "<name> <SHA-256 of the lowercased term> <length or ->", and # comments. Text is
split into tokens: words (also split at camelCase humps), and dotted names such as domains and an email's local part,
with every shorter domain suffix too. A token whose hash is listed is a hit. A term with a length is also caught glued
to other text ("<term>Family"): every substring of an alphanumeric run with one of those lengths is hashed too. A term
that is part of ordinary words has no length ("-"), so it is caught only as a whole word.

Not a term, by ruling (Nov 10, release gate PRIV-1): the owner's initials JR, also the Person 1 key jr. They are the
project's public name and the key stays. tests/test_no_internal_words.py keeps them out of every string Steward shows.
"""
import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS_ENV = "STEWARD_PRIVATE_TERMS"
DEFAULT_TERMS = ROOT / "export" / "private_terms.txt"

Terms = dict[str, tuple[str, int | None]]

WORD = re.compile(r"[a-z0-9]+")
# A dotted name is labels joined by dots, each label [a-z0-9] or [a-z0-9][a-z0-9-]*[a-z0-9]. It is read in two steps so
# the time stays linear in the text: a regex for the "chain" around it (runs of [a-z0-9-] joined by single dots,
# possessive and tried only at a run's start, so no character is read twice), then _dotted on the chain. A single
# regex for the name, with findall, retried from each letter of a long run with no dot and read the rest of the run
# each time: square time (47 minutes on one 274,304-letter run in a shared library).
CHAIN = re.compile(r"(?<![a-z0-9-])[a-z0-9-]++(?:\.[a-z0-9-]++)+")
HUMP = re.compile(r"([a-z0-9])([A-Z])|([A-Z])([A-Z][a-z])")
# Where letters turn into digits ("term2026"), for the bundle's whole words. Not where digits turn into letters, so a
# random key such as a lucide SVG path key ("5" and four letters) doesn't give its letters as a word (JR's ruling,
# Nov 10).
LETTERS_TO_DIGITS = re.compile(r"(?<=[a-z])(?=[0-9])")
SHA256 = re.compile(r"[0-9a-f]{64}")


def _split_humps(text: str) -> str:
    """"fooBar" and "ABCFoo" to "foo Bar" and "ABC Foo"."""
    return HUMP.sub(lambda m: f"{m[1]} {m[2]}" if m[1] else f"{m[3]} {m[4]}", text)


def _dotted(chain: str) -> list[str]:
    """The dotted names in a chain, as a leftmost, greedy match of label(.label)+ finds them, read once from the left.
    A name starts at a run's first letter or digit, when the run ends in one and the next run starts with one. Each
    later label is its run less any trailing hyphens, and the name goes on past it only when it is the whole run and
    the next run starts with a letter or digit. The next name is looked for from the run after the one it ended in."""
    runs = chain.split(".")
    names, i = [], 0
    while i < len(runs) - 1:
        if runs[i][-1] == "-" or runs[i + 1][0] == "-":
            i += 1
            continue
        labels, j = [runs[i].lstrip("-")], i + 1
        while True:
            labels.append(runs[j].rstrip("-"))
            if labels[-1] != runs[j] or j + 1 == len(runs) or runs[j + 1][0] == "-":
                break
            j += 1
        names.append(".".join(labels))
        i = j + 1
    return names


def tokens(text: str) -> set[str]:
    """Words, as written and split at camelCase humps, and dotted names with each of their suffixes of two labels or
    more (a.b.example.com gives a.b.example.com, b.example.com and example.com). An email's local part and domain come
    out as two dotted names."""
    low = text.lower()
    out = set(WORD.findall(low)) | set(WORD.findall(_split_humps(text).lower()))
    for name in (name for chain in CHAIN.findall(low) for name in _dotted(chain)):
        labels = name.split(".")
        out.update(".".join(labels[i:]) for i in range(len(labels) - 1))
    return out


class Matcher:
    def __init__(self, terms: Terms, split_digits: bool = False):
        self.terms = terms
        self.split_digits = split_digits
        self.whole = {h: name for name, (h, _) in terms.items()}
        self.glued = {h: name for name, (h, n) in terms.items() if n}
        self.lengths = sorted({n for _, n in terms.values() if n})
        self._token = lru_cache(maxsize=None)(self._token_names)
        self._words: Matcher | None = None

    def whole_words(self) -> "Matcher":
        """The same terms found as whole words only, never glued to other text: for minified code, where a term's
        letters inside an identifier mean nothing. A word ends at anything but a letter or digit, at a camelCase hump,
        and where letters turn into digits ("term2026"), but not where digits turn into letters ("5term" is one word).
        One matcher, made on the first call."""
        if self._words is None:
            self._words = Matcher({name: (h, None) for name, (h, _) in self.terms.items()}, split_digits=True)
        return self._words

    def _token_names(self, token: str) -> frozenset[str]:
        found = set()
        name = self.whole.get(hashlib.sha256(token.encode()).hexdigest())
        if name:
            found.add(name)
        if "." not in token:
            for n in self.lengths:
                for piece in {token[i:i + n] for i in range(len(token) - n + 1)}:   # each distinct piece hashed once
                    name = self.glued.get(hashlib.sha256(piece.encode()).hexdigest())
                    if name:
                        found.add(name)
        return frozenset(found)

    def __call__(self, text: str) -> set[str]:
        """The names of the terms in text."""
        out = set()
        found = tokens(text)
        if self.split_digits:
            found |= {part for t in found if "." not in t for part in LETTERS_TO_DIGITS.split(t)}
        for t in found:
            out |= self._token(t)
        return out


def load_terms(path: Path) -> Terms:
    """A term file's terms. ValueError, naming the file and line, for anything but a well-formed list."""
    terms: Terms = {}
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        ok = (len(parts) == 3 and SHA256.fullmatch(parts[1]) is not None
              and (parts[2] == "-" or (parts[2].isdigit() and int(parts[2]) > 0)))
        if not ok:
            raise ValueError(f"{path}:{n}: expected '<name> <sha256, lower-case hex> <length or ->'")
        name, digest, length = parts
        if name in terms:
            raise ValueError(f"{path}:{n}: {name} is listed twice")
        terms[name] = (digest, None if length == "-" else int(length))
    if not terms:
        raise ValueError(f"{path} lists no terms")
    return terms


def terms_path() -> Path | None:
    """The term file to use: the one STEWARD_PRIVATE_TERMS names (which must exist), else export/private_terms.txt
    when this checkout has it, else None."""
    named = os.environ.get(TERMS_ENV)
    if named:
        path = Path(named)
        if not path.is_file():
            raise FileNotFoundError(f"{TERMS_ENV} names {path}, which isn't a file")
        return path
    return DEFAULT_TERMS if DEFAULT_TERMS.is_file() else None


def private_matcher() -> Matcher | None:
    """A matcher for the private terms, or None where there's no term file (the public repo)."""
    path = terms_path()
    return Matcher(load_terms(path)) if path else None


def made_up(**terms: tuple[str, int | None]) -> Matcher:
    """A matcher for invented terms given in plain text, name=(term, length or None). For tests only."""
    return Matcher({name: (hashlib.sha256(t.encode()).hexdigest(), n) for name, (t, n) in terms.items()})


def decode_text(data: bytes) -> str | None:
    """A file's text, or None for a binary: a NUL in its first 8 KB, or not UTF-8."""
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_text(path: Path) -> str | None:
    return decode_text(Path(path).read_bytes())
