"""The exact pass (spec 4.3), deterministic and on the NAS: each known identifier becomes its alias or a bracket
token. Matching is steward_boundary.known's (the canonical normal form: case, accents, look-alike letters, full-width
digits, zero-width characters, separators), so it reaches the same verdict as the gateway's fingerprints on every
spelling. Dates written next to a birth word become "[date of birth]" (ruling 6), five or more digits spelled out in
words become "[number]" (ruling 28; the rule is steward_boundary.text's, shared with the gateway), a PIN, password or
code written next to its word becomes "[secret]" (click-through feedback, 2026-10-25; also the gateway's), and the
outgoing question rule (Task 2.5) is applied last, with the aliases and
bracket tokens this pass issued as its only protected text.

The pass ends with two checks and refuses the turn (Refused) if either fails: no known identifier may survive in the
final text (known.survivors), and the final text must pass the question rule unchanged (what the gateway will check).
A later edit that would overlap an alias chip is also a refusal, never a guess. issued_now(chips) names the tokens the
NAS put into this text; the turn sends them in the START frame as `issued`."""
from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from steward.advisor.identifiers import Identifier
from steward_boundary.aliases import is_issuable
from steward_boundary.fingerprint import hashes_for
from steward_boundary.known import Known, find_known, forms_table, known_digits, survivors
from steward_boundary.normal import view
from steward_boundary.protocol import LINES
from steward_boundary.spans import Edit, apply, shift
from steward_boundary.text import dob_edits, is_question_safe, question_edits, secret_edits, spelled_edits


class Refused(Exception):
    """The pass can't prove the text is clean, so nothing is sent. The message is the plain stop line."""
    stop = "stopped_check"

    def __init__(self) -> None:
        super().__init__(LINES["stopped_check"])


@lru_cache(maxsize=16)
def _compiled(identifiers: tuple[Identifier, ...]) -> tuple[dict[str, str], frozenset[str]]:
    knowns = [Known(i.text, i.replacement, i.name) for i in identifiers]
    return forms_table(knowns), known_digits(knowns)


def exact_redact(text: str, identifiers: Sequence[Identifier]) -> tuple[str, list[dict]]:
    """The text after the exact pass and the outgoing question rule, and its chips (layer "steward")."""
    table, digits = _compiled(tuple(identifiers))
    v = view(text)
    edits: list[Edit] = spelled_edits(v)
    edits += dob_edits(v)
    edits += secret_edits(v)
    edits += find_known(v, table)
    try:
        named, chips = apply(v.plain, edits)
        issued = frozenset(c["label"] for c in chips if is_issuable(c["label"]))
        masks = question_edits(named, issued=issued, known=digits)
        final, mask_chips = apply(named, masks)
        chips = sorted(shift(chips, masks) + mask_chips, key=lambda c: c["start"])
    except ValueError as e:         # a mask reached into an alias chip, or an edit lay outside its text
        raise Refused from e
    if survivors(final, table) or not is_question_safe(final, issued=issued, known=digits):
        raise Refused
    return final, chips


def survives(text: str, identifiers: Sequence[Identifier]) -> bool:
    """Whether any of the identifiers is still in the text, on the exact pass's own matching (known.survivors)."""
    return bool(survivors(text, _compiled(tuple(identifiers))[0]))


def issued_now(chips: Sequence[dict]) -> list[str]:
    """The aliases and bracket tokens this pass put into the text, sorted: the START frame's `issued`."""
    return sorted({c["label"] for c in chips if is_issuable(c["label"])})


def turn_hashes(identifiers: Sequence[Identifier], salt: str) -> list[str]:
    return sorted(hashes_for(((i.text, i.name) for i in identifiers), salt))


APPROVABLE_KINDS = ("payee", "institution")


def turn_hash_sets(identifiers: Sequence[Identifier], salt: str) -> tuple[list[str], list[str]]:
    """The START frame's `hashes` and `approvable` (plan B ruling 3): payee and institution names apart from the rest.
    A hash both kinds produce stays in the rest, so it is never let through."""
    rest = hashes_for(((i.text, i.name) for i in identifiers if i.kind not in APPROVABLE_KINDS), salt)
    approvable = hashes_for(((i.text, i.name) for i in identifiers if i.kind in APPROVABLE_KINDS), salt) - rest
    return sorted(rest), sorted(approvable)
