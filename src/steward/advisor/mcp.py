"""MCP calls waiting for the gateway's word (spec 7, ruling 1): the exact part a tool produced, kept in this process
for one minute under a one-time call id. The gateway checks the part; only then is this copy written to the book's log.
Nothing here is stored: a restart drops waiting calls, and Claude Code calls the tool again."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime

from steward_boundary import tools as T

PENDING_S = 60
MAX_PENDING = 200


@dataclass(frozen=True)
class PendingCall:
    book_id: int
    user_id: int
    turn_id: str
    part: dict
    expires: datetime


def offered(kind: str) -> list[str]:
    """The book kind's tools without merchant_detail (spec 7, ruling 7), sorted by name as chat sends them."""
    return [t.name for t in T.TOOLS if kind in t.books and t.name != T.MERCHANT]


class PendingCalls:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, PendingCall] = {}

    def put(self, call_id: str, call: PendingCall, now: datetime) -> None:
        """Drops expired calls, keeps at most 200 (oldest dropped first), then keeps this one."""
        with self._lock:
            self._calls = {k: v for k, v in self._calls.items() if v.expires > now}
            while len(self._calls) >= MAX_PENDING:
                self._calls.pop(next(iter(self._calls)))
            self._calls[call_id] = call

    def take(self, call_id: str, book_id: int, user_id: int, now: datetime) -> PendingCall | None:
        """One use: the call leaves the store whatever the answer. Another book's or person's call isn't taken."""
        with self._lock:
            call = self._calls.get(call_id)
            if call is None or call.book_id != book_id or call.user_id != user_id:
                return None
            del self._calls[call_id]
        return call if call.expires > now else None
