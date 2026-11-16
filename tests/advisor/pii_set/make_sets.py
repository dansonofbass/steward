"""Builds the fictional PII set (400 questions) and keep set (200) of spec 11.1 from templates, with every identifier
span labelled by construction (ruling 27). It covers names in lowercase, possessives, names next to a relationship,
look-alike letters, digits split by spaces, dashes or zero-width characters, numbers spelled out, dates of birth in
six formats, a number pasted from a statement and an address with a unit number.
Write the files with: uv run python -m tests.advisor.pii_set.make_sets"""
from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

from steward.advisor.identifiers import dob_forms
from tests.advisor.identities import HOUSEHOLD, PARENT, PATTERNS, THIRD_PARTY

HERE = Path(__file__).parent
ZW = chr(0x200B)
SPELL = dict(zip("0123456789", ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")))
LOOKALIKE = {"a": chr(0x430), "e": chr(0x435), "o": chr(0x43E), "p": chr(0x440), "c": chr(0x441)}

TEMPLATES = {
    "name": ["How much did {x} spend on dining last month?", "Did {x} get the Social Security deposit this month?",
             "Is {x}'s pension landing in the right account?", "my brother {x} paid me back $200, did it arrive?",
             "What does {x} have in the IRA?", "Can {x} retire at 62 if we save $500 more a month?",
             "{x} asked whether the supplement plan is paid up.", "Has {x} been charged twice by the pharmacy?"],
    "email": ["Can you send the summary to {x}?", "The statement came from {x}, is that our bank?",
              "Email {x} if anything looks odd."],
    "phone": ["Someone called from {x} about a charge, is it real?", "Should I call {x} about the late premium?"],
    "dob": ["I was born {x}, when can I claim Social Security?", "Her birthday is {x}; does the RMD start next year?",
            "DOB {x}: what's the full retirement age?"],
    "address": ["We moved to {x} last spring, does that change the taxes?", "Mail the forms to {x}."],
    "organization": ["My salary from {x} went up 4%, what does that do to the plan?"],
    "institution": ["How much is at {x} right now?", "Is the {x} account earning enough interest?"],
    "payee": ["How much did we pay {x} this year?", "Is {x} charging more than last year?"],
    "number": ["The policy number is {x}, is it the long-term care one?"],
    "ssn": ["My SSN is {x}, do I need it for the 1099?", "Use {x} for the tax form."],
    "card": ["Was card {x} charged twice in September?", "Pasted from the statement: Card {x} Balance $1,182.40"],
    "routing": ["The routing number is {x}, is that our bank?"],
    "account": ["Account Number {x} Balance $8,214.55, is that checking?", "Is {x} the joint account?"],
    "iban": ["Is a wire to {x} next week safe?"],
}
KEEP_TEMPLATES = [
    "Are we spending more than {amt} a month on {cat}?",
    "If I put {amt} more a month into the 401(k), can we retire at {age}?",
    "What did we spend on {cat} in {year} compared with {year2}?",
    "Is {pct} too much to keep in {ticker}?",
    "We live in {state}; does that change the tax on {amt}?",
    "Can we cover a year on one income of {amt}?",
    "Is Medicare Part B {amt} a month now?",
    "Our kids are {a1}, {a2} and {a3}; what will college cost?",
    "Did {cat} go up {pct} since {year}?",
    "How much is in the Roth IRA and the HSA, and is {ticker} or {ticker2} the bigger share?",
    "When can we claim Social Security if we stop working at {age}?",
    "What would {amt} a year from consulting until {age} do to the plan?",
]
AMOUNTS = ["$500", "$1,250", "$812.40", "$12k", "$2,400,000", "$38.40", "12,000 dollars", "$185"]
CATS = ["dining", "groceries", "travel", "utilities", "subscriptions", "health", "insurance", "shopping"]
AGES = ["55", "60", "62", "65", "67", "70"]
YEARS = ["2019", "2024", "2025", "2031"]
PCTS = ["4%", "6.5%", "12.5%", "20 %"]
TICKERS = ["VTI", "BND", "VXUS", "FXAIX", "VFIFX"]
STATES = ["California", "Texas", "CA", "New York", "Oregon"]


def _lookalike(v: str) -> str:
    for i, ch in enumerate(v):
        if i > 0 and ch in LOOKALIKE:
            return v[:i] + LOOKALIKE[ch] + v[i + 1:]
    return v


def variants(kind: str, value: str) -> list[tuple[str, str]]:
    seen, out = set(), []
    for name, text in _variants(kind, value):
        if text not in seen:                 # a name with no look-alike letter has no look-alike variant
            seen.add(text)
            out.append((name, text))
    return out


def _variants(kind: str, value: str) -> list[tuple[str, str]]:
    if kind == "name":
        return [("plain", value), ("lowercase", value.lower()), ("lookalike", _lookalike(value))]
    if kind == "dob":
        return [(f"dob_{i}", f) for i, f in enumerate(dob_forms(date.fromisoformat(value)), 1)]
    if kind == "email":
        return [("plain", value), ("uppercase", value.upper())]
    if kind == "number":
        return [("plain", value), ("lowercase", value.lower()), ("spaced", value.replace("-", " "))]
    if kind == "iban":
        return [("plain", value), ("compact", value.replace(" ", ""))]
    if kind in ("phone", "ssn", "card", "routing", "account"):
        digits = "".join(c for c in value if c.isdigit())
        groups = [digits[i:i + 4] for i in range(0, len(digits), 4)]
        return [("plain", value), ("spaced", " ".join(groups)), ("dashed", "-".join(groups)),
                ("zero_width", ZW.join(groups)), ("spelled", " ".join(SPELL[d] for d in digits))]
    return [("plain", value), ("lowercase", value.lower())]


def _pool() -> list[tuple]:
    out, seen = [], set()

    def add(book, category, kind, known, values, templates):
        for value in values:
            for variant, text in variants(kind, value):
                for t in templates:
                    question = t.replace("{x}", text, 1)
                    if (book, question) not in seen:
                        seen.add((book, question))
                        out.append((book, category, variant, kind, known, value, text, t))
    for book, data in (("household", HOUSEHOLD), ("parent", PARENT)):
        for group, known in (("known", True), ("unknown", False)):
            for kind, values in data[group].items():
                category = kind if known else f"{kind}_unknown"
                add(book, category, kind, known, values, TEMPLATES[kind])
        add(book, "third_party", "name", False, THIRD_PARTY, TEMPLATES["name"])
        for kind, values in PATTERNS.items():
            add(book, kind, kind, False, values, TEMPLATES[kind])
    return out


# Rows added after the set was first drawn, numbered after it, so no earlier row moves (book, category, variant, kind,
# known, value, text as written, template).
ADDED = [
    # Final review, 2026-10-24 (F2, F4, F6): spelled numbers as dictation and punctuation write them, and a number
    # half in words and half in digits.
    ("household", "ssn", "spelled_slash", "ssn", False, "900-12-3456",
     "nine zero zero / one two / three four five six", "Use {x} for the tax form."),
    ("parent", "ssn", "spelled_and", "ssn", False, "900-12-3456",
     "nine zero zero and one two three four five six", "My SSN is {x}, do I need it for the 1099?"),
    ("household", "account", "spelled_and", "account", False, "4417002918",
     "four four one seven and zero zero two nine one eight", "Is {x} the joint account?"),
    ("parent", "routing", "spelled_dash", "routing", False, "021000021",
     "zero two one dash zero zero zero dash zero two one", "The routing number is {x}, is that our bank?"),
    ("household", "ssn", "spelled_mixed", "ssn", False, "900-12-3456",
     "nine zero zero 12 3456", "My SSN is {x}, do I need it for the 1099?"),
    ("parent", "account", "spelled_mixed", "account", False, "4417002918",
     "four four one seven 0029-18", "Is {x} the joint account?"),
    # Click-through feedback, 2026-10-25: a PIN, password or code is never sent, however short.
    ("household", "secret", "pin", "secret", False, "1111", "1111", "Here's my pin for my debit card {x}"),
    ("household", "secret", "pin_spelled", "secret", False, "4821", "four eight two one",
     "My PIN is {x}, is that too easy?"),
    ("parent", "secret", "pin_before", "secret", False, "9073", "9073", "{x} is the PIN for the joint card, right?"),
    ("household", "secret", "cvv", "secret", False, "317", "317", "The CVV on the Visa is {x}, can you check the charge?"),
    ("parent", "secret", "password", "secret", False, "hunter2", "hunter2", "My password is {x}, did I use it for the bank?"),
    ("household", "secret", "last_four", "secret", False, "3456", "3456",
     "The last four of my social are {x}, is that on the 1099?"),
    ("parent", "secret", "access_code", "secret", False, "5509", "5509", "The access code for the pharmacy portal is {x}."),
]


def build_pii() -> list[dict]:
    rng = random.Random(20261020)
    pool = _pool()
    strata: dict[tuple, list[tuple]] = {}
    for c in pool:
        strata.setdefault(c[:3], []).append(c)
    chosen = [rng.choice(strata[k]) for k in sorted(strata)]
    taken = set(chosen)
    rest = [c for c in pool if c not in taken]
    rng.shuffle(rest)
    chosen += rest[:400 - len(chosen)]
    rows = []
    for i, (book, category, variant, kind, known, value, text, template) in enumerate(chosen + ADDED, 1):
        start = template.index("{x}")
        rows.append({"id": f"pii-{i:03d}", "book": book, "category": category, "variant": variant,
                     "text": template.replace("{x}", text, 1),
                     "spans": [{"start": start, "end": start + len(text), "kind": kind, "known": known,
                                "value": value}]})
    return rows


def build_keep() -> list[dict]:
    rng = random.Random(20261021)
    rows, seen = [], set()
    while len(rows) < 200:
        text = rng.choice(KEEP_TEMPLATES).format(
            amt=rng.choice(AMOUNTS), cat=rng.choice(CATS), age=rng.choice(AGES), year=rng.choice(YEARS),
            year2=rng.choice(YEARS), pct=rng.choice(PCTS), ticker=rng.choice(TICKERS), ticker2=rng.choice(TICKERS),
            state=rng.choice(STATES), a1=str(rng.randint(2, 9)), a2=str(rng.randint(10, 13)), a3=str(rng.randint(14, 17)))
        if text not in seen:
            seen.add(text)
            rows.append({"id": f"keep-{len(rows) + 1:03d}", "text": text})
    return rows


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write() -> None:
    for name, rows in (("questions.jsonl", build_pii()), ("keep.jsonl", build_keep())):
        (HERE / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    write()
