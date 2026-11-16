"""The alias grammar (spec 4.2): what Claude sees in place of people, children, accounts and payees, and the bracket
tokens redaction leaves where there is no alias.

Protection (Task 2.5, the Task 2 security review): an alias or bracket token is protected only when the NAS issued it
in this turn and it appears exactly as issued. Text that merely looks like one ("Person 12" that nobody was given, a
"[name]" typed into the question, "Person 1" spelled with a Cyrillic e, "person 1") is checked like any other text."""
from __future__ import annotations

import re
from collections.abc import Collection

NUMBERED = ("Person", "Child", "Account", "Payee")
NAMED = ("Joint", "Business", "Parent")
_BODY = r"(?:(?:Person|Child|Account|Payee) [1-9][0-9]{0,3}|Joint|Business|Parent)"
ALIAS_PATTERN = rf"^{_BODY}$"
ALIAS_RE = re.compile(ALIAS_PATTERN)
ALIAS_TOKEN_RE = re.compile(rf"(?<![\w]){_BODY}(?![\w])")
BRACKETS = ("[name]", "[organization]", "[institution]", "[payee]", "[email]", "[phone]", "[address]",
            "[date of birth]", "[account number]", "[card number]", "[ssn]", "[routing number]", "[iban]", "[number]",
            "[secret]")
BRACKET_RE = re.compile("|".join(re.escape(b) for b in BRACKETS))
_NUMBERED_RE = re.compile(r"^(Person|Child|Account|Payee) ([1-9][0-9]{0,3})$")


def is_alias(s: object) -> bool:
    return isinstance(s, str) and ALIAS_RE.fullmatch(s) is not None


def is_issuable(s: object) -> bool:
    """An alias or a bracket token: the only strings the NAS can issue."""
    return is_alias(s) or s in BRACKETS


def number_of(alias: str) -> tuple[str, int] | None:
    m = _NUMBERED_RE.fullmatch(alias)
    return (m.group(1), int(m.group(2))) if m else None


def protected_spans(text: str, issued: Collection[str]) -> list[tuple[int, int]]:
    """Where `text` (plain) holds a token the NAS issued this turn, exactly as issued. An alias counts only as a whole
    word that no more digits follow ("Account 1,234" is not "Account 1"); a bracket token counts as written."""
    bad = [t for t in issued if not is_issuable(t)]
    if bad:
        raise ValueError(f"{len(bad)} issued token(s) aren't aliases or bracket tokens")
    found: list[tuple[int, int]] = []
    aliases = sorted((t for t in issued if is_alias(t)), key=len, reverse=True)
    if aliases:
        pattern = "|".join(re.escape(a) for a in aliases)
        found += [(m.start(), m.end()) for m in re.finditer(rf"(?<![\w])(?:{pattern})(?![\w])(?![^\w\s]\d)", text)]
    for b in (t for t in issued if t in BRACKETS):
        found += [(m.start(), m.end()) for m in re.finditer(re.escape(b), text)]
    return sorted(found)
