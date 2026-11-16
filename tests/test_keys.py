import secrets

import pytest

from steward.db.engine import WrongKey, check_key, make_engine
from steward.db.keys import DIRECTORY_INFO, book_key, derive_key, directory_key, hkdf_sha256


def test_hkdf_matches_rfc_5869_case_1():
    okm = hkdf_sha256(b"\x0b" * 22, bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42,
                      salt=bytes.fromhex("000102030405060708090a0b0c"))
    assert okm.hex() == ("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
                         "34007208d5b887185865")


def test_hkdf_matches_rfc_5869_case_3_no_salt_no_info():
    okm = hkdf_sha256(b"\x0b" * 22, b"", 42)
    assert okm.hex() == ("8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d"
                         "9d201395faa4b61a96c8")


def test_derived_keys_are_64_hex_distinct_and_stable():
    master = "ab" * 32
    d, b1, b2 = directory_key(master), book_key(master, 1), book_key(master, 2)
    assert all(len(k) == 64 and int(k, 16) >= 0 for k in (d, b1, b2))
    assert len({master, d, b1, b2}) == 4
    assert d == derive_key(master, DIRECTORY_INFO) == directory_key(master)
    assert b1 == derive_key(master, "steward/book/1")


def test_one_file_cannot_be_opened_with_another_files_key(tmp_path):
    master = secrets.token_hex(32)
    keys = {"directory": directory_key(master), "book1": book_key(master, 1), "book2": book_key(master, 2)}
    for name, key in keys.items():
        eng = make_engine(tmp_path / f"{name}.db", key)
        with eng.begin() as c:
            c.exec_driver_sql("CREATE TABLE t (x INTEGER)")
        eng.dispose()
    for name in keys:
        for other, key in keys.items():
            eng = make_engine(tmp_path / f"{name}.db", key)
            if other == name:
                check_key(eng)
            else:
                with pytest.raises(WrongKey):
                    check_key(eng)
            eng.dispose()
