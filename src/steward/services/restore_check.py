"""Proves last night's backup restores (backups spec, Part 1). The newest run's copies are copied into a private
scratch folder and opened there, never in backups/ (an open SQLCipher file can leave -wal/-shm beside it, and Hyper
Backup would ship them). Each copy must open with its key, pass integrity_check, sit at the migrations' head and, when
its live book has transactions, have some too; every mirrored file must decrypt (AES-GCM, the book and file ids in
the AAD). Nothing private is printed: slugs, counts, revisions and file ids only."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlcipher3
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from steward.books.registry import BookUnavailable
from steward.db.directory_models import Book
from steward.db.engine import WrongKey, check_key, make_engine
from steward.db.keys import book_key, directory_key
from steward.db.migrate import book_head, directory_head
from steward.db.models import StoredFile, Transaction
from steward.inventory.files import FileStore, FileUnreadable, file_key

MAX_AGE_HOURS = 30
_RUN = re.compile(r"^steward-directory-(\d{8}-\d{6})\.db$")
_READ_ERRORS = (WrongKey, DBAPIError, sqlcipher3.DatabaseError)


@dataclass
class CheckResult:
    stamp: str | None
    lines: list[str]
    failures: int
    books: int
    files: int

    @property
    def ok(self) -> bool:
        return self.stamp is not None and self.failures == 0


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _open(src: Path, scratch: Path, key: str) -> Engine:
    """A private copy of one backup file, opened with its key; raises a _READ_ERRORS on a wrong key or damage."""
    dst = scratch / src.name
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o600)
    eng = make_engine(dst, key)
    try:
        check_key(eng)
    except BaseException:
        eng.dispose()
        raise
    return eng


def _verify(eng: Engine, head: str) -> str | None:
    """None when the copy is whole and at `head`; otherwise what's wrong, in words."""
    with eng.connect() as c:
        verdict = c.exec_driver_sql("PRAGMA integrity_check").scalar()
        if verdict != "ok":
            return f"integrity check says: {verdict}"
        rev = c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    return None if rev == head else f"schema {rev}, expected {head}"


def _live_transactions(books, book_id: int) -> int | None:
    """The live book's transaction count, read-only, or None when it can't be opened right now."""
    info = next((b for b in books.books() if b.id == book_id), None)
    if info is None or info.id in books.unavailable:
        return None
    try:
        eng = books.engine_for(info)
    except BookUnavailable:
        return None
    with Session(eng) as s:
        return s.scalar(select(func.count()).select_from(Transaction))


def _newest_run(backups_dir: Path) -> str | None:
    if not backups_dir.is_dir():
        return None
    stamps = sorted(m.group(1) for p in backups_dir.iterdir() if (m := _RUN.match(p.name)))
    return stamps[-1] if stamps else None


