"""Restoring an encrypted export as a new book (import/export spec P31; CLI restore). The ZIP's members and its KDF
parameters are checked before anything is derived, so a crafted file can't exhaust memory or write outside its
folder. The copy is opened in a 0700 scratch folder and checked (key, revision, kind, owner names). It never
overwrites or touches an existing book. Nothing private is printed: the caller prints the slug and counts.

Anyone who knows the passphrase can make a backup, so nothing in its schema is trusted or run. The new book (a new
id, its key from this NAS's steward.key) is built by Steward's own migrations to the backup's revision; then, for each
of that book's tables, only its columns' values are copied from a stored table of the same name in the backup, with
names quoted from Steward's schema. Every column read from the backup must be a plain stored column: a generated
one would run the backup's expression. The backup's triggers, views, indexes, extra tables and extra columns are
never read; a view, virtual table or generated column in a Steward table's place, a missing column, a row Steward's
constraints refuse, or a dangling foreign key makes it DAMAGED. Operational rows (book_export.RESTORE_BLANKS) are
never read and stay empty, and every directory user id saying who did what (ATTRIBUTION) becomes RESTORED_BY, since
on this NAS the same id can be someone else. Then the book migrates to head, its integrity is checked, and its files must be exactly
the ZIP's file members."""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import string
import tempfile
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlcipher3
from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from steward.books.bootstrap import remove_db_files
from steward.books.owners import HOUSEHOLD_OWNER_NAMES, parse_owner_names, to_json
from steward.books.people import RESTORED_BY
from steward.books.registry import BookInfo
from steward.books.service import NAME_RULE, add_membership, slug_for
from steward.db.directory_models import BOOK_KINDS, Book
from steward.db.engine import make_engine
from steward.db.migrate import MigrationFailed, book_head, book_revisions, migrate_to, run_migrations
from steward.db.models import Transaction
from steward.inventory.files import MAX_BYTES
from steward.services import book_export as X

MAX_TOTAL = 4 * 1024 ** 3
MAX_DB = 2 * 1024 ** 3          # book.db is copied to the scratch folder whole; a real book is far smaller
MAX_MEMBERS = 100_000          # each files/ member is one stored file
MAX_META = 64 * 1024            # export.json is a few hundred bytes; it's read whole, so it's bounded first
MAX_FILE_MEMBER = MAX_BYTES + len(X.FILE_MAGIC) + X.NONCE_BYTES + 16    # the upload limit, sealed (GCM's tag)
MAX_SEQ_GAP = 10 ** 6           # an AUTOINCREMENT mark this far past the table's highest id isn't a real book's
FIRST_REVISION = "0035"         # the first revision an export can have: the export arrived with 0035
# No higher than the export writes (settings.EXPORT_KDF is t=3, 256 MiB, p=1; tests use 8 MiB), so a crafted file
# can't make the NAS spend more memory or time deriving than a real backup does.
BOUNDS = {"t": (1, 4), "m_kib": (8 * 1024, 256 * 1024), "p": (1, 4)}
_MEMBER = re.compile(r"(?:export\.json|book\.db|files/[1-9][0-9]{0,17})")
_REVISION = re.compile(r"[0-9]{4}")
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error,
               OSError)
