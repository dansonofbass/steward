"""The suggester (spec 3.3): proposes items for what a book's transactions and tax forms show but its inventory
doesn't list. Pure functions over plain values; every name list is in data/patterns.json (tests:
tests/test_suggester_patterns.py). Signals, in order: a recurring deposit from an income-like payer (income), a
recurring payment to an insurer or premium (insurance), interest or dividends naming a bank with no item (account),
recurring transfers with such a bank (account), and tax forms (rulings 19, 20)."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.services.transactions import tidy

DATA = Path(__file__).parent / "data" / "patterns.json"


@dataclass(frozen=True)
class Patterns:
    abbreviations: dict[str, str]
    noise: frozenset[str]
    keep_before: dict[str, frozenset[str]]
    special: tuple[tuple[re.Pattern, str, str, str], ...]
    income_words: tuple[tuple[str, re.Pattern], ...]
    insurers: re.Pattern
    insurer_words: re.Pattern
    premium_words: re.Pattern
    insurance_types: tuple[tuple[str, re.Pattern, bool], ...]
    bank_words: re.Pattern
    institutions: re.Pattern
    brokerages: re.Pattern
    interest_words: re.Pattern
    dividend_words: re.Pattern
    transfer_words: re.Pattern
    acronyms: frozenset[str]
    generic: frozenset[str]


def _words(words) -> re.Pattern:
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![A-Z0-9])({alts})(?![A-Z0-9])")


@cache
def patterns() -> Patterns:
    raw = json.loads(DATA.read_text())
    return Patterns(
        abbreviations=dict(raw["abbreviations"]), noise=frozenset(raw["noise"]),
        keep_before={k: frozenset(v) for k, v in raw["keep_before"].items()},
        special=tuple((re.compile(s["pattern"]), s["key"], s["name"], s["income"]) for s in raw["special_payers"]),
        income_words=tuple((src, _words(ws)) for src, ws in raw["income_words"].items()),
        insurers=_words(raw["insurers"]), insurer_words=_words(raw["insurer_words"]),
        premium_words=_words(raw["premium_words"]),
        insurance_types=tuple((t["type"], _words(t["words"]), bool(t["explain"])) for t in raw["insurance_types"]),
        bank_words=_words(raw["bank_words"]), institutions=_words(raw["institutions"]),
        brokerages=_words(raw["brokerages"]), interest_words=_words(raw["interest_words"]),
        dividend_words=_words(raw["dividend_words"]), transfer_words=_words(raw["transfer_words"]),
        acronyms=frozenset(raw["acronyms"]), generic=frozenset(raw["generic"]),
    )


@dataclass(frozen=True)
class Txn:
    id: int
    account_id: int
    posted_at: date
    amount_cents: int
    raw: str


@dataclass(frozen=True)
class Form:
    id: int
    form: str
    tax_year: int
    payer: str
    payer_key: str
    last4: str | None
    boxes: dict


@dataclass(frozen=True)
class ItemFact:
    id: int
    kind: str
    status: str
    institution_key: tuple[str, ...]
    match_text: str | None
    type: str | None
    last4: str | None
    account_id: int | None


@dataclass
class Candidate:
    kind: str
    payer_key: str
    payer_name: str
    signal: str
    guess: str | None = None
    hint_word: str | None = None
    amount_cents: int | None = None
    frequency: str | None = None
    usual_day: int | None = None
    account_id: int | None = None
    txn_ids: list[int] = field(default_factory=list)
    count: int = 0
    form_ids: list[int] = field(default_factory=list)
    related_item_id: int | None = None
    match_text: str | None = None


def payer(raw: str) -> tuple[tuple[str, ...], str] | None:
    """The words that name who paid or was paid, and how to show them: "HARBOR SAVINGS BK INT XFER" →
    (("HARBOR", "SAVINGS", "BANK"), "Harbor Savings Bank"). None when nothing identifying is left."""
    P = patterns()
    s = tidy(raw)
    for rx, key, name, _ in P.special:
        if rx.search(s):
            return tuple(key.split()), name
    words: list[str] = []
    for w in re.findall(r"[A-Z][A-Z&']*", s):
        words.extend(P.abbreviations.get(w, w).split())
    out = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if len(w) < 2 or (w in P.noise and nxt not in P.keep_before.get(w, frozenset())):
            continue
        out.append(w)
    out = out[:4]
    if not out or all(w in P.generic for w in out):
        return None
    return tuple(out), " ".join(w if w in P.acronyms else w.capitalize() for w in out)


def key_text(words: tuple[str, ...]) -> str:
    return " ".join(words)


def item_key(text: str | None) -> tuple[str, ...]:
    got = payer(text) if text else None
    return got[0] if got else ()


def overlaps(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """One names the other ("Harbor Savings" and "Harbor Savings Bank") and they share a word that isn't generic."""
    sa, sb = set(a), set(b)
    if not sa or not sb or not (sa <= sb or sb <= sa):
        return False
    return bool((sa & sb) - patterns().generic)


