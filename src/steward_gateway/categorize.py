"""The categorizer (spec 6.1): an 8B model in Ollama on the gateway, local only. Rows come from the NAS with digits
already masked. Ten rows go in one prompt and up to `parallel` prompts run at once (ruling 9); the answer is held to a
JSON schema of the allowed categories, a merchant and a confidence. Below confidence 0.6 a row is
`uncategorized` with the model's category kept as a guess (phase 12 decision 4); `transfer` is never the model's to
give (ruling 8); a merchant is kept only when its words are the description's own. Nothing here logs a description,
a merchant or a category."""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx2

from steward_boundary import vocab as V
from steward_gateway.ollama import OPTIONS, ThinkCheck

# transfer and investment come from rules; reimbursement only from a person or a rule (reimbursable spec, Privacy)
ALLOWED = tuple(c for c in V.CATEGORIES if c not in ("transfer", "investment", "reimbursement"))
MIN_CONFIDENCE = 0.6
CHUNK = 10
MAX_BATCH = 50
MAX_DESCRIPTION = 200
MERCHANT_MAX = 60
TAGS_EVERY_S = 60.0
CATEGORIZER_AWAY = "The categorizer on this machine isn't answering."
GUIDE = {
    "groceries": "supermarkets, food markets, co-ops", "dining": "restaurants, cafes, coffee, takeout",
    "housing": "rent, HOA dues, property management", "utilities": "water, electric, gas, internet, phone, trash",
    "transport": "fuel, parking, transit, tolls, car repair", "travel": "airlines, hotels, lodging, trains",
    "health": "doctors, dentists, pharmacies, therapy, eye care", "insurance": "insurance premiums",
    "loan_payments": "car, student and personal loan payments (a credit card payment is not one)",
    "pets": "pet food, vets, groomers, boarding, pet supplies", "cash_atm": "ATM and cash withdrawals",
    "childcare_education": "daycare, preschool, tutoring, tuition, school fees",
    "giving": "church giving, charities, donations", "subscriptions": "streaming, apps, memberships billed monthly",
    "shopping": "general stores, clothing, electronics, books", "personal": "salons, barbers, gyms, dry cleaning",
    "kids": "toys, kids' clothes, kids' sports and lessons", "home": "hardware, garden, furniture, home services",
    "gifts": "florists, gift shops, cards", "entertainment": "movies, concerts, bowling, arcades, zoos",
    "income": "wages, salary, pensions and benefits coming in",
    "business_income": "consulting fees, client payments and paid invoices coming in",
    "business_expense": "office, coworking, business services", "taxes": "property, state and estimated taxes",
    "fees": "bank, ATM, late and overdraft fees", "interest": "interest, APY and dividends earned",
    "uncategorized": "the description doesn't say what it was",
}
CATEGORIZER_FEATURES = ("guess", "examples")      # what /v1/health advertises (phase 12 ruling 15)
MAX_EXAMPLES = 40
EXAMPLES_HEAD = "This family sorted these before:"
PROMPT = ("You sort bank transactions into spending categories for a family's books.\n"
          "Categories:\n{guide}\n\n"
          "For each numbered transaction give its number as i, the category, the store or payer as merchant (only "
          "words from the description, or an empty string) and your confidence from 0 to 1. Use uncategorized when "
          "the description doesn't say what was bought or who paid. Money in for consulting, a client or an invoice "
          "is business_income, not income; interest, APY or a dividend earned is interest, not income. Also give "
          "business from 0 to 1: for money out, how likely it is a cost of running a one-person consulting business "
          "(software, co-working, client travel, professional dues, education, office supplies); for money in, 0. "
          "Answer with JSON only.\n\n"
          "{examples}{lines}")
SCHEMA = {"type": "object", "properties": {"rows": {"type": "array", "items": {
    "type": "object",
    "properties": {"i": {"type": "integer"}, "category": {"type": "string", "enum": list(ALLOWED)},
                   "merchant": {"type": "string"}, "confidence": {"type": "number"},
                   "business": {"type": "number"}},
    "required": ["i", "category", "merchant", "confidence", "business"]}}}, "required": ["rows"]}


@dataclass(frozen=True)
class Row:
    description: str
    amount_cents: int


@dataclass(frozen=True)
class Example:
    """One of the household's own rules, masked as rows are (phase 12 decision 3)."""
    description: str
    category: str


@dataclass(frozen=True)
class Answer:
    category: str
    merchant: str | None
    business: int | None = None      # how likely money out is a business cost, 0-100 (business plan ruling 5)
    confidence: float | None = None  # the model's own, 0-1 (phase 12 decision 4); None when it gave none
    guess: str | None = None         # under MIN_CONFIDENCE: the category it would have given


def _examples_text(examples: Sequence[Example]) -> str:
    if not examples:
        return ""
    return EXAMPLES_HEAD + "\n" + "\n".join(f'- "{_quoted(e.description)}" is {e.category}' for e in examples) + "\n\n"


UNCATEGORIZED = Answer("uncategorized", None)


class CategorizerAway(Exception):
    """Ollama didn't answer, or answered with an error status."""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def clean_merchant(merchant: object, description: str) -> str | None:
    if not isinstance(merchant, str):
        return None
    m = " ".join(merchant.split())[:MERCHANT_MAX].strip(" .,-*#")
    words = _words(m)
    if not words or sum(c.isdigit() for c in m) > 4:
        return None
    have = set(_words(description))
    return m if all(w in have for w in words) else None


