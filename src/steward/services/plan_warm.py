"""Phase 18: Plan's first open after a restart found an empty solve cache (1.6 s on the NAS, 4.8 s seen on the phone),
and its first open after new figures did too. A low-priority thread works out each household book's plan at its saved
levers, as GET /plan does, so the open finds the answer. It runs at start-up and after each scheduled sync, off the
request path. A failure is logged and changes nothing."""
from __future__ import annotations

import logging
import os
import threading

from sqlalchemy.orm import Session

from steward import deps
from steward.books.people import attach_people
from steward.books.registry import BookInfo, BookRegistry, BookUnavailable
from steward.engine import EngineInputs
from steward.services.plan import latest_plan, saved_state, solve_cached
from steward.services.plan_inputs import SetupIncomplete, build_inputs
from steward.services.plan_levers import resolve_state

log = logging.getLogger(__name__)
NICE = 10   # Linux: os.nice lowers only the calling thread, so requests keep their priority


def warm_book(books: BookRegistry, book: BookInfo) -> bool:
    """GET /plan's solve for one book, into its cache. False when there is no plan to work out: not a household,
    can't be opened, or setup unfinished."""
    if book.kind != "household":
        return False
    try:
        engine = books.engine_for(book)
    except BookUnavailable:
        return False
    cache = books.plan_cache(book.id)
    today = deps.today()
    with Session(engine.execution_options(read=True)) as db:
        attach_people(db, lambda: books.people(book.id))
        try:
            pi = cache.inputs.get_or_build(today, lambda: build_inputs(db, today))
        except SetupIncomplete:
            return False
        state, _ = resolve_state({}, saved_state(latest_plan(db)), pi.household, pi.observed)
        db.rollback()                                    # nothing is held while the engine runs
    solve_cached(cache, EngineInputs(pi.household, state.assumed))
    return True


def warm_all(books: BookRegistry, stop: threading.Event) -> None:
    try:
        household_books = list(books.books())
    except Exception:  # noqa: BLE001 - warming must never be the thing that fails
        log.exception("Couldn't warm the plan")
        return
    for book in household_books:
        if stop.is_set():
            return
        try:
            warm_book(books, book)
        except Exception:  # noqa: BLE001 - warming must never be the thing that fails
            log.exception("Couldn't warm the plan for book %s", book.id)


class PlanWarmer:
    """One nice'd thread at a time. A kick while it runs asks for one more pass after it, however many kicks."""

    def __init__(self, books: BookRegistry | None):
        self.books = books
        self._lock = threading.Lock()
        self._running = False
        self._again = False
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def kick(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            if self._running:
                self._again = True
                return
            self._running = True
        threading.Thread(target=self._run, name="steward-plan-warm", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            os.nice(NICE)
        except OSError:
            pass
        done = False
        try:
            while True:
                try:
                    warm_all(self.books, self._stop)
                except Exception:  # noqa: BLE001 - a failed pass is logged and changes nothing
                    log.exception("Couldn't warm the plan")
                with self._lock:
                    if not self._again or self._stop.is_set():
                        self._running = False        # with the decision, so a kick after it starts a new pass
                        done = True
                        return
                    self._again = False
        finally:
            if not done:                             # the thread is dying some other way: let the next kick start one
                with self._lock:
                    self._running = False