def cadence(dates: list[date]) -> str | None:
    ds = sorted(set(dates))
    if len(ds) < 2:
        return None
    gap = median((b - a).days for a, b in zip(ds, ds[1:]))
    if 25 <= gap <= 35 and len(ds) >= 3:
        return "monthly"
    if 80 <= gap <= 100:
        return "quarterly"
    if 170 <= gap <= 195:
        return "half_yearly"
    if 350 <= gap <= 380:
        return "yearly"
    return None


def steady(amounts: list[int]) -> bool:
    mid = median(abs(a) for a in amounts)
    return sum(abs(abs(a) - mid) <= mid * 0.1 for a in amounts) >= 0.75 * len(amounts)


def _income_source(key: tuple[str, ...], text: str) -> str | None:
    P = patterns()
    for _, k, _, src in P.special:
        if tuple(k.split()) == key:
            return src
    for src, rx in P.income_words:
        if rx.search(text):
            return src
    return None


def _insurance_type(text: str) -> tuple[str | None, str | None]:
    for typ, rx, explain in patterns().insurance_types:
        m = rx.search(text)
        if m:
            return typ, (m.group(1) if explain else None)
    return None, None


def _cand(kind: str, key: tuple[str, ...], name: str, signal: str, ts: list[Txn], freq: str | None,
          guess: str | None = None, hint: str | None = None) -> Candidate:
    ts = sorted(ts, key=lambda t: (t.posted_at, t.id), reverse=True)
    return Candidate(
        kind, key_text(key), name, signal, guess, hint,
        amount_cents=int(round(median(abs(t.amount_cents) for t in ts))) if freq else None,
        frequency=freq, usual_day=int(round(median(t.posted_at.day for t in ts))) if freq else None,
        account_id=Counter(t.account_id for t in ts).most_common(1)[0][0],
        txn_ids=[t.id for t in ts][:12], count=len(ts), match_text=tidy(ts[0].raw)[:120])


def _form_candidates(f: Form) -> list[Candidate]:
    P, key, b = patterns(), f.payer_key, f.boxes
    base = {"payer_key": key, "payer_name": f.payer, "signal": "form", "form_ids": [f.id]}
    if f.form == "1099-INT":
        return [Candidate("account", guess="savings", **base)]
    if f.form == "1099-DIV":
        return [Candidate("account", guess="brokerage", **base)]
    if f.form == "SSA-1099":
        net = b.get("box_5") or b.get("box_3")
        return [Candidate("income", guess="social_security", frequency="monthly",
                          amount_cents=round(net / 12) if net else None, **base)]
    code = str(b.get("box_7") or "").upper()
    if P.insurers.search(key) or P.insurer_words.search(key) or "ANNUITY" in key:
        source, account = "annuity", "annuity"
    elif P.brokerages.search(key) or re.search(r"\bIRA\b", key):
        source, account = "rmd", "ira"
    else:
        source, account = "pension", None
    out = []
    if "G" not in code:
        gross = b.get("box_1")
        out.append(Candidate("income", guess=source, frequency="monthly",
                             amount_cents=round(gross / 12) if gross else None, **base))
    if account or "G" in code:
        out.append(Candidate("account", guess=account or "ira", **{**base, "form_ids": [f.id]}))
    return out


