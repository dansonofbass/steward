import hashlib
import hmac
import os
import re
import secrets
import stat
from pathlib import Path


class KeyMissing(RuntimeError):
    pass


KEY_FILE_SHARED = "The key file {path} can be read by others (mode {mode}). Run: chmod 600 {path}"
KEY_FILE_UNWRITABLE = ("STEWARD_KEY_FILE is {path}, and Steward can't write there. Run `steward keygen`, save the "
                       "line it prints in that file (mode 600, readable by Steward), and run this again.")
KEY_FILE_MISSING = ("No encryption key at {path} (STEWARD_KEY_FILE). Run `steward keygen` and save its line there "
                    "(mode 600).")


def new_key() -> str:
    """64 hex characters: 32 random bytes, the master key every database key derives from."""
    return secrets.token_hex(32)


def ensure_key(path: Path) -> str:
    if path.exists():
        return read_key(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = new_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    return key


def check_private(path: Path) -> None:
    """STEWARD_KEY_FILE must be private to Steward: no group or other bits (600 or 400). stat follows a symlink, so a
    link's target is what counts. The message names the path and the mode, never the key."""
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise KeyMissing(KEY_FILE_SHARED.format(path=path, mode=f"{mode:o}"))


def read_key(path: Path, *, private: bool = False) -> str:
    """The master key. private=True is STEWARD_KEY_FILE's read: refused when others can read the file."""
    if not path.exists():
        raise KeyMissing(KEY_FILE_MISSING.format(path=path) if private
                         else f"No encryption key at {path}. Run `steward init-key`.")
    if private:
        if not path.is_file():
            raise KeyMissing(f"{path} isn't a file.")
        check_private(path)
    key = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", key):
        raise KeyMissing(f"Key at {path} is not 64 hex characters.")
    return key


def ensure_key_file(path: Path) -> str:
    """STEWARD_KEY_FILE's key: read through the mode check when it's there, else made there (mode 600). A path Steward
    can't write (a read-only Docker secret's folder, a dangling link) says to use `steward keygen`."""
    if path.exists():
        return read_key(path, private=True)
    try:
        return ensure_key(path)
    except OSError:
        raise KeyMissing(KEY_FILE_UNWRITABLE.format(path=path)) from None


DIRECTORY_INFO = "steward/directory"


def hkdf_sha256(ikm: bytes, info: bytes, length: int = 32, salt: bytes | None = None) -> bytes:
    """RFC 5869 HKDF with SHA-256. No salt means HashLen zero bytes, as the RFC says."""
    if not 0 < length <= 255 * 32:
        raise ValueError("HKDF output length out of range")
    prk = hmac.new(salt if salt else bytes(32), ikm, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def derive_key(master_hex: str, info: str) -> str:
    """A database key derived from steward.key (spec 2.3). steward.key stays the only secret to keep."""
    return hkdf_sha256(bytes.fromhex(master_hex), info.encode()).hex()


def directory_key(master_hex: str) -> str:
    return derive_key(master_hex, DIRECTORY_INFO)


def book_key(master_hex: str, book_id: int) -> str:
    return derive_key(master_hex, f"steward/book/{book_id}")