def _quoted(text: str) -> str:
    """A description made safe to sit inside quotes in the prompt: no quote or line break can end it early."""
    return text.replace('"', "'").replace("\r", " ").replace("\n", " ")


def _line(i: int, row: Row) -> str:
    way = "money in" if row.amount_cents > 0 else "money out"
    return f'{i}. "{_quoted(row.description)}" ({way}, ${abs(row.amount_cents) / 100:,.2f})'


def _number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and (not isinstance(v, float) or math.isfinite(v))


def _business(value: object, row: Row) -> int | None:
    """A whole percent for money out with a number from 0 to 1; nothing for money in or anything else."""
    if row.amount_cents >= 0 or not _number(value) or not 0 <= value <= 1:
        return None
    return round(value * 100)


class Categorizer:
    def __init__(self, url: str, model: str, *, http: httpx2.AsyncClient | None = None, parallel: int = 4,
                 timeout: float = 20.0):
        self.url, self.model, self.parallel, self.timeout = url.rstrip("/"), model, parallel, timeout
        self._http = http or httpx2.AsyncClient(timeout=timeout)
        self._sem = asyncio.Semaphore(parallel)
        self._at_ollama = 0             # prompts sent and not yet answered
        self._idle = asyncio.Event()     # set while no prompt is at Ollama: statement requests wait on it (P30)
        self._idle.set()
        self._tags: tuple[float, bool] | None = None
        self._failed_at: float | None = None
        self._thinks = ThinkCheck(self.url, model, self._http)

    async def close(self) -> None:
        await self._http.aclose()

    async def wait_idle(self) -> None:
        """Returns once no categorizer prompt is at Ollama (PDF statements spec P30: the categorizer goes first)."""
        while self._at_ollama > 0:
            await self._idle.wait()

    async def ready(self) -> bool:
        """Ollama answers and the configured model is pulled (ruling 17), remembered for a minute; and no batch has
        failed in the last minute (final review M4: a pulled model that can't load, say because another app has the
        GPU, isn't answering). No probe through /api/generate: one every minute would keep the model on the GPU around
        the clock (re-review N1)."""
        if self._failed_at is not None and time.monotonic() - self._failed_at < TAGS_EVERY_S:
            return False
        if self._tags and time.monotonic() - self._tags[0] < TAGS_EVERY_S:
            return self._tags[1]
        try:
            r = await self._http.get(self.url + "/api/tags", timeout=1.0)
            names = {m.get("name") for m in r.json().get("models", [])} if r.status_code == 200 else set()
        except (httpx2.HTTPError, ValueError, AttributeError, TypeError):
            names = set()
        ok = self.model in names or f"{self.model}:latest" in names
        self._tags = (time.monotonic(), ok)
        return ok

    def _body(self, rows: list[Row], think_off: bool, examples: Sequence[Example]) -> dict:
        guide = "\n".join(f"- {c}: {GUIDE[c]}" for c in ALLOWED)
        lines = "\n".join(_line(i, r) for i, r in enumerate(rows, 1))
        prompt = PROMPT.format(guide=guide, examples=_examples_text(examples), lines=lines)
        body = {"model": self.model, "prompt": prompt, "stream": False, "format": SCHEMA,
                "options": dict(OPTIONS), "keep_alive": "30m"}
        if think_off:
            body["think"] = False
        return body

    async def _chunk(self, rows: list[Row], examples: Sequence[Example]) -> list[Answer]:
        think_off = await self._thinks()
        async with self._sem:
            # Ollama may run fewer prompts at once than `parallel` (the gateway's runs one), and a prompt it queues
            # waits for the ones sent before it, inside this request's timeout. So each prompt ahead adds a
            # prompt's time, and the timeout still counts `timeout` from when Ollama gets to this one.
            ahead, self._at_ollama = self._at_ollama, self._at_ollama + 1
            self._idle.clear()
            try:
                r = await self._http.post(self.url + "/api/generate", json=self._body(rows, think_off, examples),
                                          timeout=self.timeout * (ahead + 1))
            except httpx2.HTTPError:
                self._failed_at = time.monotonic()
                raise CategorizerAway() from None
            finally:
                self._at_ollama -= 1
                if self._at_ollama == 0:
                    self._idle.set()
        if r.status_code != 200:
            self._failed_at = time.monotonic()
            raise CategorizerAway()
        self._failed_at = None
        answers = [UNCATEGORIZED] * len(rows)
        try:
            items = json.loads(r.json()["response"])["rows"]
        except (ValueError, KeyError, TypeError):
            return answers
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            i, category, confidence = item.get("i"), item.get("category"), item.get("confidence")
            if isinstance(i, bool) or not isinstance(i, int) or not 1 <= i <= len(rows):
                continue
            if category not in ALLOWED or not _number(confidence):
                continue
            conf = min(1.0, max(0.0, float(confidence)))
            row = rows[i - 1]
            if category == "uncategorized":
                answers[i - 1] = Answer("uncategorized", None, None, conf, None)
            elif conf < MIN_CONFIDENCE:
                answers[i - 1] = Answer("uncategorized", None, None, conf, category)      # kept as a guess
            else:
                answers[i - 1] = Answer(category, clean_merchant(item.get("merchant"), row.description),
                                        _business(item.get("business"), row), conf)
        return answers

    async def categorize(self, rows: list[Row], examples: Sequence[Example] = ()) -> list[Answer]:
        chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
        parts = await asyncio.gather(*(self._chunk(c, examples) for c in chunks))
        return [a for part in parts for a in part]
