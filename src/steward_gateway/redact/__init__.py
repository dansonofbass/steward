"""Model redaction on the gateway (spec 4.3): GLiNER-PII and Presidio over free text. Only alias and bracket tokens the
NAS issued this turn are protected (Task 2.5): a detector span is cut around them with spans.outside(), never dropped,
so a typed look-alike or a neighbouring name is still replaced. Spans whose text is a keep word (ruling 18) are
ignored, and so is a model span that names nobody however it is drawn (names_nobody); overlapping spans, from one
detector or several, merge into one covering all of them.

Every detector reads the canonical view (Task 8.5, steward_boundary.normal.view): look-alike letters folded to
Latin, digits to ASCII, accents dropped, each run of separators one space. When parting words where the plain text hid
a break (a zero-width space, "TomBecker", "Acct123456") changes it, the detectors read that split view too and the
spans are joined. The only difference from the views the exact pass and the fingerprints use is that letters keep
their case, one character for one, because the models read capitals. Each span is mapped back to the plain text
through the view's map, so a casefold that changes length ("ß" to "ss") or a collapsed line break never moves an edit.
The edits and the returned text are on the plain text (NFKC, invisible characters dropped), which is what is sent. The
same redact() makes the preview and the sent question (spec 4.3, "The preview"). If the models can't load, chat stays
disabled: there is no mode that sends without them (spec 6.2)."""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from steward_boundary.aliases import ALIAS_TOKEN_RE, BRACKET_RE, protected_spans
from steward_boundary.normal import View, fold, split_view, view
from steward_boundary.spans import Edit, apply, merge, outside
from steward_boundary.text import DIGIT_LIMIT
from steward_boundary.vocab import CATEGORIES, GENERIC_WORDS, STATES
from steward_gateway.logs import log_event

log = logging.getLogger("steward_gateway.redact")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str      # the bracket token that replaces it, e.g. "[name]"
    layer: str      # "gliner" or "presidio"


class Detector(Protocol):
    name: str

    def detect(self, text: str) -> list[Span]: ...


# A hit with one of these labels stops a turn in the second pass (spec 4.5, check 3). "[secret]" is left out on
# purpose: banks write "PIN" in their own text ("DEBIT PIN 5521"), so a store name holding it must not stop a turn;
# the question is redacted for it here and on the NAS, and store names pass the NAS's exact pass, which has the rule.
STOP_LABELS = frozenset({"[name]", "[email]", "[phone]", "[address]", "[date of birth]", "[account number]",
                         "[card number]", "[ssn]", "[routing number]", "[iban]"})
_STATE_NAMES = ("Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho "
                "Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota "
                "Mississippi Missouri Montana Nebraska Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah "
                "Vermont Virginia Washington Wisconsin Wyoming").split()
KEEP_WORDS = frozenset(w.casefold() for w in (
    "Social Security", "Medicare", "Medicare Part B", "Medicare Part D", "Medicaid", "IRS", "IRA", "Roth", "Roth IRA",
    "401(k)", "403(b)", "HSA", "529", "RMD", "CD", "Steward", "Claude", "New Hampshire", "New Jersey", "New Mexico",
    "New York", "North Carolina", "North Dakota", "Rhode Island", "South Carolina", "South Dakota", "West Virginia",
    *_STATE_NAMES, *STATES, *(c.replace("_", " ") for c in CATEGORIES)))
_TOKEN = re.compile(r"[^\W_]+")
# The words of the keep words, as words of a longer model span. Not the 2-letter state codes, and no word of 1 or 2
# letters ("b" of "403(b)", "k" of "401(k)"): those are initials and short names ("Al", "Mo", "Ms Georgia"); the exact
# check in detect_all still drops a span that is only "CA" (final review F3).
_KEEP_TOKENS = frozenset(t for w in KEEP_WORDS - {s.casefold() for s in STATES} for t in _TOKEN.findall(w) if len(t) > 2)
# State and month names that are also people's names. One of them in a person span names nobody ("in May", "North
# Carolina"); two make a name ("Georgia Washington", "June Carolina") (final review F3).
_NAME_LIKE = frozenset("georgia virginia carolina dakota montana nevada indiana florida washington york arizona "
                       "may june april august".split())
# Words that name nobody and that ruling 4's generic words leave out: pronouns and a few joining words.
_PRONOUNS = frozenset("i me we us you he him she they them mine yours ours theirs if or but so than as is are was".split())


