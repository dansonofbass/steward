"""The live turns in this NAS process (plan B rulings 7, 8): the person's Stop, and their answer to a store-names card.
Keyed by turn id; only the person whose turn it is, in its book, can stop or answer it, and an answer to a card counts
only with the hash of that card (Task 6.5), so a forged, replayed or stale answer, or one for a different list of
names, is refused. Whether the person is a manager is checked by the route and again by the turn when the answer
arrives, never here. release() is the browser going away: it ends a waiting card or the Stop poll at once. Nothing here
is stored: a restart ends every live turn, as it ends their streams. An OK can carry the rows the manager ticked to
send a recipient's name too (public issue #1); ticked() reads them once the OK is in, and a decline keeps none."""
from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass, field


@dataclass
class _Live:
    user_id: int
    book_id: int
    cv: threading.Condition = field(default_factory=threading.Condition)
    stopped: bool = False
    gone: bool = False
    waiting: str | None = None
    digest: str | None = None
    answer: str | None = None
    ticked: frozenset[str] = frozenset()


class Control:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, _Live] = {}

    def begin(self, turn_id: str, user_id: int, book_id: int) -> None:
        with self._lock:
            self._turns[turn_id] = _Live(user_id, book_id)

    def end(self, turn_id: str) -> None:
        with self._lock:
            self._turns.pop(turn_id, None)

    def _get(self, turn_id: str, user_id: int | None = None, book_id: int | None = None) -> _Live | None:
        with self._lock:
            live = self._turns.get(turn_id)
        if live is None or (user_id is not None and (live.user_id, live.book_id) != (user_id, book_id)):
            return None
        return live

    def why_stopped(self, turn_id: str) -> str | None:
        """"gone" once the browser went away, "stopped" once the person pressed Stop, else None."""
        live = self._get(turn_id)
        if live is None:
            return None
        return "gone" if live.gone else "stopped" if live.stopped else None

    def is_stopped(self, turn_id: str) -> bool:
        return self.why_stopped(turn_id) is not None

    def stop(self, turn_id: str, user_id: int, book_id: int) -> bool:
        live = self._get(turn_id, user_id, book_id)
        if live is None:
            return False
        with live.cv:
            live.stopped = True
            live.cv.notify_all()
        return True

    def release(self, turn_id: str) -> None:
        """The browser reading this turn went away: a waiting card or the reply poll ends now, not in 10 minutes."""
        live = self._get(turn_id)
        if live is None:
            return
        with live.cv:
            live.gone = True
            live.cv.notify_all()

    def answer(self, turn_id: str, call_id: str, user_id: int, book_id: int, send: bool,
               digest: str | None = None, ticked=()) -> bool:
        live = self._get(turn_id, user_id, book_id)
        if live is None:
            return False
        with live.cv:
            if live.waiting != call_id or live.answer is not None or live.stopped or live.gone:
                return False
            if live.digest is not None and not (isinstance(digest, str)
                                                and hmac.compare_digest(digest.encode(), live.digest.encode())):
                return False
            live.answer = "send" if send else "decline"
            live.ticked = frozenset(ticked) if send else frozenset()
            live.cv.notify_all()
        return True

    def ticked(self, turn_id: str) -> frozenset[str]:
        """The rows ticked with the last OK for this turn ("r0", "p2"), checked against the card by the turn."""
        live = self._get(turn_id)
        return live.ticked if live is not None else frozenset()

    def wait_for_ok(self, turn_id: str, call_id: str, timeout: float, digest: str | None = None) -> str:
        """"send", "decline", "stopped", "gone" or "timeout". `digest` is the hash of the card shown; an answer
        counts only if it carries it."""
        live = self._get(turn_id)
        if live is None:
            return "stopped"
        with live.cv:
            live.waiting, live.digest, live.answer, live.ticked = call_id, digest, None, frozenset()
            live.cv.notify_all()          # the card is up: wakes whatever waits to see it (tests); nothing else waits
            answered = live.cv.wait_for(lambda: live.stopped or live.gone or live.answer is not None, timeout)
            live.waiting, live.digest = None, None
            if live.gone:
                return "gone"
            if live.stopped:
                return "stopped"
            return live.answer if answered else "timeout"
