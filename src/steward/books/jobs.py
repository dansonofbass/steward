"""Jobs that run over every book (spec 2.7)."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.books.owners import default_owner
from steward.books.registry import BookRegistry
from steward.db.models import EventLog
from steward.events import log_event
from steward.inventory.accounts import parent_hook
from steward.services.simplefin.sync import SYNC_FAILED, SyncResult, sync_now

log = logging.getLogger("steward.books")


def _record_failure(books: BookRegistry, book) -> None:
    """In the book's own events, once while it stays unresolved."""
    try:
        with Session(books.engine_for(book)) as db:
            if db.scalar(select(EventLog.id).where(EventLog.message == SYNC_FAILED, EventLog.resolved_at.is_(None))) is None:
                log_event(db, "error", "sync", SYNC_FAILED)
                db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Couldn't record the sync failure for book %s", book.id)


def sync_all_books(books: BookRegistry, http, model, now: datetime, allowed_hosts,
                   only: str | None = None) -> dict[str, SyncResult | str]:
    """Sync every book that has a SimpleFIN link, each with its own link and lock. One book's failure is logged in
    that book and doesn't stop the others."""
    out: dict[str, SyncResult | str] = {}
    for book in books.books():
        if only is not None and book.slug != only:
            continue
        if book.id in books.unavailable:
            out[book.slug] = "unavailable"
            continue
        lock = books.sync_lock(book.id)
        if not lock.acquire(blocking=False):
            out[book.slug] = "busy"   # an on-demand sync is running; the next tick catches up
            continue
        try:
            res = sync_now(books.engine_for(book), http, model, now, allowed_hosts,
                           default_owner=default_owner(book.owner_names), after=parent_hook(book.kind), household=book.kind == "household")
            out[book.slug] = "not linked" if res is None else res
        except Exception:  # noqa: BLE001 - one book must not sink the others
            log.exception("Scheduled SimpleFIN sync failed for book %s", book.id)
            _record_failure(books, book)
            out[book.slug] = "failed"
        finally:
            lock.release()
    return out
