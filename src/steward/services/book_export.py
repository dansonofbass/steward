"""An encrypted backup of one book that only its passphrase opens (import/export spec P26-P30; The encrypted backup:
crypto design). Every key in the file comes from Argon2id over the NFC passphrase and a random salt, split by HKDF
into a database key and a files key: nothing from steward.key or the book's key. The live book's own key only opens
the source; sqlcipher_export writes the copy under the new key, so no file ever holds data under both. The copy is
made in a 0700 folder outside backups/ (Hyper Backup never ships it). The passphrase and the keys live only in this
call's memory; Python can't promise they're zeroed, so this claims no more than dropping the references."""
from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import tempfile
import threading
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.books.owners import to_json
from steward.db.engine import allow_writes
from steward.db.keys import hkdf_sha256
from steward.db.models import StoredFile
from steward.inventory.files import FileUnreadable

FORMAT = "steward-book-export"
VERSION = 1
PREFIX = "steward-export-"
FILE_MAGIC = b"SWX1"
NONCE_BYTES = 12
SALT_BYTES = 16
KEY_BYTES = 64
MIN_CHARS = 12
TTL = timedelta(minutes=10)
DB_INFO = b"steward/export/v1/db"
FILES_INFO = b"steward/export/v1/files"
TOO_SHORT = "Use at least 12 characters."
MISMATCH = "The two don't match."
BUSY = "Another backup is being made. Try again in a minute."
EXPIRED = "That download has expired. Make the backup again."
UNREADABLE_FILE = "One of this book's files can't be read, so no backup was made."
LOCK = threading.Lock()          # P29: one backup at a time, process-wide
# P27: emptied in the copy (and simplefin_link's access_url blanked). Ask conversations are private to each person,
# and the manager who makes a backup chooses its passphrase, so nobody's conversations travel in it; nor does mail
# still to go, which can quote other people's flags. Children before their parent (chat_turn, chat_message, then
# chat_conversation). secure_delete and the VACUUM after keep the rows out of the file's free pages too.
EXPORT_EMPTIES = ("undo_text", "undo_entry", "chat_turn", "chat_message", "chat_seen", "chat_conversation",
                  "mail_outbox", "statement_stage")      # PDF statements P50: a staged statement is half-done work
# What a restore never reads from a backup and leaves empty: the stripped SimpleFIN link and the export's own empties,
# mail still to go (it would go from this NAS's sender), and rows keyed by another NAS's directory user ids (email
# switches, Profile marks, Home visits, the chat disclosure seen). Kept beside the export's list so the two move together.
# Ask conversations are private to one person and keyed by a directory user id; on another NAS that id can be
# someone else, so a restore starts Ask afresh (the audit of what was sent, advisor_outgoing, is kept).
RESTORE_BLANKS = ("simplefin_link", *EXPORT_EMPTIES, "watch_recipient", "user_setup", "home_visit")


class ExportRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def normalize(passphrase: str) -> str:
    return unicodedata.normalize("NFC", passphrase)


def check_passphrase(passphrase: object, again: object) -> str:
    """P28: at least 12 characters, typed twice, NFC-normalized (so it opens the file from any device)."""
    if not isinstance(passphrase, str) or not isinstance(again, str) or len(normalize(passphrase)) < MIN_CHARS:
        raise ExportRefused(422, TOO_SHORT)
    if normalize(passphrase) != normalize(again):
        raise ExportRefused(422, MISMATCH)
    return normalize(passphrase)


def keys(passphrase: str, salt: bytes, t: int, m_kib: int, p: int) -> tuple[bytes, bytes]:
    k = hash_secret_raw(normalize(passphrase).encode("utf-8"), salt, time_cost=t, memory_cost=m_kib, parallelism=p,
                        hash_len=KEY_BYTES, type=Type.ID)
    return hkdf_sha256(k, DB_INFO, 32), hkdf_sha256(k, FILES_INFO, 32)


def file_aad(file_id: int) -> bytes:
    return f"steward/export/v1/file/{file_id}".encode()


def seal(key: bytes, file_id: int, data: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE_BYTES)
    return FILE_MAGIC + nonce + AESGCM(key).encrypt(nonce, data, file_aad(file_id))


