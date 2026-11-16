"""The NAS's link to the categorizer (milestone 1 spec 5.5 step 3, milestone 3 spec 6.1). Once Steward is paired with
the gateway it asks the gateway (`/v1/categorize`, and `/v1/categorize/batch` for up to 50 rows) with the pairing token
(ruling 10). Digits are masked before anything is sent. Never raises: a failure returns None, leaves a plain-words
reason in `last_error`, starts a cool-off, and sets `missed` so the catch-up asks again later (ruling 11). The model may
never answer `transfer` or `uncategorized` (ruling 8)."""
import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx2

from steward.db.models import CATEGORIES
from steward_boundary.text import mask_numbers

BATCH = 50
MAX_DESCRIPTION = 200
# investment comes from the account type; reimbursement only from a person or a rule (reimbursable spec, Privacy)
NOT_FROM_MODEL = frozenset({"uncategorized", "transfer", "investment", "reimbursement"})
MAX_EXAMPLES = 40
Hit = tuple[str, str | None] | tuple[str, str | None, int]   # (category, merchant[, business 0-100])
Example = tuple[str, str]       # (a rule's pattern, its category); masked here before it leaves


@dataclass(frozen=True)
class Guess:
    """An unsure answer (phase 12 decision 4): the row stays unsorted and keeps the model's best guess, or none when
    the model couldn't tell. Falsy on purpose: every `if hit:` keeps meaning "the model sorted it"."""
    category: str | None
    pct: int | None

    def __bool__(self) -> bool:
        return False


def features_from(health: dict | None) -> frozenset[str]:
    """What the gateway's health says its categorizer can do (ruling 15); nothing from an old gateway."""
    feats = health.get("categorizer_features") if isinstance(health, dict) else None
    return frozenset(f for f in feats if isinstance(f, str)) if isinstance(feats, list) else frozenset()


class ModelClient(Protocol):
    last_error: str | None

    def categorize(self, description: str, amount_cents: int) -> Hit | None: ...


class NullModelClient:
    last_error: str | None = None
    missed: bool = False

    def close(self) -> None:
        pass

    def categorize(self, description: str, amount_cents: int) -> Hit | None:
        return None

    def categorize_batch(self, rows: Sequence[tuple[str, int]], examples: Sequence[Example] = ()) -> list[Hit | None] | None:
        return None             # no model looked at these rows: like a failed batch, nothing is marked asked


def _desc(description: str) -> str:
    return mask_numbers(description)[:MAX_DESCRIPTION]


def _pct(value: object) -> int | None:
    """The gateway's confidence as a percent; anything but a finite number in [0, 1] is no confidence at all."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return round(value * 100)


def _hit(item: dict, features: frozenset[str] = frozenset()) -> Hit | Guess | None:
    cat, merchant = item.get("category"), item.get("merchant")
    if cat == "uncategorized" and "guess" in features:
        guess = item.get("guess")
        if not isinstance(guess, str) or guess not in CATEGORIES or guess in NOT_FROM_MODEL:
            guess = None
        return Guess(guess, _pct(item.get("confidence")))
    if not isinstance(cat, str) or cat not in CATEGORIES or cat in NOT_FROM_MODEL:
        return None
    base = (cat, merchant[:200] if isinstance(merchant, str) and merchant else None)
    b = item.get("business")
    if isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= 100:
        return (*base, b)
    return base


def business_of(hit: Hit | Guess | None) -> int | None:
    """The model's business likelihood when it gave one (business plan ruling 5)."""
    return hit[2] if hit and len(hit) > 2 else None


