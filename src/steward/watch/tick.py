"""The watch tick (ruling 17): every minute, for each parent book, the 6:30 AM run, the 7:00 AM summary and the
outbox. "Today" and both times are the household's (clock.household_tz()), so midnight and DST follow the household's time zone. Email is
sent outside any database transaction; one book's failure never stops the others."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta

import sqlcipher3
from sqlalchemy.orm import Session

from steward.books.registry import BookInfo, BookRegistry
from steward.db.models import MailOutbox
from steward import clock
from steward.inventory.accounts import run_safely
from steward.inventory.present import log_safe
from steward.mail import mail_ready
from steward.watch import vocab as V
from steward.watch.outbox import Sender, addresses, after_try, claim, deliver, due_rows, fail_unprepared, prepare, queue_summary
from steward.watch.run import WATCH_FAILED, run_daily
from steward.watch.store import DAILY_ON, SUMMARY_ON, get_state, set_state

log = logging.getLogger("steward.watch")


LOCK_RETRY_MINUTES = 2
LOCK_GIVE_UP = timedelta(minutes=30)


def _is_locked(e: Exception) -> bool:
    """A real SQLite lock: the driver's own OperationalError saying "locked" or "busy", not any database error."""
    orig = getattr(e, "orig", e)
    return (isinstance(orig, (sqlite3.OperationalError, sqlcipher3.OperationalError))
            and any(w in str(orig).lower() for w in ("locked", "busy")))


def _retry_soon(engine, row_id: int, now: datetime) -> None:
    """Leave a row that hit a lock pending and due again shortly; once the lock streak has lasted over 30 minutes, fail it with its event."""
    try:
        with Session(engine) as db:
            row = db.get(MailOutbox, row_id)
            if row is not None and row.status == "pending":
                if row.locked_since is None:
                    row.locked_since = now
                if now - row.locked_since > LOCK_GIVE_UP:
                    fail_unprepared(db, row, now)
                else:
                    row.next_try_at = now + timedelta(minutes=LOCK_RETRY_MINUTES)
            db.commit()
    except Exception as e:  # noqa: BLE001 - still locked: the row stays pending and is due again on the next tick
        log.error("The watch tick couldn't postpone mail row %s: %s", row_id, log_safe(e))


def _prepared(db, row, sender: Sender, today, now: datetime) -> bool:
    ok = prepare(db, row, sender, today, now)
    row.locked_since = None          # it got through: any lock streak is over
    return ok


def _claim_attempt(engine, row_id: int, sender: Sender, today, now: datetime):
    with Session(engine) as db:
        row = db.get(MailOutbox, row_id)
        if row.tries >= V.TRIES:     # claimed before and never finished (a crash): don't send it again
            after_try(db, row, [], json.loads(row.to_user_ids or "[]"), "Steward stopped before this finished.", now)
        elif _prepared(db, row, sender, today, now):
            claim(row, now)
            item = (row.id, json.loads(row.to_user_ids), json.loads(row.sent_to or "[]"), row.subject, row.text_body,
                    row.html_body)
            db.commit()
            return item
        db.commit()
        return None


def _claim_one(engine, row_id: int, sender: Sender, today, now: datetime):
    """Prepare one row and claim it (count the try, push the next one back) in one transaction, committed before any
    mail is sent. None when the row won't be sent. A failure that isn't a lock gets one more claim before the row is
    failed for good, since whatever tripped it (a lock that read as another error) may have cleared."""
    for attempt in (1, 2):
        try:
            return _claim_attempt(engine, row_id, sender, today, now)
        except Exception as e:  # noqa: BLE001 - a row that can't be rendered must not stop the others or the run
            log.error("The watch tick couldn't prepare mail row %s: %s", row_id, log_safe(e))
            if _is_locked(e):      # a brief lock is not a row that can't be rendered: leave it pending, try again shortly
                _retry_soon(engine, row_id, now)
                return None
    try:
        with Session(engine) as db:
            row = db.get(MailOutbox, row_id)
            if row is not None and row.status == "pending":
                fail_unprepared(db, row, now)
            db.commit()
    except Exception as e:  # noqa: BLE001 - a lock while failing the row leaves it pending for the next tick
        log.error("The watch tick couldn't fail mail row %s: %s", row_id, log_safe(e))
    return None


def watch_book(books: BookRegistry, book: BookInfo, mailer, settings, now: datetime) -> str:
    engine = books.engine_for(book)
    local = now.astimezone(clock.household_tz())
    today = local.date()
    sender = Sender(book, books.directory, settings.base_url, mail_ready(mailer))
    immediate = engine.execution_options(immediate=True)
    with Session(immediate) as db:
        if local.time() >= V.DAILY_AT and get_state(db, DAILY_ON) != today.isoformat():
            set_state(db, DAILY_ON, today.isoformat(), now)
            run_safely(db, lambda s: run_daily(s, today, now), WATCH_FAILED["daily"])
            db.commit()
    try:
        with Session(immediate) as db:
            if local.time() >= V.SUMMARY_AT and get_state(db, SUMMARY_ON) != today.isoformat():
                set_state(db, SUMMARY_ON, today.isoformat(), now)
                queue_summary(db, today, now)
                db.commit()
    except Exception as e:  # noqa: BLE001 - the summary must not stop urgent mail
        log.error("The daily summary couldn't be queued for book %s: %s", book.id, log_safe(e))
    with Session(immediate) as db:
        ids = [r.id for r in due_rows(db, now)]
    work = []
    for row_id in ids:           # each email in its own transaction: one that can't be rendered doesn't stop the others
        item = _claim_one(immediate, row_id, sender, today, now)
        if item is not None:
            work.append(item)
    if not work:
        return "idle"
    emails = addresses(books.directory, [u for w in work for u in w[1]])
    results = [(w[0], *deliver(mailer, w[1], w[2], w[3], w[4], w[5], emails)) for w in work]
    for row_id, ok, failed, error in results:
        with Session(immediate) as db:
            after_try(db, db.get(MailOutbox, row_id), ok, failed, error, now)
            db.commit()
    return f"{len(work)} tried"


def watch_tick(books: BookRegistry, mailer, settings, now: datetime) -> dict[str, str]:
    out: dict[str, str] = {}
    for book in books.books():
        if book.kind != "parent":
            continue
        if book.id in books.unavailable:
            out[book.slug] = "unavailable"
            continue
        try:
            out[book.slug] = watch_book(books, book, mailer, settings, now)
        except Exception as e:  # noqa: BLE001 - one book must not stop the others
            log.error("The watch tick failed for book %s: %s", book.id, log_safe(e))
            out[book.slug] = "failed"
    return out
