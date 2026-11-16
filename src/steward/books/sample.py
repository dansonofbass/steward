"""The Sample book (guided setup spec 8): the demo household, dated to end today, in a book of its own that belongs to
one person. It never syncs, never reaches Claude, and is never THE household book (plan D1). Remove archives it with a
15-minute Undo; the watcher's tick deletes the file after that."""
from __future__ import annotations

import logging
import shutil
import threading
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import demo
from steward.books.registry import BookInfo, BookRegistry
from steward.books.service import create_book
from steward.db.directory_models import Book
from steward.db.engine import WRITE
from steward.db.models import UNDO_MINUTES

log = logging.getLogger(__name__)

YEARS = 2
NAME = "Sample"
NO_SAMPLE = "You don't have a sample book."
SAMPLE_GONE = "That sample is gone. You can make a new one from the welcome."
HAS_SAMPLE = "You already have a sample book."
SAMPLE_FAILED = "The sample couldn't be made. Try again."

_MAKING = threading.Lock()   # held by make_sample from the lookup to the end of the seed


class SampleMissing(LookupError):
    """There is nothing to remove or bring back; the message is the words."""


class SampleTaken(ValueError):
    """The person already has a Sample; the message is the words."""


def _live(ddb: Session, user_id: int) -> Book | None:
    return ddb.scalar(select(Book).where(Book.sample_of == user_id, Book.archived_at.is_(None)))


def make_sample(books: BookRegistry, ddb: Session, user_id: int, today: date, now: datetime) -> tuple[BookInfo, bool]:
    """The person's Sample, and whether it was made now. create_book commits the directory session before the seeding
    starts, which releases the write lock, so the directory cannot keep two presses apart: a second one would find the
    half-seeded Sample and hand it back empty. _MAKING is held from the lookup through the seed and the failure
    cleanup, so a second press waits, then finds the finished Sample (or makes a new one after a failure). A POST's
    session is BEGIN IMMEDIATE and has already read, so it holds the directory write lock: it lets go before waiting,
    or the first press's failure cleanup could not write."""
    ddb.rollback()                                        # release the directory write lock before waiting
    with _MAKING:
        ddb.rollback()                                    # end any read snapshot taken while waiting
        found = _live(ddb, user_id)
        if found is not None:
            return BookInfo.of(found), False
        info = create_book(books, ddb, name=NAME, kind="household", by=user_id, sample_of=user_id, now=now)
        try:
            with Session(books.engine_for(info).execution_options(**WRITE)) as db:
                demo.seed(db, years=YEARS, end=today)
        except Exception as e:  # noqa: BLE001 - whatever stopped the seeding, the half-made book goes away
            log.exception("The Sample book couldn't be seeded")
            books.close(info.id)
            ddb.get(Book, info.id).archived_at = now
            ddb.commit()
            shutil.rmtree(books.path_for(info).parent, ignore_errors=True)
            raise RuntimeError(SAMPLE_FAILED) from e
        return info, True


def remove_sample(books: BookRegistry, ddb: Session, user_id: int, now: datetime) -> BookInfo:
    row = _live(ddb, user_id)
    if row is None:
        raise SampleMissing(NO_SAMPLE)
    row.archived_at = now
    info = BookInfo.of(row)
    ddb.commit()
    books.close(info.id)
    return info


def restore_sample(books: BookRegistry, ddb: Session, user_id: int, now: datetime) -> BookInfo:
    if _live(ddb, user_id) is not None:
        raise SampleTaken(HAS_SAMPLE)
    row = ddb.scalar(select(Book).where(Book.sample_of == user_id,
                                        Book.archived_at > now - timedelta(minutes=UNDO_MINUTES))
                     .order_by(Book.archived_at.desc(), Book.id.desc()).limit(1))
    if row is None or not books.path_for(BookInfo.of(row)).exists():
        raise SampleMissing(SAMPLE_GONE)
    row.archived_at = None
    info = BookInfo.of(row)
    ddb.commit()
    return info


def sweep_removed(books: BookRegistry, now: datetime) -> int:
    """Delete the folder of every Sample removed more than UNDO_MINUTES ago. The directory row stays (membership_change
    keeps its keys). Only a folder named for the book, directly under the books folder, is ever removed."""
    cutoff = now - timedelta(minutes=UNDO_MINUTES)
    with Session(books.directory) as s:
        rows = [BookInfo.of(b) for b in s.scalars(select(Book).where(
            Book.sample_of.is_not(None), Book.archived_at.is_not(None), Book.archived_at <= cutoff))]
    root = books.settings.books_dir.resolve()
    swept = 0
    for info in rows:
        folder = books.path_for(info).parent
        if not folder.exists() or folder.parent != root or folder.name != info.slug:
            continue
        books.close(info.id)
        shutil.rmtree(folder)
        swept += 1
    return swept
