"""The directory's first build and the one-time move to books (spec 2.6).

Restart-safe: the directory is built in directory.db.partial and renamed into place in one step, so a crash leaves
either no directory (steward.db untouched, and the next start begins again) or a complete one. steward.db itself
changes only in its own Alembic upgrade (0008), which SQLite runs in one transaction."""
from __future__ import annotations

from steward import clock
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import sqlcipher3

from steward.books.owners import HOUSEHOLD_OWNER_NAMES, to_json
from steward.db.engine import WrongKey, check_key, make_engine
from steward.db.keys import directory_key
from steward.db.migrate import run_directory_migrations, run_migrations
from steward.settings import Settings

log = logging.getLogger("steward.books")
MOVED = ("user", "passkey", "password_reset", "session")
OURS_FILE = "steward.db"


def utc_now() -> datetime:
    return clock.now()


def sqlite_time(dt: datetime) -> str:
    """How SQLAlchemy stores a TZDateTime in SQLite: naive UTC with six decimals."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def remove_db_files(path: Path) -> None:
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
        p.unlink(missing_ok=True)


def _sql_path(p: Path) -> str:
    from steward.books.registry import DirectoryUnavailable
    s = str(p)
    if not p.is_absolute() or any(c in s for c in "'\"\0"):
        raise DirectoryUnavailable(f"The data folder path {s} can't contain quote characters.")
    return s


def sign_in_fingerprint(raw, schema: str) -> str:
    """A digest of the sign-in rows in `schema` ("main" or an attached name). Columns in name order, rows by id."""
    h = hashlib.sha256()
    tables = {r[0] for r in raw.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")}
    for t in MOVED:
        if t not in tables:
            h.update(f"{t}:absent;".encode())
            continue
        cols = sorted(r[1] for r in raw.execute(f'PRAGMA {schema}.table_info("{t}")'))
        col_sql = ", ".join(f'"{c}"' for c in cols)
        for row in raw.execute(f'SELECT {col_sql} FROM {schema}."{t}" ORDER BY id'):
            h.update(repr((t, tuple(row))).encode())
    return h.hexdigest()


def _reusable_backup(settings: Settings, dest: Path, master: str) -> Path | None:
    """A restart after a crash reuses the newest pre-move backup when steward.db hasn't been touched since it was
    taken, so the move has exactly one backup (Review Focus 1; ledger ruling). A steward.db restored by nas-ops has
    a newer mtime and gets a fresh backup. Writes land in the -wal file first, so its mtime counts too, and a backup
    that the key doesn't open is not reused."""
    found = sorted(dest.glob("pre-books-steward-*.db"), key=lambda p: p.stat().st_mtime)
    if not found or not settings.db_path.exists():
        return None
    newest = found[-1]
    taken = newest.stat().st_mtime
    wal = settings.db_path.with_name(settings.db_path.name + "-wal")
    for live in (settings.db_path, wal):
        if live.exists() and live.stat().st_mtime > taken:
            return None
    try:     # read-only and immutable: checking the backup must not write to it, not even a journal mode
        conn = sqlcipher3.connect(f"file:{_sql_path(newest.resolve())}?mode=ro&immutable=1", uri=True)
        try:
            conn.execute(f"PRAGMA key = \"x'{master}'\"")
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlcipher3.DatabaseError:
        return None
    return newest


def backup_before_books(settings: Settings, master: str) -> Path:
    """The same encrypted copy `steward backup` makes (VACUUM INTO, same key), taken before anything moves (spec
    2.6). Named outside the 14-copy rotation so it is never pruned (ruling 14)."""
    from steward.books.registry import DirectoryUnavailable
    dest = settings.backups_dir.resolve()
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = dest / f"pre-books-steward-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    if target.exists():  # a restart within the same second already took it
        return target
    eng = make_engine(settings.db_path, master)
    try:
        try:
            check_key(eng)
        except WrongKey as e:
            raise DirectoryUnavailable(f"The key at {settings.key_path} doesn't open {settings.db_path}.") from e
    finally:
        eng.dispose()      # closing the last connection checkpoints and removes the -wal this check created
    reuse = _reusable_backup(settings, dest, master)
    if reuse is not None:
        return reuse
    eng = make_engine(settings.db_path, master)
    try:
        raw = eng.raw_connection()
        try:
            raw.driver_connection.execute(f"VACUUM INTO '{_sql_path(target)}'")
        finally:
            raw.close()
    finally:
        eng.dispose()
    os.chmod(target, 0o600)
    return target