def restore_check(books, backups_dir: Path, *, now: datetime | None = None, max_age_hours: int = MAX_AGE_HOURS,
                  master: str | None = None) -> CheckResult:
    master = master if master is not None else books.master
    now = now or datetime.now()
    lines: list[str] = []
    stamp = _newest_run(backups_dir)
    if stamp is None:
        return CheckResult(None, [f"No backup in {backups_dir}."], 1, 0, 0)
    try:
        made = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError:
        return CheckResult(stamp, [f"The newest backup's name has a bad date ({stamp})."], 1, 0, 0)
    age = (now - made).total_seconds() / 3600
    if age < -1:
        return CheckResult(stamp, [f"The newest backup is dated in the future ({stamp}); check this machine's clock."],
                           1, 0, 0)
    if age > max_age_hours:
        lines.append(f"The newest backup is {int(age)} hours old (from {stamp}); expected one in the last "
                     f"{max_age_hours} hours.")
        return CheckResult(stamp, lines, 1, 0, 0)

    failures = n_books = n_files = 0
    engines: list[Engine] = []
    scratch = Path(tempfile.mkdtemp(prefix="steward-restore-check-"))
    try:
        try:
            dir_eng = _open(backups_dir / f"steward-directory-{stamp}.db", scratch, directory_key(master))
            engines.append(dir_eng)
        except _READ_ERRORS:
            lines.append("directory: the key doesn't open it.")
            return CheckResult(stamp, lines, 1, 0, 0)
        except OSError:
            lines.append("directory: the copy can't be read (the file is missing or unreadable).")
            return CheckResult(stamp, lines, 1, 0, 0)
        try:
            problem = _verify(dir_eng, directory_head())
            if not problem:
                with Session(dir_eng) as s:
                    listed = [(b.id, b.slug, b.key_scheme)
                              for b in s.scalars(select(Book).where(Book.archived_at.is_(None),
                                                                    Book.sample_of.is_(None)).order_by(Book.id))]
        except _READ_ERRORS:
            lines.append("directory: the copy can't be read (a table is missing or damaged).")
            return CheckResult(stamp, lines, 1, 0, 0)
        if problem:
            lines.append(f"directory: {problem}.")
            return CheckResult(stamp, lines, 1, 0, 0)
        if not listed:
            lines.append("directory: lists no books.")
            return CheckResult(stamp, lines, 1, 0, 0)

        for book_id, slug, scheme in listed:
            n_books += 1
            src = backups_dir / f"steward-{slug}-{stamp}.db"
            if not src.is_file():
                lines.append(f"{slug}: no copy in backup {stamp}.")
                failures += 1
                continue
            try:
                eng = _open(src, scratch, master if scheme == "raw" else book_key(master, book_id))
                engines.append(eng)
                problem = _verify(eng, book_head())
            except _READ_ERRORS:
                lines.append(f"{slug}: the copy can't be read (a wrong key or damaged bytes).")
                failures += 1
                continue
            except OSError:
                lines.append(f"{slug}: the copy can't be read (the file is missing or unreadable).")
                failures += 1
                continue
            if problem:
                lines.append(f"{slug}: {problem}.")
                failures += 1
                continue
            try:
                with Session(eng) as s:
                    txns = s.scalar(select(func.count()).select_from(Transaction))
                    file_ids = list(s.scalars(select(StoredFile.id).order_by(StoredFile.id)))
            except _READ_ERRORS:
                lines.append(f"{slug}: the copy can't be read (a table is missing or damaged).")
                failures += 1
                continue
            live = _live_transactions(books, book_id)
            if live and not txns:
                lines.append(f"{slug}: the copy has no transactions, but the book has {live:,}.")
                failures += 1
                continue
            store = FileStore(backups_dir / f"steward-{slug}-files", file_key(master, book_id), book_id)
            bad_files = 0
            for fid in file_ids:
                if not store.path(fid).is_file():
                    lines.append(f"{slug}: file {fid} is missing from the backup.")
                    bad_files += 1
                    continue
                try:
                    store.read(fid)
                except FileUnreadable as e:
                    lines.append(f"{slug}: file {fid} doesn't decrypt ({e}).")
                    bad_files += 1
            if bad_files:
                failures += 1
                continue
            n_files += len(file_ids)
            note = "" if live is not None else "; the live book couldn't be opened, so it wasn't compared"
            lines.append(f"{slug}: ok (schema {book_head()}, {_plural(txns, 'transaction')}, "
                         f"{_plural(len(file_ids), 'file')}{note})")
    finally:
        for eng in engines:
            eng.dispose()
        shutil.rmtree(scratch, ignore_errors=True)

    if failures:
        lines.append(f"Backup {stamp} does not restore: {_plural(failures, 'problem')}.")
    else:
        lines.append(f"Backup {stamp} restores: {_plural(n_books, 'book')}, {_plural(n_files, 'file')}.")
    return CheckResult(stamp, lines, failures, n_books, n_files)
