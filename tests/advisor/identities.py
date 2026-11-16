"""Fictional identifiers for the synthetic books (spec 11.1). Nothing here is real: the names are invented, emails are
at example.com, phones are 555-01xx, SSNs are in the never-issued 900 range, cards are the networks' published test
numbers, and the routing numbers and IBAN are documentation examples. Identifiers under "known" are stored in the
book, so the NAS's exact pass must catch them; the rest are the model layer's job (spec 11.2)."""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from steward.advisor.identifiers import dob_forms
from steward.db.directory_models import User
from steward.db.models import Child, InventoryItem
from steward_boundary.text import fold, plain

HOUSEHOLD = {
    "known": {"name": ["Jordan Reyes", "Samantha Reyes", "Avery", "Noah", "Lily"],
              "email": ["jordan.reyes@example.com", "samantha.reyes@example.com"],
              "dob": ["1985-06-14", "1987-02-02"],
              "institution": ["Big Bank", "Robo Invest", "Workplace Retirement"],
              "payee": ["Streamflix", "Cloudtunes", "Noodle House"]},
    "unknown": {"name": ["Jordy", "Sammy"], "organization": ["Brightline Robotics"],
                "address": ["2207 Juniper Court, Unit 4B, Brea, CA 92821"]},
}
PARENT = {
    "known": {"name": ["Margaret Ellis", "Robert", "Linda Park", "Daniel Ortiz"],
              "email": ["dortiz@example.com", "lpark@example.com"],
              "phone": ["(714) 555-0102", "(714) 555-0148"],
              "number": ["EM-LTC-0047730"],
              "institution": ["Wells Fargo", "Fidelity", "Westmark Life", "Evergreen Mutual", "Clearpath Rx"],
              "address": ["1428 Alder Lane, Fullerton, CA 92831"]},
    "unknown": {"name": ["Peggy", "Bobby"], "dob": ["1941-03-14"]},
}
THIRD_PARTY = ["Tom Becker", "Dr. Alvarez", "Priya Nair", "Coach Dunmore", "Aunt Rosalind", "Jonah Wexler"]
PATTERNS = {"ssn": ["900-12-3456", "912-45-6789"],
            "card": ["4111 1111 1111 1111", "5555 5555 5555 4444", "3782 822463 10005"],
            "routing": ["021000021", "011000015"], "account": ["4417002918", "88120345671"],
            "iban": ["GB82 WEST 1234 5698 7654 32"]}
DIGIT_KINDS = frozenset({"phone", "number", "ssn", "card", "routing", "account", "iban"})
TITLES = frozenset({"dr", "aunt", "coach", "mr", "mrs", "ms"})


def seed_household_identities(db: Session, ddb: Session) -> None:
    """The demo household with full names and example.com emails for its two people, and first names for the
    children."""
    for username, name, email in (("alex", "Jordan Reyes", "jordan.reyes@example.com"),
                                  ("spouse", "Samantha Reyes", "samantha.reyes@example.com")):
        ddb.execute(update(User).where(User.username == username).values(display_name=name, email=email))
    ddb.commit()
    for old, new in (("Oldest", "Avery"), ("Middle", "Noah"), ("Youngest", "Lily")):
        db.execute(update(Child).where(Child.label == old).values(label=new))
    db.commit()


def seed_parent_identities(db: Session) -> None:
    """Margaret's house gets a street address in its details (the inventory form's free fields can hold one)."""
    house = db.scalar(select(InventoryItem).where(InventoryItem.name == "House"))
    details = json.loads(house.details or "{}")
    details["address"] = PARENT["known"]["address"][0]
    house.details = json.dumps(details)
    db.commit()


def needles(kind: str, value: str) -> tuple[list[str], list[str]]:
    """What must not survive of an identifier: words (case- and look-alike-insensitive, whole words) and digit
    strings of 5 or more digits."""
    if kind == "dob":
        forms = dob_forms(date.fromisoformat(value))
        # the year of birth is never sent (preflight ruling 6), so the 4-digit year is a needle too
        return [f.casefold() for f in forms], ["".join(c for c in f if c.isdigit()) for f in forms] + [value[:4]]
    if kind in DIGIT_KINDS:
        digits = "".join(c for c in value if c.isdigit())
        words = [value.casefold()] if any(c.isalpha() for c in value) else []
        return words, [digits] if len(digits) >= 5 else []
    if kind == "secret":
        # a PIN is a needle however short, in digits or in words; a password is a word
        digits = "".join(c for c in value if c.isdigit())
        if any(c.isalpha() for c in value):
            return [value.casefold()], []
        return [" ".join(_SPELL[d] for d in digits)], [digits]
    if kind == "address":
        street = value.split(",")[0].split(maxsplit=1)[1]      # "Alder Lane": a house number alone identifies nothing
        return [street.casefold()], []
    if kind == "name":
        parts = [p for p in value.replace(".", "").split() if len(p) >= 4 and p.casefold() not in TITLES]
        return [p.casefold() for p in parts] or [value.casefold()], []
    return [value.casefold()], []


_SPELL = dict(zip("0123456789", "zero one two three four five six seven eight nine".split()))
_RUNS = re.compile(r"\d(?:[\s\-.()/]*\d)*")
_WORD_DIGITS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine".split())} | {"oh": "0"}
_DIGIT_TOKEN = re.compile(rf"(?<![^\W_]|•)(?:{'|'.join(_WORD_DIGITS)})(?![^\W_]|•)|\d+")
_SPOKEN_JOIN = re.compile(r"(?:[^\w•]|_)+(?:and|then|dash)(?:[^\w•]|_)+")


def spelled_digit_runs(text: str) -> list[str]:
    """Numbers written at least partly in words ("nine zero zero ...", "nine zero zero 12 3456") as digit strings,
    matched on the normal form like the production pass, so an unredacted spelled-out number is seen. Tokens join
    across any stretch with no letter in it, and two digit words also across one spoken "and", "then" or "dash"."""
    t = fold(plain(text)).casefold()
    runs: list[list[str]] = []
    prev = None
    for m in _DIGIT_TOKEN.finditer(t):
        tok = m.group()
        if prev is not None:
            gap = t[prev.end():m.start()]
            words = not tok.isdigit() and not prev.group().isdigit()
            if not any(c.isalpha() for c in gap) or (words and _SPOKEN_JOIN.fullmatch(gap)):
                runs[-1].append(tok)
                prev = m
                continue
        runs.append([tok])
        prev = m
    return ["".join(_WORD_DIGITS.get(x, x) for x in run) for run in runs if any(not x.isdigit() for x in run)]


def leaks(text: str, kind: str, value: str) -> bool:
    words, digits = needles(kind, value)
    t = fold(plain(text)).casefold()
    for w in words:
        if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", t):
            return True
    runs = ["".join(c for c in run if c.isdigit()) for run in _RUNS.findall(plain(text))] + spelled_digit_runs(text)
    return any(d and d in r for d in digits for r in runs)


def all_identifiers() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for book in (HOUSEHOLD, PARENT):
        for group in ("known", "unknown"):
            for kind, values in book[group].items():
                out += [(kind, v) for v in values]
    out += [("name", n) for n in THIRD_PARTY]
    out += [(kind, v) for kind, values in PATTERNS.items() for v in values]
    return out
