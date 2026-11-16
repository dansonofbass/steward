"""Uploaded files (spec 3.5; rulings 1-4). AES-256-GCM through the cryptography package, with a per-book key from
steward.key (HKDF-SHA256, info steward/book/<id>/files). Each file is SWF1 + a random 12-byte nonce + ciphertext and
tag, with the book and file id as associated data, so a file moved to another id or book won't decrypt. Writes go to
<id>.partial, are fsynced, renamed, and the folder is fsynced, so no partial file is ever left under its real name (spec 8)."""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from steward.db.keys import hkdf_sha256

MAX_BYTES = 25 * 1024 * 1024
MAGIC = b"SWF1"
NONCE_BYTES = 12
TYPES = {"pdf": ("application/pdf", "PDF"), "png": ("image/png", "PNG"), "jpg": ("image/jpeg", "JPEG"),
         "jpeg": ("image/jpeg", "JPEG"), "heic": ("image/heic", "HEIC"), "csv": ("text/csv", "CSV")}
HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"})

TOO_BIG = "Not attached: it's over 25 MB. Steward takes files up to 25 MB."
WRONG_TYPE = "Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV. Save it as PDF or CSV and try again."
NOT_WHAT_IT_SAYS = "Not attached: the file inside isn't a {label}. Save it again and try again."
EMPTY = "Not attached: the file is empty."
DISK = "Not attached: Steward couldn't save it. Try again in a minute."
UNREADABLE = "This file can't be read. Restore it from the backup (docs/guides/backups.md)."
_TAX_FORM = re.compile(r"(?i)(^|[^0-9A-Z])(SSA[- ]?)?1099(-?(INT|DIV|R))?([^0-9A-Z]|$)")


class FileRefused(ValueError):
    def __init__(self, message: str, status: int = 415):
        super().__init__(message)
        self.status = status


class FileUnreadable(RuntimeError):
    """The bytes on disk don't decrypt with this book's key and this file's id."""


def file_key(master_hex: str, book_id: int) -> bytes:
    return hkdf_sha256(bytes.fromhex(master_hex), f"steward/book/{book_id}/files".encode())


def _aad(book_id: int, file_id: int) -> bytes:
    return f"steward/book/{book_id}/file/{file_id}".encode()


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff(name: str, data: bytes) -> tuple[str, str]:
    """(content type, label) when the extension is allowed and the bytes match it (ruling 4)."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in TYPES:
        raise FileRefused(WRONG_TYPE)
    ok = {"pdf": data.startswith(b"%PDF-"), "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
          "jpg": data[:3] == b"\xff\xd8\xff", "jpeg": data[:3] == b"\xff\xd8\xff",
          "heic": data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS, "csv": _is_text(data)}[ext]
    if not ok:
        raise FileRefused(NOT_WHAT_IT_SAYS.format(label=TYPES[ext][1]))
    return TYPES[ext]


def clean_name(raw: str | None) -> str:
    """The file's own name without any folder, control characters or more than 200 characters."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch >= " " and ch != "\x7f").strip()
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 199 - len(ext)] + dot + ext) if dot and len(ext) <= 10 else name[:200]
    return name or "file"


def looks_like_tax_form(name: str) -> bool:
    """Decision 10's nudge: a file named like a 1099 or an SSA-1099."""
    return bool(_TAX_FORM.search(name))


class FileStore:
    """One book's encrypted files folder."""

    def __init__(self, folder: Path, key: bytes, book_id: int):
        self.folder, self.key, self.book_id = folder, key, book_id

    def path(self, file_id: int) -> Path:
        return self.folder / str(file_id)

    def write(self, file_id: int, data: bytes) -> None:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        nonce = secrets.token_bytes(NONCE_BYTES)
        blob = MAGIC + nonce + AESGCM(self.key).encrypt(nonce, data, _aad(self.book_id, file_id))
        tmp = self.folder / f"{file_id}.partial"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path(file_id))
            dir_fd = os.open(self.folder, os.O_RDONLY)      # so a power cut can't lose the rename
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def read(self, file_id: int) -> bytes:
        try:
            blob = self.path(file_id).read_bytes()
        except OSError as e:
            raise FileUnreadable(str(e)) from None
        if blob[:4] != MAGIC or len(blob) < 4 + NONCE_BYTES + 16:
            raise FileUnreadable("not a Steward file")
        nonce, body = blob[4:4 + NONCE_BYTES], blob[4 + NONCE_BYTES:]
        try:
            return AESGCM(self.key).decrypt(nonce, body, _aad(self.book_id, file_id))
        except InvalidTag:
            raise FileUnreadable("the file doesn't match its key or id") from None

    def remove(self, file_id: int) -> None:
        self.path(file_id).unlink(missing_ok=True)
        (self.folder / f"{file_id}.partial").unlink(missing_ok=True)