def names_nobody(text: str, label: str) -> bool:
    """True for a model span that can't carry an identifier, whatever its boundaries (privacy approach review,
    2026-10-24): no letters and at most 4 digits (the question rule lets those leave: an age, a year), or, except for a
    date of birth, every word a keep word, one of ruling 4's generic words, a pronoun, or a number of 4 digits or
    fewer ("We", "Our kids", "3, 10 and 16", "the Roth IRA and the HSA", "Social Security if"). A person span with
    two state or month names that are also people's names is a name ("Georgia Washington"). A span holding
    something shaped like an alias or a bracket token always counts: one the NAS issued is cut out of it by
    detect_all, and one it didn't ("Person 7", a typed "[payee]") is replaced like any other text (Task 2.5)."""
    if ALIAS_TOKEN_RE.search(text) or BRACKET_RE.search(text):
        return False
    if not any(c.isalpha() for c in text) and sum(c.isdigit() for c in text) <= DIGIT_LIMIT:
        return True
    if label == "[date of birth]":
        return False
    toks = [t.casefold() for t in _TOKEN.findall(text)]
    if label == "[name]" and sum(t in _NAME_LIKE for t in toks) > 1:
        return False
    return bool(toks) and all(t in _KEEP_TOKENS or t in GENERIC_WORDS or t in _PRONOUNS
                              or (t.isdigit() and len(t) <= DIGIT_LIMIT) for t in toks)


@dataclass(frozen=True)
class Redacted:
    text: str                       # the plain text with the edits applied
    edits: tuple[Edit, ...]         # on the plain text (normal.view(text).plain), not on the raw input


def _cased(v: View) -> str:
    """The view's normal text with each letter given back the case of the plain character it came from: same length
    and same map as v.norm."""
    f = fold(v.plain)
    chars = list(v.norm)
    for i, ch in enumerate(chars):
        if ch.isalpha() and f[v.src[i]].isupper():
            up = ch.upper()
            if len(up) == 1:
                chars[i] = up
    return "".join(chars)


def detection_views(text: str) -> list[tuple[View, str]]:
    """What the detectors read: the canonical view of `text` (case kept), and its split form when splitting changes
    it. Splitting parts "TomBecker" and a zero-width space but would also break "GB82…" (an IBAN), so both are read
    and their spans joined."""
    v = view(text)
    out = [(v, _cased(v))]
    w = split_view(v)
    if w.norm != v.norm:
        out.append((w, _cased(w)))
    return out


def detect_all(text: str, detectors: Sequence[Detector], issued: Collection[str] = frozenset()) -> list[Span]:
    """Spans on the plain text of `text` (raw or plain). Every detector reads the canonical view (and its split form);
    each span is mapped back to the plain text. `issued` is the alias and bracket tokens the NAS issued this turn; a
    span that overlaps one is cut around it (the issued token stays, the rest is still replaced)."""
    views = detection_views(text)
    plain_text = views[0][0].plain
    protected = protected_spans(plain_text, issued)
    out = []
    for v, seen in views:
        for d in detectors:
            for s in d.detect(seen):
                s0, s1 = max(0, s.start), min(len(seen), s.end)
                if s1 <= s0 or (s.label != "[secret]" and seen[s0:s1].strip().casefold() in KEEP_WORDS):
                    continue                # a password may be a keep word: "my password is New York"
                p0, p1 = v.to_plain(s0, s1)
                # A model span is judged piece by piece once the issued tokens are cut out of it: "my brother [name]"
                # around the gateway's own "[name]" leaves "my brother ", which names nobody.
                out += [Span(a, b, s.label, s.layer) for a, b in outside(p0, p1, protected)
                        if not (s.layer == "gliner" and names_nobody(plain_text[a:b], s.label))]
    return out


def redact(text: str, detectors: Sequence[Detector], issued: Collection[str] = frozenset()) -> Redacted:
    plain = view(text).plain
    edits = merge(Edit(s.start, s.end, s.label, s.layer) for s in detect_all(text, detectors, issued))
    return Redacted(apply(plain, edits)[0], tuple(edits))


class Guarded:
    """One detector made of several behind one lock: the GPU model is shared by every turn and isn't safe to call at
    once. Pass it as [Guarded(detectors)]."""
    name = "guarded"

    def __init__(self, detectors: Sequence[Detector]):
        self._detectors, self._lock = list(detectors), threading.Lock()

    def detect(self, text: str) -> list[Span]:
        with self._lock:
            return [s for d in self._detectors for s in d.detect(text)]


def load_real_detectors() -> tuple[list[Detector], str | None]:
    """GLiNER-PII and Presidio, or no detectors and the reason, for /v1/health (spec 6.2)."""
    try:
        from steward_gateway.redact.gliner_detector import GlinerDetector
        from steward_gateway.redact.presidio_detector import PresidioDetector
        return [GlinerDetector(), PresidioDetector()], None
    except Exception as e:  # noqa: BLE001 - any failure leaves chat disabled, with the reason in health
        log_event(log, "redaction.load_failed", level=logging.ERROR, error_type=type(e).__name__)
        return [], f"The redaction models didn't load ({type(e).__name__})."
