"""The about line (Ask about this, P4, P13): one sentence for what a question was asked about, made from the strict
wire object (protocol.ABOUT) and nothing else. The gateway appends it to the per-turn context; the NAS shows the same
string first in What Claude will see. It imports nothing from steward (tests/test_packaging.py).

Numbers are kept apart: dates in words ("October 16, 2026"), a word between any two numbers, and amounts with no
sign, so the line passes the question path's text rule with the about alias issued (tests/boundary/test_about.py).
Each enum's id stands beside its words, so Claude can pass it straight to a tool."""
from __future__ import annotations

from datetime import date

from steward_boundary.vocab import CATEGORY_WORDS


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def _month(ym: str) -> str:
    d = date.fromisoformat(f"{ym}-01")
    return f"{d:%B} {d.year}"


def _money(cents: int) -> str:
    c = abs(cents)
    return f"${c // 100:,}.{c % 100:02d}"


def about_text(about: dict) -> str:
    kind = about["kind"]
    if kind == "account":
        return f"It's about {about['account']}."
    if kind == "category":
        c = about["category"]
        return f"It's about {CATEGORY_WORDS[c]} (category {c}) in {_month(about['month'])}."
    if kind == "plan":
        return "It's about the retirement plan."
    if kind == "transaction":
        c = about["category"]
        way = "in" if about["amount_cents"] > 0 else "out"
        return (f"It's about one transaction: {_money(about['amount_cents'])} {way} on {_day(about['date'])}, "
                f"category {CATEGORY_WORDS[c]} ({c}), in {about['account']}.")
    if kind == "flag":
        return f"It's about a flag from the {about['check']} check on {_day(about['date'])}."
    if kind == "care" and "scenario" in about:
        return f"It's about care scenario {about['scenario']} ({about['level']})."
    if kind == "care":
        return "It's about the care projection."
    raise ValueError("an about object of an unknown kind")