class HttpModelClient:
    def __init__(self, url: str, timeout_s: float = 2.0, transport: httpx2.BaseTransport | None = None,
                 cooldown_s: float = 60.0, now: Callable[[], float] = time.monotonic, token: str | None = None,
                 batch_timeout_s: float = 10.0) -> None:
        self.url, self.cooldown_s, self._now, self.batch_timeout_s = url.rstrip("/"), cooldown_s, now, batch_timeout_s
        self._client = httpx2.Client(timeout=timeout_s, transport=transport)
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._failed_at: float | None = None
        self._one_batch = threading.Lock()
        self.last_error: str | None = None
        self.features: frozenset[str] = frozenset()    # set from the gateway's health; empty until it says
        self.missed = True              # until the first catch-up has run (ruling 11)

    def close(self) -> None:
        self._client.close()

    def _post(self, url: str, payload: dict, timeout: float | None = None):
        kw = {"timeout": timeout} if timeout is not None else {}
        return self._client.post(url, json=payload, headers=self._headers, **kw)

    def _fail(self, reason: str) -> None:
        self.last_error = reason
        self._failed_at = self._now()
        self.missed = True

    def _ok(self) -> None:
        self.last_error = None
        self._failed_at = None

    def _cooling(self) -> bool:
        if self._failed_at is not None and self._now() - self._failed_at < self.cooldown_s:
            self.missed = True          # a row went unasked; last_error stays as it was
            return True
        return False

    def _send(self, url: str, payload: dict, timeout: float | None = None):
        try:
            r = self._post(url, payload, timeout)
        except httpx2.TimeoutException:
            self._fail("the categorizer took too long to answer")
            return None
        except Exception:  # noqa: BLE001 - any failure means "model unavailable"
            self._fail("could not reach the categorizer")
            return None
        if r.status_code != 200:
            self._fail(f"the categorizer answered with an error (HTTP {r.status_code})")
            return None
        try:
            return r.json()
        except Exception:  # noqa: BLE001 - not JSON
            self._fail("the categorizer sent a reply that could not be read")
            return None

    def categorize(self, description: str, amount_cents: int) -> Hit | None:
        if self._cooling():
            return None
        body = self._send(self.url, {"description": _desc(description), "amount_cents": amount_cents})
        if body is None:
            return None
        if not isinstance(body, dict):
            self._fail("the categorizer sent a reply that could not be read")
            return None
        self._ok()
        return _hit(body, self.features)

    def categorize_batch(self, rows: Sequence[tuple[str, int]],
                         examples: Sequence[Example] = ()) -> list[Hit | Guess | None] | None:
        if not rows:
            return []
        if len(rows) > BATCH:
            raise ValueError(f"at most {BATCH} rows at a time")
        # One batch at a time: the gateway works through batches in turn (Ollama runs one prompt at a time), so a
        # batch sent alongside another waited for it inside its own timeout. Waiting here instead starts the timeout
        # when the gateway takes this batch. Callers ask with no transaction open, so the wait holds no lock on a book.
        payload: dict = {"rows": [{"description": _desc(d), "amount_cents": a} for d, a in rows]}
        if examples and "examples" in self.features:
            payload["examples"] = [{"description": _desc(d), "category": c} for d, c in examples[:MAX_EXAMPLES]]
        with self._one_batch:
            if self._cooling():
                return None
            body = self._send(self.url + "/batch", payload, self.batch_timeout_s)
        if body is None:
            return None
        items = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(items, list) or len(items) != len(rows) or not all(isinstance(i, dict) for i in items):
            self._fail("the categorizer sent a reply that could not be read")
            return None
        self._ok()
        return [_hit(i, self.features) for i in items]


def client_for(settings) -> HttpModelClient | NullModelClient:
    """STEWARD_CATEGORIZER_URL (development only), else the paired gateway, else nothing (ruling 10)."""
    if settings.categorizer_url:
        return HttpModelClient(settings.categorizer_url, settings.categorizer_timeout_s,
                               batch_timeout_s=settings.categorizer_batch_timeout_s)
    from steward.advisor.gateway import read_token
    token = read_token(settings) if settings.gateway_url else None
    if settings.gateway_url and token:
        return HttpModelClient(settings.gateway_url.rstrip("/") + "/v1/categorize", settings.categorizer_timeout_s,
                               token=token, batch_timeout_s=settings.categorizer_batch_timeout_s)
    return NullModelClient()