def _matched(c: Candidate, key: tuple[str, ...], items: list[ItemFact], raw_by_id: dict[int, str]) -> bool:
    for i in items:
        if i.kind != c.kind:
            continue
        if overlaps(i.institution_key, key):
            return True
        if i.match_text and any(i.match_text.upper() in raw_by_id.get(t, "") for t in c.txn_ids):
            return True
        if c.kind == "income" and c.guess == "social_security" and i.type == "social_security":
            return True
    return False


_ORDER = {"income": 0, "insurance": 1, "account": 2}


def candidates(txns: list[Txn], forms: list[Form], items: list[ItemFact]) -> list[Candidate]:
    P = patterns()
    groups: dict[tuple[str, ...], list[Txn]] = {}
    names: dict[tuple[str, ...], str] = {}
    norm: dict[int, str] = {}
    for t in txns:
        norm[t.id] = tidy(t.raw)
        got = payer(t.raw)
        if got is None:
            continue
        groups.setdefault(got[0], []).append(t)
        names[got[0]] = got[1]
    found: dict[tuple[str, tuple[str, ...]], Candidate] = {}
    for key, ts in groups.items():
        text = " | ".join(sorted({norm[t.id] for t in ts}))
        deps = [t for t in ts if t.amount_cents > 0]
        pays = [t for t in ts if t.amount_cents < 0]
        name, words = names[key], key_text(key)
        source = _income_source(key, text)
        dep_freq = cadence([t.posted_at for t in deps]) if deps else None
        pay_freq = cadence([t.posted_at for t in pays]) if pays else None
        if source and dep_freq and steady([t.amount_cents for t in deps]):
            found[("income", key)] = _cand("income", key, name, "income", deps, dep_freq, guess=source)
        elif (pay_freq and steady([t.amount_cents for t in pays])
              and (P.insurers.search(text) or P.insurer_words.search(text) or P.premium_words.search(text))):
            typ, hint = _insurance_type(text)
            found[("insurance", key)] = _cand("insurance", key, name, "insurance", pays, pay_freq, guess=typ, hint=hint)
        if not (P.bank_words.search(words) or P.institutions.search(words)):
            continue
        interest = [t for t in deps if P.interest_words.search(norm[t.id])]
        dividends = [t for t in deps if P.dividend_words.search(norm[t.id])]
        if (interest or dividends) and ("income", key) not in found:
            signal = "interest" if interest else "dividend"
            found[("account", key)] = _cand("account", key, name, signal, interest or dividends, None,
                                            guess="savings" if interest else "brokerage")
        else:
            moves = [t for t in ts if P.transfer_words.search(norm[t.id])]
            if len(moves) >= 2 and ("account", key) not in found:
                found[("account", key)] = _cand("account", key, name, "transfer", moves, None)
    for f in forms:
        for c in _form_candidates(f):
            k = (c.kind, tuple(c.payer_key.split()))
            if k in found:
                found[k].form_ids.append(f.id)
            else:
                found[k] = c
    out = []
    for (kind, key), c in found.items():
        if _matched(c, key, items, norm):
            continue
        if kind == "income":
            c.related_item_id = next((i.id for i in items if i.kind == "account" and overlaps(i.institution_key, key)), None)
        out.append(c)
    return sorted(out, key=lambda c: (_ORDER[c.kind], c.payer_name))


def read_inputs(db: Session) -> tuple[list[Txn], list[Form], list[ItemFact]]:
    """The book's transactions (without transfers paired between the parent's own accounts), tax forms and item facts."""
    from steward.db.models import InventoryItem, TaxForm, Transaction
    txns = [Txn(*r) for r in db.execute(select(Transaction.id, Transaction.account_id, Transaction.posted_at,
                                               Transaction.amount_cents, Transaction.raw_description)
                                        .where(Transaction.transfer_peer_id.is_(None)))]
    forms = [Form(f.id, f.form, f.tax_year, f.payer, f.payer_key, f.last4, json.loads(f.boxes or "{}"))
             for f in db.scalars(select(TaxForm))]
    items = []
    for i in db.scalars(select(InventoryItem)):
        d = json.loads(i.details or "{}")
        key = item_key(i.institution) or (item_key(i.name) if i.kind == "income" else ())
        items.append(ItemFact(i.id, i.kind, i.status, key, d.get("match_text"), d.get("type") or d.get("source"),
                              i.last4, i.account_id))
    return txns, forms, items
