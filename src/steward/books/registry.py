"""Opens books (spec 2.4, 2.7, 8): the directory engine, one engine per book opened on first use and kept, and the
per-book things that used to sit on app.state once (the plan cache and the sync lock)."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from steward import clock
from steward.books.owners import OwnerName, from_json
from steward.books.people import Person, sample_people
from steward.db.directory_models import Book, DirectoryEvent, DirectoryMeta, Membership, User
from steward.books.sample_guard import SAMPLE_OPTION
from steward.db.engine import WrongKey, check_key, make_engine
from steward.db.keys import book_key, directory_key, read_key
from steward.db.migrate import MigrationFailed, book_revision, run_directory_migrations, run_migrations
from steward.services.plan_cache import PlanCache
from steward.settings import Settings

log = logging.getLogger("steward.books")
CANT_OPEN = "This book can't be opened right now."


class BookUnavailable(RuntimeError):
    """A book that can't be opened right now (spec 8). The message is the reason, in plain words, for managers."""


class DirectoryUnavailable(RuntimeError):
    """The directory can't be opened or upgraded. Steward must not start (spec 8); the message names the file."""


@dataclass(frozen=True)
class BookInfo:
    id: int
    slug: str
    name: str
    kind: str
    owner_names: tuple[OwnerName, ...]
    file: str
    key_scheme: str
    sample: bool = False

    @classmethod
    def of(cls, b: Book) -> "BookInfo":
        return cls(b.id, b.slug, b.name, b.kind, from_json(b.owner_names), b.file, b.key_scheme,
                   b.sample_of is not None)


def household_book_id(ddb: Session) -> int | None:
    """THE install's household book (guided setup spec: one household per install): the unarchived one. Only setup
    (bootstrap, prepare) makes it, and no second one can be made, but an older install might hold two. Then the
    lowest id is the household and a warning says so, so a manager of the other one never gets install authority.
    A Sample (sample_of set) is never the household book."""
    ids = ddb.scalars(select(Book.id).where(Book.kind == "household", Book.archived_at.is_(None),
                                            Book.sample_of.is_(None)).order_by(Book.id).limit(2)).all()
    if len(ids) > 1:
        log.warning("More than one household book; book %s counts as the household.", ids[0])
    return ids[0] if ids else None


def household_name(ddb: Session) -> str:
    """The household book's name, for words that name it; plain words when there is none."""
    book_id = household_book_id(ddb)
    book = ddb.get(Book, book_id) if book_id is not None else None
    return book.name if book is not None else "the household book"


