"""S1: the books are encrypted with AES-256. These tests read what SQLCipher reports for a real book, the statements
Steward runs to key it, and the bytes on disk, so a weaker cipher, a shorter key or a plaintext file fails here."""
import re
import secrets

import pytest
import sqlcipher3
from sqlalchemy import text

from steward.db.engine import WrongKey, check_key, make_engine
from steward.db.keys import book_key, ensure_key

MARKER = "plaintext-marker-7f3a9c1e"
KEY_PRAGMA = re.compile(r"""PRAGMA\s+key\s*=\s*["']x'[0-9a-fA-F]{64}'["']\s*;?""", re.IGNORECASE)
WEAKENING_PRAGMA = re.compile(r"cipher|kdf|page_size|hmac|rekey|compatibility", re.IGNORECASE)


@pytest.fixture
def book(tmp_path, monkeypatch):
    """A real book keyed the way the app keys one, with every statement run on its connections recorded."""
    statements: list[str] = []
    real_connect = sqlcipher3.connect

    def recording_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(sqlcipher3, "connect", recording_connect)
    master = ensure_key(tmp_path / "steward.key")
    key = book_key(master, 1)
    path = tmp_path / "books" / "1.db"
    engine = make_engine(path, key)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE note (body TEXT)"))
        c.execute(text("INSERT INTO note VALUES (:m)"), {"m": MARKER})
    yield {"engine": engine, "path": path, "master": master, "key": key, "statements": statements}
    engine.dispose()


def _pragma(engine, name):
    with engine.connect() as c:
        return c.exec_driver_sql(f"PRAGMA {name}").fetchall()


def test_sqlcipher_is_version_4_or_later_and_the_cipher_is_aes_256_cbc(book):
    version = _pragma(book["engine"], "cipher_version")[0][0]
    assert int(version.split(".")[0]) >= 4, version
    assert _pragma(book["engine"], "cipher")[0][0].upper() == "AES-256-CBC"


def test_cipher_settings_are_sqlcipher_4_strong_defaults(book):
    text_ = " ".join(str(r[0]) for r in _pragma(book["engine"], "cipher_settings")).upper()
    kdf_iter = int(_pragma(book["engine"], "kdf_iter")[0][0])
    assert kdf_iter >= 256000
    assert int(_pragma(book["engine"], "cipher_page_size")[0][0]) == 4096
    assert int(_pragma(book["engine"], "cipher_use_hmac")[0][0]) == 1
    assert "HMAC_SHA512" in text_
    assert "PBKDF2_HMAC_SHA512" in text_
    assert int(_pragma(book["engine"], "cipher_plaintext_header_size")[0][0]) == 0


def test_master_and_book_keys_are_256_bits(book):
    assert len(bytes.fromhex(book["master"])) == 32
    assert len(bytes.fromhex(book["key"])) == 32


def test_the_only_key_pragma_is_a_raw_256_bit_key_and_nothing_weakens_the_cipher(book):
    with book["engine"].connect() as c:
        c.exec_driver_sql("SELECT 1").fetchall()
    key_statements = [s for s in book["statements"] if re.match(r"\s*PRAGMA\s+key\b", s, re.IGNORECASE)]
    assert key_statements, "no key pragma was recorded"
    assert all(KEY_PRAGMA.fullmatch(s.strip()) for s in key_statements), key_statements
    assert not [s for s in book["statements"] if re.match(r"\s*PRAGMA\b", s, re.IGNORECASE)
                and not re.match(r"\s*PRAGMA\s+key\b", s, re.IGNORECASE) and WEAKENING_PRAGMA.search(s)
                and "=" in s], book["statements"]


def test_the_file_and_its_wal_hold_no_plaintext(book):
    engine, path = book["engine"], book["path"]
    assert _pragma(engine, "journal_mode")[0][0].lower() == "wal"   # the marker's pages are in the WAL
    files = [p for p in path.parent.iterdir() if p.name.startswith(path.name)]
    assert any(p.name.endswith("-wal") and p.stat().st_size > 0 for p in files)
    for p in files:
        data = p.read_bytes()
        assert not data.startswith(b"SQLite format 3"), p.name
        assert MARKER.encode() not in data, p.name
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    main = path.read_bytes()
    assert not main.startswith(b"SQLite format 3")
    assert MARKER.encode() not in main


def test_a_different_256_bit_key_cannot_read_the_book(book):
    book["engine"].dispose()
    other = make_engine(book["path"], secrets.token_hex(32))
    try:
        with pytest.raises(WrongKey):
            check_key(other)
    finally:
        other.dispose()
    right = make_engine(book["path"], book["key"])
    try:
        check_key(right)
    finally:
        right.dispose()
