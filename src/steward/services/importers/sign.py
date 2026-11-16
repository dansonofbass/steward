"""Which way a file's signs run (import/export spec, The sign question; P10, P11). The format, debit and credit
columns or a Type column say it outright; otherwise a running balance, then payment or deposit words, for the picked
account's kind; otherwise the person is asked, with nothing pre-selected. Steward keeps money out negative, so
"Purchases are positive" means negate."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from steward.services.importers.layouts import Layout, Parsed

CARD_TYPES = frozenset({"credit", "business_credit"})
_PAYMENT = re.compile(r"\b(?:payment|thank you|autopay|auto pay|pymt|online pmt|epay)\b", re.I)
_DEPOSIT = re.compile(r"\b(?:payroll|direct dep|deposit|interest paid|transfer from)\b", re.I)
BALANCE_AGREES = 0.9
WORD_ROWS = 3
OTHERS_AGREE = 0.8


@dataclass(frozen=True)
class Verdict:
    verdict: str | None          # "negate" | "as_is" | None (ask)
    lean: str | None             # "positive" | "negative" | None (exactly half: the sentence is dropped)


def lean(raw) -> str | None:
    nonzero = [a for a in raw if a]
    if not nonzero:
        return None
    share = sum(a > 0 for a in nonzero) / len(nonzero)
    return "positive" if share > 0.5 else "negative" if share < 0.5 else None


def by_balance(raw, balances, card: bool) -> str | None:
    """For consecutive rows the balance moves by +amount or −amount; both file orders are tried. Clear at 90% of the
    computable pairs (at least 2). On a card the balance is what's owed (Engineering choice 10), so the verdict flips."""
    if len(balances) != len(raw):
        return None
    pairs = [(raw[i], raw[i + 1], balances[i], balances[i + 1]) for i in range(len(raw) - 1)
             if balances[i] is not None and balances[i + 1] is not None]
    if len(pairs) < 2:
        return None
    counts = {"old+": 0, "old-": 0, "new+": 0, "new-": 0}
    for a0, a1, b0, b1 in pairs:
        counts["old+"] += b1 - b0 == a1
        counts["old-"] += b1 - b0 == -a1
        counts["new+"] += b0 - b1 == a0
        counts["new-"] += b0 - b1 == -a0
    best = max(counts, key=lambda k: counts[k])
    if counts[best] < BALANCE_AGREES * len(pairs):
        return None
    rises_with_amount = best.endswith("+")
    if card:
        return "negate" if rises_with_amount else "as_is"
    return "as_is" if rises_with_amount else "negate"


def by_words(raw, descriptions, card: bool) -> str | None:
    """A card's payment rows, or a bank's deposit rows: at least 3, all one sign, and at least 80% of the other rows
    the opposite sign. Payments (or deposits) positive means the file is as Steward keeps it."""
    words = _PAYMENT if card else _DEPOSIT
    hits = [a for a, d in zip(raw, descriptions) if a and words.search(d)]
    rest = [a for a, d in zip(raw, descriptions) if a and not words.search(d)]
    if len(hits) < WORD_ROWS:
        return None
    signs = {a > 0 for a in hits}
    if len(signs) != 1 or not rest:
        return None
    positive = signs.pop()
    if sum((a > 0) != positive for a in rest) < OTHERS_AGREE * len(rest):
        return None
    return "as_is" if positive else "negate"


def _evidence(parsed: Parsed, card: bool) -> Verdict:
    descriptions = [r.raw_description for r in parsed.rows]
    return Verdict(by_balance(parsed.raw, parsed.balances, card) or by_words(parsed.raw, descriptions, card),
                   lean(parsed.raw))


def file_sign(layout: Layout, parsed: Parsed) -> dict[str, dict]:
    """Both kinds of account, so the web can show the question for whichever account the person picks (P11)."""
    if not layout.needs_sign:
        fixed = {"verdict": "negate" if layout.negate else "as_is", "lean": None}
        return {"credit": dict(fixed), "bank": dict(fixed)}
    return {"credit": asdict(_evidence(parsed, True)), "bank": asdict(_evidence(parsed, False))}
