"""Open-source evaluation 6.7: per-address limits on the doors someone can knock on without a password:
- forgot-password: each try can send an email;
- passkey sign-in options: each holds a challenge in ChallengeStore's 1000 slots;
- invite acceptance;
- the first-run setup link.
Shaped like ChallengeStore: in memory, one process serves the household, and a restart only forgets who knocked.
The words and the 15 minutes are the login lockout's (auth/users.py, api/auth.py).

The address is request.client: the tailnet device, from the X-Forwarded-For that tailscale serve or steward-proxy
sets, which `steward serve` trusts only from STEWARD_TRUSTED_PROXIES (tests/test_proxy_trust.py). Time is
steward.clock's, so tests move the fake clock instead of sleeping. Refused tries don't count, so a wait never grows."""
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil

from fastapi import HTTPException, Request

from steward import clock
from steward.auth.users import LOCK_AFTER, LOCK_MINUTES

MAX_ADDRESSES = 1000


@dataclass(frozen=True)
class Rule:
    tries: int
    window: timedelta


WINDOW = timedelta(minutes=LOCK_MINUTES)
FORGOT = Rule(LOCK_AFTER, WINDOW)        # 5: each can send an email; a link lives 15 minutes
PASSKEY_OPTIONS = Rule(30, WINDOW)       # far above a person retrying; far below ChallengeStore's 1000
INVITE_ACCEPT = Rule(10, WINDOW)         # a link works once; tokens are 32 random bytes
SETUP = Rule(10, WINDOW)                 # the first-run link (check and use): one person, a few tries
MAIL_TEST = Rule(5, WINDOW)              # each test sends a real email, to the signed-in manager only
PAIR = Rule(5, WINDOW)                   # pairing by code: Steward's 5 per device, beside the gateway's own window
CSP_REPORT = Rule(20, WINDOW)            # issue #14: each report writes a log line; a regression shows in the first few


def try_again(until: datetime, t: datetime) -> str:
    mins = max(1, ceil((until - t).total_seconds() / 60))
    return f"Too many tries. Try again in {mins} minute{'' if mins == 1 else 's'}."


class RateLimiter:
    def __init__(self, max_keys: int = MAX_ADDRESSES):
        self._max = max_keys
        self._lock = threading.Lock()
        self._hits: OrderedDict[tuple[str, str], deque[datetime]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._hits)

    def hit(self, door: str, rule: Rule, address: str, now: datetime) -> datetime | None:
        """Counts one try at `door` from `address`. None when it may go ahead, else when the next try may."""
        key = (door, address)
        with self._lock:
            stamps = self._hits.pop(key, None) or deque()
            while stamps and stamps[0] <= now - rule.window:
                stamps.popleft()
            refused = len(stamps) >= rule.tries
            if not refused:
                stamps.append(now)
            self._hits[key] = stamps                          # the most recently seen address is last
            while len(self._hits) > self._max:
                self._hits.popitem(last=False)
            return stamps[0] + rule.window if refused else None


def limit(door: str, rule: Rule) -> Callable[[Request], None]:
    """A route dependency: 429, with Retry-After and the lockout's words, once `rule` is used up at `door`."""
    def check(request: Request) -> None:
        address = request.client.host if request.client else "unknown"
        t = clock.now()
        until = request.app.state.rate_limits.hit(door, rule, address, t)
        if until is not None:
            raise HTTPException(429, detail={"error": try_again(until, t)},
                                headers={"Retry-After": str(max(1, ceil((until - t).total_seconds())))})
    return check
