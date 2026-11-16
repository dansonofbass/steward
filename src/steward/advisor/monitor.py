"""What the NAS knows about the gateway (spec 3.2, 4.6): the last health answer and when it came, polled every 60
seconds and on demand when older than 10 seconds, and the nightly check that every hash the gateway sent for a book is
in that book's log."""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.advisor.control import Control
from steward.advisor.gateway import GatewayClient, GatewayRefused, GatewayUnavailable
from steward.advisor.mcp import PendingCalls
from steward.db.models import AdvisorOutgoing, EventLog
from steward import clock
from steward.events import log_event

CROSSCHECK_AT = time(3, 30)
MISSING = "Steward found something sent to Claude that isn't in the log"


class AdvisorMonitor:
    def __init__(self, client: GatewayClient | None, books, now: Callable[[], datetime] = deps.now):
        self.client, self.books, self.now = client, books, now
        self.started_at = now()
        self._lock = threading.Lock()
        self.health: dict | None = None
        self.checked_at: datetime | None = None
        self.last_ok: datetime | None = None
        self.checked_on: date | None = None

    def poll(self) -> dict | None:
        if self.client is None:
            return None
        try:
            h = self.client.health()
        except (GatewayUnavailable, GatewayRefused):
            h = None
        with self._lock:
            self.health, self.checked_at = h, self.now()
            if h is not None:
                self.last_ok = self.checked_at
        return h

    def forget(self) -> None:
        """A different gateway client: what the old one last said no longer counts."""
        with self._lock:
            self.health = self.checked_at = self.last_ok = None

    def away_for(self, now: datetime) -> timedelta:
        """How long the gateway hasn't answered: since its last answer, or since Steward started if it never has; zero
        while the newest check got an answer."""
        with self._lock:
            if self.health is not None:
                return timedelta(0)
            since = self.last_ok or self.started_at
        return max(timedelta(0), now - since)

    def fresh(self, max_age_s: float = 10.0) -> dict | None:
        with self._lock:
            stale = self.checked_at is None or (self.now() - self.checked_at).total_seconds() > max_age_s
            current = self.health
        return self.poll() if stale else current

    def tick(self) -> None:
        """Every 60 seconds (spec 3.2): ask for health; after 3:30 AM household time, once a day, the cross-check."""
        self.poll()
        local = self.now().astimezone(clock.household_tz())
        if self.client is not None and local.time() >= CROSSCHECK_AT and self.checked_on != local.date():
            try:
                crosscheck(self.books, self.client, self.now())
            except (GatewayUnavailable, GatewayRefused):
                return                  # the gateway is asleep or away: try again at the next tick
            self.checked_on = local.date()   # marked only after a check that worked


def crosscheck(books, client, now: datetime, window: timedelta = timedelta(hours=48)) -> int:
    """Spec 4.6: every hash the gateway sent for a book must be in that book's log. A missing one goes to the book's
    Home (an actionable event) and to the directory events, once. Rows with channel "check" belong to no book
    (ruling 13)."""
    wanted: dict[int, dict[str, dict]] = {}
    for r in client.sent_since(now - window)["sent"]:
        if r.get("channel") != "check" and r.get("book_id") is not None:
            wanted.setdefault(r["book_id"], {})[r["sha256"]] = r
    missing = 0
    for book in books.books():
        hashes = wanted.pop(book.id, {})
        if not hashes or book.id in books.unavailable:
            continue
        with Session(books.engine_for(book)) as db:
            have = set(db.scalars(select(AdvisorOutgoing.sha256).where(AdvisorOutgoing.sha256.in_(list(hashes)))))
            for sha, r in hashes.items():
                if sha in have:
                    continue
                missing += 1
                # An absolute time plus the hash's first characters: the same text on every night's check, so the
                # 48-hour look-back finds the open event instead of adding another.
                sent = datetime.fromisoformat(r["at"]).astimezone(clock.household_tz())
                msg = f"{MISSING}, sent {sent.strftime('%b %-d, %Y at %-I:%M %p')} (ref {sha[:8]})."
                if db.scalar(select(EventLog.id).where(EventLog.kind == "chat", EventLog.message == msg,
                                                       EventLog.resolved_at.is_(None))) is None:
                    log_event(db, "error", "chat", msg, actionable=True)
                    books.log_event("error", "chat", msg, book_id=book.id)
            db.commit()
    for hashes in wanted.values():                   # a book that no longer exists
        missing += len(hashes)
        books.log_event("error", "chat", f"{MISSING}, for a book that no longer exists.", book_id=None)
    return missing


@dataclass
class AdvisorRuntime:
    client: GatewayClient | None
    monitor: AdvisorMonitor
    control: Control = field(default_factory=Control)
    mcp: PendingCalls = field(default_factory=PendingCalls)

    def use(self, client: GatewayClient) -> GatewayClient | None:
        """Swap the live client after a pairing (guided setup spec 6.2); returns the old one for its owner to close."""
        old, self.client = self.client, client
        self.monitor.client = client
        self.monitor.forget()
        return old