def build_directory(settings: Settings, master: str, now: datetime) -> int:
    """directory.db from steward.db's sign-in tables (if it has them), with ours registered and every person a
    manager of it. Built under another name, then renamed into place. Returns how many people it holds."""
    partial = settings.directory_path.with_name("directory.db.partial")
    remove_db_files(partial)
    stamp = sqlite_time(now)
    eng = make_engine(partial, directory_key(master))
    try:
        run_directory_migrations(eng)
        with eng.connect() as c:
            raw = c.connection.driver_connection
            raw.execute(f"ATTACH DATABASE '{_sql_path(settings.db_path.resolve())}' AS old KEY \"x'{master}'\"")
            try:
                raw.execute("BEGIN IMMEDIATE")
                try:
                    tables = {r[0] for r in raw.execute("SELECT name FROM old.sqlite_master WHERE type='table'")}
                    if "user" in tables:
                        for t in MOVED:
                            cols = ", ".join(f'"{r[1]}"' for r in raw.execute(f'PRAGMA old.table_info("{t}")'))
                            raw.execute(f'INSERT INTO main."{t}" ({cols}) SELECT {cols} FROM old."{t}"')
                    fingerprint = sign_in_fingerprint(raw, "old")
                    raw.execute(
                        "INSERT INTO book (slug, name, kind, owner_names, file, key_scheme, created_at) "
                        "VALUES ('ours', 'Ours', 'household', ?, ?, 'raw', ?)",
                        (to_json(HOUSEHOLD_OWNER_NAMES), OURS_FILE, stamp))
                    book_id = raw.execute("SELECT id FROM book WHERE slug = 'ours'").fetchone()[0]
                    raw.execute("INSERT INTO membership (user_id, book_id, role, created_at, created_by) "
                                "SELECT id, ?, 'manager', ?, NULL FROM main.\"user\"", (book_id, stamp))
                    raw.execute("INSERT INTO membership_change (at, book_id, user_id, action, role_before, role_after, "
                                "by_user_id, note) SELECT ?, ?, id, 'added', NULL, 'manager', NULL, 'Moved to books' "
                                "FROM main.\"user\"", (stamp, book_id))
                    raw.execute("INSERT INTO directory_meta (key, value) VALUES ('sign_in_fingerprint', ?)",
                                (fingerprint,))
                    people = raw.execute("SELECT count(*) FROM main.\"user\"").fetchone()[0]
                    raw.execute("COMMIT")
                except BaseException:
                    raw.execute("ROLLBACK")
                    raise
            finally:
                raw.execute("DETACH DATABASE old")
    finally:
        eng.dispose()
    os.replace(partial, settings.directory_path)
    return people


_DIRECTORY_BACKUP = re.compile(r"^steward-directory-\d{8}-\d{6}\.db$")


def _refuse_if_directory_is_lost(settings: Settings, master: str) -> None:
    """directory.db is missing but steward.db is already past 0008 (no `user` table): the people live only in the
    lost directory, so building an empty one would lock everybody out. Say which backup to restore."""
    from steward.books.registry import DirectoryUnavailable
    eng = make_engine(settings.db_path, master)
    try:
        try:
            check_key(eng)
        except WrongKey as e:
            raise DirectoryUnavailable(f"The key at {settings.key_path} doesn't open {settings.db_path}.") from e
        with eng.connect() as c:
            names = {r[0] for r in c.connection.driver_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        eng.dispose()
    if "alembic_version" not in names or "user" in names:
        return
    # Exact stamp only: a book slugged "directory-stuff" also backs up as steward-directory-*.db.
    found = (sorted(p.name for p in settings.backups_dir.iterdir() if _DIRECTORY_BACKUP.match(p.name))
             if settings.backups_dir.is_dir() else [])
    newest = (f"Restore the newest directory backup, {found[-1]}, from {settings.backups_dir} to "
              f"{settings.directory_path}, then start Steward again." if found else
              f"No copy of directory.db was found in {settings.backups_dir}.")
    raise DirectoryUnavailable(
        f"data/directory.db is missing ({settings.directory_path}), but {settings.db_path} no longer holds the "
        f"sign-in data, so Steward won't build an empty directory. {newest}")


def ensure_directory(settings: Settings, master: str, now: datetime | None = None) -> str:
    """Make sure directory.db exists. "ready": it did. "moved": built from an existing steward.db after a backup.
    "created": a new install, with steward.db made first so both layouts are the same (ruling 1)."""
    remove_db_files(settings.directory_path.with_name("directory.db.partial"))
    if settings.directory_path.exists():
        return "ready"
    if settings.db_path.exists():
        _refuse_if_directory_is_lost(settings, master)
        backup = backup_before_books(settings, master)
        what = "moved"
    else:
        eng = make_engine(settings.db_path, master)
        try:
            run_migrations(eng)
        finally:
            eng.dispose()
        what = "created"
    people = build_directory(settings, master, now or utc_now())
    if what == "moved":
        log.info("Moved sign-in for %d %s to directory.db; backup %s", people, "person" if people == 1 else "people",
                 backup.name)
    return what