_ASCII_FOLD = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_LOG_LEVELS = {"NONE", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"}
# Who did what: directory user ids a book keeps without a foreign key (spec 2.2). On this NAS the same id can be
# someone else, so every one that is set becomes RESTORED_BY ("Someone, before this book was restored"). NULL stays
# NULL: it already says "the bank feed", "the checks" or "the demo seed". Stored names (a note's author_name, a rule
# note's note_by_name) are right as they are. Tables keyed by a user id are in RESTORE_BLANKS instead.
ATTRIBUTION: dict[str, tuple[str, ...]] = {
    "advisor_outgoing": ("user_id", "approved_by"), "advisor_state": ("updated_by",),
    "business_rule": ("created_by",), "business_state": ("updated_by",),
    "care_quote": ("updated_by",), "care_scenario": ("created_by", "updated_by"), "care_setup": ("updated_by",),
    "change_record": ("user_id",), "expense_ratio_override": ("updated_by",), "file": ("uploaded_by",),
    "flag": ("status_by", "resolved_by"), "import_batch": ("imported_by",), "import_set": ("imported_by",),
    "inventory_item": ("created_by", "updated_by"), "merchant_rule": ("note_by",), "plan": ("saved_by",),
    "positions_import": ("imported_by",), "reimburse_settlement": ("created_by",),
    "same_account_answer": ("answered_by",), "set_aside": ("updated_by",), "set_aside_dismissed": ("created_by",),
    "set_aside_match": ("created_by",), "setup_step": ("user_id",), "spending_prefs": ("updated_by",),
    "spending_target": ("updated_by",), "statement_layout": ("confirmed_by",), "suggestion": ("answered_by",),
    "tax_form": ("created_by",), "tax_state": ("updated_by",), "transaction_note": ("author_id",),
    "trip": ("created_by",), "watch_known": ("added_by", "removed_by"),
}
# JSON lists of user ids: whoever was emailed becomes one RESTORED_BY.
ATTRIBUTION_JSON = frozenset({("flag_event", "user_ids")})
NOT_EXPORT = "That isn't a Steward backup."
WRONG = "That passphrase doesn't open this backup."
NEWER = "This backup is from a newer Steward. Update first."
DAMAGED = "This backup is damaged."
BAD_FILE = "A file in this backup doesn't open with that passphrase."


class RestoreRefused(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Header:
    kdf: tuple[int, int, int]
    salt: bytes
    files: list[int]


def _int_in(value: object, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise RestoreRefused(NOT_EXPORT)
    return value


def check(z: zipfile.ZipFile) -> Header:
    infos = z.infolist()
    names = [i.filename for i in infos]
    if len(names) > MAX_MEMBERS or len(set(names)) != len(names) or any(not _MEMBER.fullmatch(n) for n in names):
        raise RestoreRefused(NOT_EXPORT)                  # an absolute name, "..", or anything else
    if "export.json" not in names or "book.db" not in names or sum(i.file_size for i in infos) > MAX_TOTAL or \
            z.getinfo("export.json").file_size > MAX_META or z.getinfo("book.db").file_size > MAX_DB or \
            any(i.file_size > MAX_FILE_MEMBER for i in infos if i.filename.startswith("files/")):
        raise RestoreRefused(NOT_EXPORT)
    try:
        meta = json.loads(z.read("export.json"))
    except (ValueError, RecursionError, *_ZIP_ERRORS):
        raise RestoreRefused(NOT_EXPORT) from None
    k = meta.get("kdf") if isinstance(meta, dict) else None
    if not isinstance(k, dict) or meta.get("format") != X.FORMAT or meta.get("version") != X.VERSION or \
            k.get("name") != "argon2id":
        raise RestoreRefused(NOT_EXPORT)
    t, m, p = (_int_in(k.get(f), *BOUNDS[f]) for f in ("t", "m_kib", "p"))
    try:
        salt = base64.b64decode(k.get("salt") or "", validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise RestoreRefused(NOT_EXPORT) from None
    if len(salt) != X.SALT_BYTES:
        raise RestoreRefused(NOT_EXPORT)
    return Header((t, m, p), salt, sorted(int(n[6:]) for n in names if n.startswith("files/")))


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _fold(name: str) -> str:
    """SQLite matches names ignoring ASCII case only (a Kelvin sign is not a K)."""
    return name.translate(_ASCII_FOLD)


def _harden(c) -> None:
    """No function in a schema runs unless it's harmless, and a malformed cell is caught as it's read."""
    c.execute("PRAGMA trusted_schema = OFF")
    c.execute("PRAGMA cell_size_check = ON")


def _is_table(c, schema: str, name: str) -> bool:
    """One object of that name and it's a stored table: never a view, a virtual table (its module would read the
    backup's shadow tables) or anything else."""
    rows = c.execute(f"SELECT type, rootpage, sql FROM {schema}.sqlite_master WHERE name = ? COLLATE NOCASE",
                     (name,)).fetchall()
    return len(rows) == 1 and rows[0][0] == "table" and isinstance(rows[0][1], int) and rows[0][1] > 0 and \
        isinstance(rows[0][2], str) and rows[0][2].startswith("CREATE TABLE ")


def _plain(c, schema: str, table: str, cols: list[str]) -> str:
    """Before any read from the backup: the table is a stored table and every column read is a plain stored column
    of it (hidden 0 in table_xinfo; a generated one would run the backup's expression). Returns the SELECT, its
    columns qualified by an alias so a missing one is an error, never a string literal."""
    if not _is_table(c, schema, table):
        raise RestoreRefused(DAMAGED)
    theirs = {_fold(r[1]): r[6] for r in c.execute(f"PRAGMA {schema}.table_xinfo({_q(table)})").fetchall()}
    if any(theirs.get(_fold(col)) != 0 for col in cols):
        raise RestoreRefused(DAMAGED)
    return f"SELECT {', '.join('s.' + _q(col) for col in cols)} FROM {schema}.{_q(table)} AS s"


@contextmanager
def _quiet_cipher_log(c) -> Iterator[None]:
    """A wrong passphrase makes SQLCipher log "hmac check failed" to stderr; the CLI says it in words instead."""
    level = c.execute("PRAGMA cipher_log_level").fetchone()
    level = level[0] if level and level[0] in _LOG_LEVELS else None
    if level:
        c.execute("PRAGMA cipher_log_level = NONE")
    try:
        yield
    finally:
        if level:
            c.execute(f"PRAGMA cipher_log_level = {level}")


def _read_copy(src: Path, k_db: bytes) -> tuple[str, dict[str, str]]:
    """The key (a page that fails its check under the right key is DAMAGED, not a wrong passphrase), then the revision
    and the meta, each read only as plain columns of stored tables."""
    c = sqlcipher3.connect(str(src), check_same_thread=False)
    try:
        c.execute(f"PRAGMA key = \"x'{k_db.hex()}'\"")
        _harden(c)
        with _quiet_cipher_log(c):
            try:
                c.execute("SELECT count(*) FROM sqlite_master").fetchall()
            except sqlcipher3.DatabaseError as e:
                raise RestoreRefused(WRONG if "not a database" in str(e) else DAMAGED) from None
        try:
            revs = [r for (r,) in c.execute(_plain(c, "main", "alembic_version", ["version_num"])).fetchall()]
            meta = dict(c.execute(_plain(c, "main", "export_meta", ["key", "value"]) +
                                  " WHERE s.\"key\" IN ('kind', 'name', 'owner_names')").fetchall())
        except sqlcipher3.Error:
            raise RestoreRefused(DAMAGED) from None
    finally:
        c.close()
    if len(revs) != 1 or not isinstance(revs[0], str) or not _REVISION.fullmatch(revs[0]):
        raise RestoreRefused(DAMAGED)
    if not all(isinstance(meta.get(k), str) for k in ("kind", "name", "owner_names")) or meta["kind"] not in BOOK_KINDS:
        raise RestoreRefused(DAMAGED)
    return revs[0], meta


def _check_revision(rev: str) -> None:
    """From FIRST_REVISION to head; a newer one asks for an update."""
    if int(rev) > int(book_head()):
        raise RestoreRefused(NEWER)
    if rev not in book_revisions() or int(rev) < int(FIRST_REVISION):
        raise RestoreRefused(DAMAGED)


def _book_name(name: str | None, meta: dict[str, str]) -> str:
    """create_book's rule: 1 to 60 characters once trimmed. A name typed at the CLI that breaks it gets the rule's
    words; a backup's own name that breaks it is DAMAGED."""
    if name is not None:
        clean = name.strip()
        if not clean or len(clean) > 60:
            raise RestoreRefused(NAME_RULE)
        return clean
    base = meta["name"].strip()
    if not base or len(base) > 60:
        raise RestoreRefused(DAMAGED)
    return f"{base} (restored)"[:60].strip()


def _owner_names(kind: str, meta: dict[str, str]) -> str:
    """As create_book: a household's are always HOUSEHOLD_OWNER_NAMES; a parent book's labels pass
    parse_owner_names and their keys are the ones those labels give (keys never change after a book is made)."""
    if kind == "household":
        return to_json(HOUSEHOLD_OWNER_NAMES)
    try:
        stored = json.loads(meta["owner_names"])
        parsed = parse_owner_names([d["label"] for d in stored])
        keys = [d["key"] for d in stored]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise RestoreRefused(DAMAGED) from None
    if [o.key for o in parsed] != keys:
        raise RestoreRefused(DAMAGED)
    return to_json(parsed)


def _copy_rows(new, src: Path, k_db: bytes) -> None:
    """Every table of the new book (Steward's, at the backup's revision) but alembic_version gets the rows of the
    backup's stored table of that name, Steward's columns only, in one transaction; RESTORE_BLANKS are never read and
    stay empty. Every name in the SQL is Steward's own, quoted. Foreign keys are off while the rows go in table by
    table, as sqlcipher_export had them, and checked before the commit."""
    raw = new.raw_connection()
    try:
        c = raw.driver_connection
        _harden(c)
        c.execute("PRAGMA foreign_keys = OFF")
        c.execute(f"ATTACH DATABASE '{X.sql_path(src)}' AS src KEY \"x'{k_db.hex()}'\"")
        try:
            if c.execute("PRAGMA src.quick_check").fetchall() != [("ok",)]:
                raise RestoreRefused(DAMAGED)
            tables = [n for (n,) in c.execute(
                "SELECT name FROM main.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'alembic_version' ORDER BY name").fetchall()]
            c.execute("BEGIN IMMEDIATE")
            try:
                for t in tables:
                    c.execute(f"DELETE FROM main.{_q(t)}")                     # any row a migration seeded
                    if t in X.RESTORE_BLANKS:
                        continue
                    cols = [r[1] for r in c.execute(f"PRAGMA main.table_xinfo({_q(t)})").fetchall() if r[6] == 0]
                    c.execute(f"INSERT INTO main.{_q(t)} ({', '.join(_q(col) for col in cols)}) "
                              + _plain(c, "src", t, cols))
                _clear_attribution(c)
                _copy_sequence(c)
                if c.execute("PRAGMA main.foreign_key_check").fetchall():
                    raise RestoreRefused(DAMAGED)
                c.execute("COMMIT")
            except BaseException:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise
        finally:
            c.execute("DETACH DATABASE src")
            c.execute("PRAGMA foreign_keys = ON")
    except sqlcipher3.Error:
        raise RestoreRefused(DAMAGED) from None
    finally:
        raw.close()


def _clear_attribution(c) -> None:
    """ATTRIBUTION's ids become RESTORED_BY, in the copy, at the backup's revision (a column it doesn't have yet is
    skipped). "Changed their own emails" stays so; another person's emails lose their target. An email switch
    (tax_state's email:<user id>) belongs to the old NAS's person, so it goes, as watch_recipient's rows do."""
    def has(table: str) -> set[str]:
        return {r[1] for r in c.execute(f"PRAGMA main.table_xinfo({_q(table)})").fetchall()}

    if {"action", "user_id", "target_id"} <= has("change_record"):
        c.execute("UPDATE main.change_record SET target_id = CASE WHEN target_id = user_id THEN ? ELSE NULL END "
                  "WHERE action = 'watch.emails' AND target_id IS NOT NULL", (RESTORED_BY,))
    for t, cols in ATTRIBUTION.items():
        present = has(t)
        for col in (col for col in cols if col in present):
            c.execute(f"UPDATE main.{_q(t)} SET {_q(col)} = ? WHERE {_q(col)} IS NOT NULL", (RESTORED_BY,))
    for t, col in sorted(ATTRIBUTION_JSON):
        if col in has(t):
            c.execute(f"UPDATE main.{_q(t)} SET {_q(col)} = ? WHERE {_q(col)} IS NOT NULL AND {_q(col)} != '[]'",
                      (json.dumps([RESTORED_BY]),))
    if "key" in has("tax_state"):
        c.execute("DELETE FROM main.tax_state WHERE key LIKE 'email:%'")
    if {"kind", "target"} <= has("advisor_alias"):
        # Claude's alias for an old NAS person is keyed by their directory id: it keeps its number (aliases never
        # change, so "Person 2" in old history still means them) but never matches anyone here. A person here gets
        # their own alias at first use; a household owner gets the owner's again.
        c.execute("UPDATE main.advisor_alias SET target = 'restored:' || target WHERE kind = 'user'")


def _copy_sequence(c) -> None:
    """AUTOINCREMENT high-water marks, so a file id is never reused (its AAD names it): only for Steward's own
    AUTOINCREMENT tables, only whole numbers, never below the rows now in the table. A mark far past the table's
    highest id (or past 2^53) is a crafted file's: it would make every later insert fail, so it's DAMAGED."""
    if not _is_table(c, "src", "sqlite_sequence"):
        return
    ours = {n for (n,) in c.execute("SELECT name FROM main.sqlite_master WHERE type = 'table' "
                                    "AND sql LIKE '%AUTOINCREMENT%'").fetchall()}
    for n, seq in c.execute(_plain(c, "src", "sqlite_sequence", ["name", "seq"])).fetchall():
        if n not in ours:
            continue
        top = c.execute(f"SELECT coalesce(max(rowid), 0) FROM main.{_q(n)}").fetchone()[0]
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0 or seq > 2 ** 53 or seq > top + MAX_SEQ_GAP:
            raise RestoreRefused(DAMAGED)
        c.execute("DELETE FROM main.sqlite_sequence WHERE name = ?", (n,))
        c.execute("INSERT INTO main.sqlite_sequence (name, seq) VALUES (?, ?)", (n, max(seq, top)))


def restore(books, path: Path, passphrase: str, name: str | None, managers: list[int],
            now: datetime) -> tuple[BookInfo, dict[str, int]]:
    if name is not None:
        _book_name(name, {})                                   # a bad --name is said before any work
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise RestoreRefused(NOT_EXPORT) from None
    with z:
        h = check(z)
        k_db, k_file = X.keys(passphrase, h.salt, *h.kdf)
        scratch = Path(tempfile.mkdtemp(prefix="steward-restore-"))      # 0700, outside backups/
        try:
            src = scratch / "book.db"
            fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as out, z.open("book.db") as zin:
                    shutil.copyfileobj(zin, out)
            except _ZIP_ERRORS:
                raise RestoreRefused(DAMAGED) from None
            rev, meta = _read_copy(src, k_db)
            _check_revision(rev)
            clean = _book_name(name, meta)
            owners = _owner_names(meta["kind"], meta)
            return _new_book(books, src, k_db, rev, z, h, k_file, meta["kind"], clean, owners, managers, now)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def _new_book(books, src: Path, k_db: bytes, rev: str, z, h: Header, k_file: bytes, kind: str, clean: str,
              owners: str, managers: list[int], now: datetime) -> tuple[BookInfo, dict[str, int]]:
    """As `book create` makes a book: a directory row, its own file with a derived key, at head, its managers. Its
    schema is Steward's migrations' to the backup's revision; only the rows come from the backup."""
    with Session(books.directory) as ddb:
        slug = slug_for(ddb, clean)
        row = Book(slug=slug, name=clean, kind=kind, owner_names=owners, file=f"books/{slug}/book.db",
                   key_scheme="derived", created_at=now)
        ddb.add(row)
        ddb.flush()
        info = BookInfo.of(row)
        target = books.path_for(info)
        try:
            remove_db_files(target)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            household = info.kind == "household"
            new = make_engine(target, books.key_for(info))
            try:
                migrate_to(new, rev, household=household)           # Steward's schema, from Steward's migrations
                _copy_rows(new, src, k_db)
                run_migrations(new, household=household)
                with new.connect() as c:
                    if c.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
                        raise RestoreRefused(DAMAGED)
                    ids = sorted(i for (i,) in c.exec_driver_sql("SELECT id FROM file").all())
                if ids != h.files or (household and h.files):           # the files are exactly the book's own
                    raise RestoreRefused(DAMAGED)
                with Session(new) as s:
                    transactions = s.scalar(select(func.count()).select_from(Transaction)) or 0
            except (MigrationFailed, DatabaseError, sqlcipher3.Error):
                raise RestoreRefused(DAMAGED) from None
            finally:
                new.dispose()
            shutil.rmtree(books.files_dir(info), ignore_errors=True)
            store = books.file_store(info)
            for fid in h.files:
                try:
                    data = X.open_sealed(k_file, fid, z.read(f"files/{fid}"))
                except (InvalidTag, ValueError, *_ZIP_ERRORS):
                    raise RestoreRefused(BAD_FILE) from None
                store.write(fid, data)                         # its AAD carries the new book's id
            for uid in dict.fromkeys(managers):
                add_membership(ddb, uid, row.id, "manager", by=None, now=now, note="Restored from an export", welcomed=True)
            ddb.commit()
        except BaseException:
            # The folder goes before the directory row does, so a book made meanwhile can't take the slug and then
            # lose its folder to this cleanup.
            remove_db_files(target)
            shutil.rmtree(books.files_dir(info), ignore_errors=True)
            shutil.rmtree(target.parent, ignore_errors=True)       # the book's own folder: never half a book
            ddb.rollback()
            raise
    return info, {"transactions": transactions, "files": len(h.files)}