def open_sealed(key: bytes, file_id: int, blob: bytes) -> bytes:
    """InvalidTag when the key, the id or a byte is wrong (GCM's tag)."""
    if blob[:4] != FILE_MAGIC:
        raise ValueError("not a sealed export file")
    nonce, body = blob[4:4 + NONCE_BYTES], blob[4 + NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, body, file_aad(file_id))


def tmp_root(settings) -> Path:
    return Path(settings.export_tmp_dir) if settings.export_tmp_dir else Path(tempfile.gettempdir())


def sweep(root: Path, now_ts: float, everything: bool = False) -> int:
    """Removes steward-export-* folders older than 10 minutes, or every one (at startup). Returns how many went."""
    if not root.is_dir():
        return 0
    gone = 0
    for d in root.glob(PREFIX + "*"):
        if d.is_dir() and (everything or now_ts - d.stat().st_mtime >= TTL.total_seconds()):
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
    return gone


@dataclass(frozen=True)
class Made:
    path: Path
    folder: Path
    filename: str
    size: int


def sql_path(p: Path) -> str:
    """Checked as backup._check checks folders: ATTACH takes no bound parameters."""
    s = str(p)
    if not p.is_absolute() or "'" in s or '"' in s or "\0" in s:
        raise ValueError("The export folder must be an absolute path without quote characters.")
    return s


def _copy(books, book, db_path: Path, k_db: bytes, now: datetime) -> None:
    """One read snapshot of the live book under WAL, written straight into the new file under the new key; then the
    secrets go (P27) with secure_delete on, the meta goes in, and VACUUM rewrites the file without the deleted pages."""
    raw = books.engine_for(book).raw_connection()
    try:
        allow_writes(raw)
        c = raw.driver_connection
        c.execute(f"ATTACH DATABASE '{sql_path(db_path)}' AS export KEY \"x'{k_db.hex()}'\"")
        try:
            c.execute("SELECT sqlcipher_export('export')")
            c.execute("PRAGMA export.secure_delete = ON")
            c.execute("UPDATE export.simplefin_link SET access_url = ''")
            for table in EXPORT_EMPTIES:
                c.execute(f"DELETE FROM export.{table}")
            c.execute("CREATE TABLE export.export_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            revision = c.execute("SELECT version_num FROM export.alembic_version").fetchone()[0]
            for k, v in (("kind", book.kind), ("name", book.name), ("owner_names", to_json(book.owner_names)),
                         ("exported_at", now.isoformat()), ("revision", revision)):
                c.execute("INSERT INTO export.export_meta (key, value) VALUES (?, ?)", (k, v))
            c.execute("VACUUM export")
        finally:
            c.execute("DETACH DATABASE export")
    finally:
        raw.close()


def make(books, book, passphrase: str, settings, today: date, now: datetime) -> Made:
    """P26: a stored ZIP of export.json (format, version and KDF only), book.db and, for a parent book, files/<id>."""
    if not LOCK.acquire(blocking=False):
        raise ExportRefused(429, BUSY)
    folder: Path | None = None
    try:
        t, m_kib, p = settings.export_kdf
        salt = secrets.token_bytes(SALT_BYTES)
        k_db, k_file = keys(passphrase, salt, t, m_kib, p)
        root = tmp_root(settings)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix=PREFIX, dir=root))          # 0700
        db_path = folder / "book.db"
        _copy(books, book, db_path, k_db, now)
        os.chmod(db_path, 0o600)
        filename = f"steward-{book.slug}-{today.isoformat()}.steward-backup"
        path = folder / filename
        meta = {"format": FORMAT, "version": VERSION,
                "kdf": {"name": "argon2id", "t": t, "m_kib": m_kib, "p": p, "salt": base64.b64encode(salt).decode()}}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr("export.json", json.dumps(meta))
            z.write(db_path, "book.db")
            db_path.unlink()
            if book.kind == "parent":
                store = books.file_store(book)
                with Session(books.engine_for(book)) as s:
                    ids = list(s.scalars(select(StoredFile.id).order_by(StoredFile.id)))
                for fid in ids:
                    try:
                        data = store.read(fid)                  # decrypted with the book's file key, in memory
                    except FileUnreadable:
                        raise ExportRefused(409, UNREADABLE_FILE) from None
                    z.writestr(f"files/{fid}", seal(k_file, fid, data))
        del k_db, k_file
        return Made(path, folder, filename, path.stat().st_size)
    except BaseException:
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        LOCK.release()
