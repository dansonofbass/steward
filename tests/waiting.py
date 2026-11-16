"""Condition waits with a ceiling: the one place a test polls, or waits on a live turn (flaky-test audit; JR's rule).
A test waits until the thing has happened and fails after CEILING seconds if it never does. It never sleeps a fixed
time and hopes. The ceiling matters only when something is broken, so it is generous; it stays under the books' 30 s
busy timeout and the 30 s card waits the tests use, so it still tells "waited for the lock" from "answered"."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

CEILING = 20.0


def wait_until(cond: Callable[[], object], what: str, ceiling: float = CEILING) -> None:
    """Returns as soon as cond() is true; fails, naming `what`, after `ceiling` seconds."""
    deadline = time.monotonic() + ceiling
    while not cond():
        if time.monotonic() >= deadline:
            raise AssertionError(f"waited {ceiling:g} s for {what}")
        time.sleep(0.005)


def wait_for_card(control, turn_id: str, call_id: str | None = None, ceiling: float = CEILING) -> None:
    """Returns once the live turn waits on a store-names card (this call's, or any). The turn begins lazily inside
    run_turn, so first wait for it to exist. Control.wait_for_ok wakes the turn's condition when it starts waiting,
    so the second wait is for the real event and doesn't poll."""
    wait_until(lambda: turn_id in control._turns, f"turn {turn_id} to begin", ceiling)
    live = control._turns[turn_id]
    with live.cv:
        ok = live.cv.wait_for(lambda: live.waiting is not None and call_id in (None, live.waiting), ceiling)
    if not ok:
        raise AssertionError(f"turn {turn_id} never waited on {call_id or 'a card'} within {ceiling:g} s")


class Later(threading.Thread):
    """fn on a daemon thread. done() joins it within the ceiling and re-raises whatever it raised."""

    def __init__(self, fn: Callable[[], object]):
        super().__init__(daemon=True)
        self.fn, self.error = fn, None

    def run(self) -> None:
        try:
            self.fn()
        except BaseException as e:  # noqa: BLE001 - handed back to the test by done()
            self.error = e

    def done(self, ceiling: float = CEILING) -> None:
        self.join(ceiling)
        assert not self.is_alive(), f"the helper thread was still running after {ceiling:g} s"
        if self.error is not None:
            raise self.error


def when_waiting(control, turn_id: str, then: Callable[[], object], call_id: str | None = None,
                 ceiling: float = CEILING) -> Later:
    """Runs then() on another thread once the turn waits on its card. This replaces threading.Timer(0.05, ...),
    whose answer, Stop or release could land before the wait it was meant for."""
    def run():
        wait_for_card(control, turn_id, call_id, ceiling)
        then()
    t = Later(run)
    t.start()
    return t