class BookRegistry:
    def __init__(self, settings: Settings, directory: Engine | None = None):
        self.settings = settings
        self.master = read_key(settings.key_path, private=settings.key_file is not None)
        self.directory = directory or make_engine(settings.directory_path, directory_key(self.master))
        self.unavailable: dict[int, str] = {}
        self._engines: dict[int, Engine] = {}
        self._plan_caches: dict[int, PlanCache] = {}
        self._sync_locks: dict[int, threading.Lock] = {}
        self._lock = threading.Lock()

    # -- start-up -------------------------------------------------------------------------------------------
    def prepare(self) -> None:
        from steward.books.bootstrap import ensure_directory
        ensure_directory(self.settings, self.master)
        self.upgrade_all()

    def upgrade_all(self) -> None:
        """Alembic for the directory, then for each book. A book that fails is marked unavailable and the others
        carry on (spec 2.7, 8). A directory that fails stops start-up."""
        path = self.settings.directory_path
        try:
            check_key(self.directory)
            run_directory_migrations(self.directory)
        except WrongKey as e:
            raise DirectoryUnavailable(f"The key at {self.settings.key_path} doesn't open {path}.") from e
        except MigrationFailed as e:
            raise DirectoryUnavailable(f"{path} couldn't be upgraded: {e}") from e
        self.unavailable.clear()
        for book in self.books(include_samples=True):
            if book.sample and not self.path_for(book).exists():
                self._archive_sample(book)
                continue
            try:
                eng = self.engine_for(book)
                self.before_upgrade(book, eng)
                was = book_revision(eng)
                run_migrations(eng, household=book.kind == "household")
                if book.kind == "parent":
                    self._backfill_items(book, eng)
                else:
                    self._check_same_accounts(book, eng, was)
            except DirectoryUnavailable:
                raise
            except (BookUnavailable, MigrationFailed) as e:
                reason = str(e) if isinstance(e, BookUnavailable) else "Its upgrade failed."
                self.close(book.id)
                self.unavailable[book.id] = reason
                log.error("Book %s can't be opened: %s", book.id, reason)   # a failed upgrade's SQL can hold values
                self.log_event("error", "book", f"Book {book.slug} can't be opened: {reason}", book.id)

    def _archive_sample(self, book: BookInfo) -> None:
        """A Sample whose file is gone (swept, or lost) is archived, not left to fail as an unavailable book."""
        with Session(self.directory) as s:
            row = s.get(Book, book.id)
            if row is not None and row.archived_at is None:
                row.archived_at = clock.now()
                s.commit()
        log.info("Sample book %s has no file; archived it.", book.id)

    def _backfill_items(self, book: BookInfo, engine: Engine) -> None:
        """Ruling 17: accounts made before the inventory existed get their items. A failure here is logged; the book
        still opens."""
        from steward.inventory.accounts import ensure_account_items
        try:
            with Session(engine) as db:
                if ensure_account_items(db):
                    db.commit()
        except Exception:  # noqa: BLE001 - the inventory must never keep a book from opening
            log.exception("Couldn't add inventory items for book %s", book.id)
            self.log_event("error", "book", f"Book {book.slug}: couldn't add inventory items for its accounts.", book.id)

    def _check_same_accounts(self, book: BookInfo, engine: Engine, was: str | None) -> None:
        """Same-account spec, decision 6: once, after the upgrade that brought feeds, pairs already in a household
        book are asked about on Home. A failure is logged; the book still opens."""
        from steward.deps import now
        from steward.services.same_account import apart
        try:
            apart.check_once(engine, was, now())
        except Exception:  # noqa: BLE001 - the check must never keep a book from opening
            log.exception("Couldn't check book %s for accounts that look the same", book.id)
            self.log_event("error", "book", f"Book {book.slug}: couldn't check for accounts that look the same.",
                           book.id)

    def before_upgrade(self, book: BookInfo, engine: Engine) -> None:
        """Spec 2.6 safety, ruling 13. A book that still has its sign-in tables (ours before 0008) drops them only if
        they are exactly what the directory copied. If not, steward.db came back from a backup and directory.db was
        left behind: starting would lose every sign-in since, so Steward refuses."""
        from steward.books.bootstrap import sign_in_fingerprint
        with engine.connect() as c:
            raw = c.connection.driver_connection
            if raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user'").fetchone() is None:
                return
            fingerprint = sign_in_fingerprint(raw, "main")
        with Session(self.directory) as s:
            kept = s.get(DirectoryMeta, "sign_in_fingerprint")
        if kept is None or kept.value != fingerprint:
            raise DirectoryUnavailable(
                f"{self.settings.directory_path} doesn't match the sign-in data in {self.path_for(book)}. If "
                "steward.db was restored from a backup, move directory.db aside and start Steward again "
                "(docs/guides/backups.md).")

    # -- books ----------------------------------------------------------------------------------------------
    def books(self, include_samples: bool = False) -> list[BookInfo]:
        """Every unarchived book; a Sample is left out unless asked, so no job ever walks one."""
        with Session(self.directory) as s:
            q = select(Book).where(Book.archived_at.is_(None))
            if not include_samples:
                q = q.where(Book.sample_of.is_(None))
            return [BookInfo.of(b) for b in s.scalars(q.order_by(Book.id))]

    def book(self, slug: str) -> BookInfo | None:
        with Session(self.directory) as s:
            b = s.scalar(select(Book).where(Book.slug == slug, Book.archived_at.is_(None)))
            return BookInfo.of(b) if b is not None else None

    def people(self, book_id: int) -> tuple[Person, ...]:
        with Session(self.directory) as s:
            rows = s.execute(select(User.id, User.username, User.display_name, Membership.role)
                             .join(Membership, Membership.user_id == User.id)
                             .where(Membership.book_id == book_id).order_by(User.id)).all()
            sample = s.scalar(select(Book.sample_of).where(Book.id == book_id)) is not None
        real = tuple(Person(*r) for r in rows)
        return sample_people(real) if sample else real

    def key_for(self, book: BookInfo) -> str:
        return self.master if book.key_scheme == "raw" else book_key(self.master, book.id)

    def files_dir(self, book: BookInfo) -> Path:
        """data/books/<slug>/files (spec 3.5); "ours" too, though only parent books upload for now."""
        return self.settings.books_dir / book.slug / "files"

    def file_store(self, book: BookInfo):
        from steward.inventory.files import FileStore, file_key
        return FileStore(self.files_dir(book), file_key(self.master, book.id), book.id)

    def path_for(self, book: BookInfo) -> Path:
        root = self.settings.data_dir.resolve()
        p = (root / book.file).resolve()
        if not p.is_relative_to(root):
            raise BookUnavailable("The book's file is outside the data folder.")
        return p

    def engine_for(self, book: BookInfo) -> Engine:
        if book.id in self.unavailable:
            raise BookUnavailable(self.unavailable[book.id])
        eng = self._engines.get(book.id)
        if eng is not None:
            return eng
        with self._lock:
            eng = self._engines.get(book.id)
            if eng is None:
                eng = self._open(book)
                self._engines[book.id] = eng
        return eng

    def _open(self, book: BookInfo) -> Engine:
        path = self.path_for(book)
        if not path.exists():  # never let SQLite make an empty file in its place
            raise BookUnavailable("The book's file is missing.")
        eng = make_engine(path, self.key_for(book))
        try:
            check_key(eng)
        except WrongKey:
            eng.dispose()
            raise BookUnavailable("The key doesn't open this book's file.") from None
        if book.sample:      # an option engine shares this pool, so close()'s dispose() still frees it
            eng = eng.execution_options(**{SAMPLE_OPTION: True})
        return eng

    def plan_cache(self, book_id: int) -> PlanCache:
        with self._lock:
            found = self._plan_caches.get(book_id)
            if found is None:
                found = self._plan_caches[book_id] = PlanCache(book_id=book_id)
            return found

    def clear_plan_caches(self) -> None:
        with self._lock:
            caches = list(self._plan_caches.values())
        for cache in caches:
            cache.clear()

    def sync_lock(self, book_id: int) -> threading.Lock:
        with self._lock:
            return self._sync_locks.setdefault(book_id, threading.Lock())

    def log_event(self, level: str, kind: str, message: str, book_id: int | None = None) -> None:
        try:
            with Session(self.directory) as s:
                s.add(DirectoryEvent(level=level, kind=kind, message=message, book_id=book_id))
                s.commit()
        except Exception:  # noqa: BLE001 - logging must never be the thing that fails
            log.exception("Couldn't write a %s %s event for book %s", level, kind, book_id)   # its text can name the book

    def close(self, book_id: int) -> None:
        with self._lock:
            eng = self._engines.pop(book_id, None)
        if eng is not None:
            eng.dispose()

    def dispose(self) -> None:
        with self._lock:
            engines, self._engines = list(self._engines.values()), {}
        for eng in engines:
            eng.dispose()
        self.directory.dispose()


def open_books(settings: Settings) -> BookRegistry:
    books = BookRegistry(settings)
    books.prepare()
    return books
