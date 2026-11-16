import os

import pytest

from steward.db.keys import book_key, hkdf_sha256
from steward.inventory.files import (
    FileRefused, FileStore, FileUnreadable, clean_name, file_key, looks_like_tax_form, sniff,
)

MASTER = "11" * 32
PDF = b"%PDF-1.4\n%made-up statement\n%%EOF\n"


def store(tmp_path, book_id=7, master=MASTER):
    return FileStore(tmp_path / "files", file_key(master, book_id), book_id)


def test_the_file_key_is_its_own_hkdf_derivation():
    assert file_key(MASTER, 7) == hkdf_sha256(bytes.fromhex(MASTER), b"steward/book/7/files")
    assert file_key(MASTER, 7).hex() != book_key(MASTER, 7)
    assert len(file_key(MASTER, 7)) == 32


def test_a_file_round_trips_and_is_encrypted_at_rest(tmp_path):
    s = store(tmp_path)
    s.write(3, PDF)
    raw = s.path(3).read_bytes()
    assert raw[:4] == b"SWF1" and PDF not in raw and b"made-up" not in raw
    assert s.read(3) == PDF
    assert oct(s.path(3).stat().st_mode & 0o777) == "0o600"
    assert not (tmp_path / "files" / "3.partial").exists()


def test_another_books_key_or_a_moved_file_fails(tmp_path):
    s = store(tmp_path)
    s.write(3, PDF)
    with pytest.raises(FileUnreadable):
        store(tmp_path, book_id=8).read(3)            # another book's key
    os.replace(s.path(3), s.path(4))
    with pytest.raises(FileUnreadable):
        s.read(4)                                    # the id is bound into the ciphertext


def test_a_changed_byte_fails(tmp_path):
    s = store(tmp_path)
    s.write(3, PDF)
    raw = bytearray(s.path(3).read_bytes())
    raw[-1] ^= 1
    s.path(3).write_bytes(bytes(raw))
    with pytest.raises(FileUnreadable):
        s.read(3)


def test_a_failed_write_leaves_nothing(tmp_path, monkeypatch):
    s = store(tmp_path)
    def boom(*a):
        raise OSError("disk full")
    monkeypatch.setattr("steward.inventory.files.os.replace", boom)
    with pytest.raises(OSError):
        s.write(3, PDF)
    assert list((tmp_path / "files").iterdir()) == []


def test_the_folder_is_fsynced_after_the_rename(tmp_path, monkeypatch):
    import stat
    s = store(tmp_path)
    calls = []
    real_replace, real_fsync = os.replace, os.fsync
    monkeypatch.setattr("steward.inventory.files.os.replace",
                        lambda a, b: (calls.append("replace"), real_replace(a, b))[1])

    def fsync(fd):
        calls.append("fsync folder" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync file")
        return real_fsync(fd)

    monkeypatch.setattr("steward.inventory.files.os.fsync", fsync)
    s.write(3, PDF)
    assert calls == ["fsync file", "replace", "fsync folder"]


@pytest.mark.parametrize("name,data,expected", [
    ("Statement.pdf", PDF, ("application/pdf", "PDF")),
    ("card.PNG", b"\x89PNG\r\n\x1a\n" + b"0" * 20, ("image/png", "PNG")),
    ("Signature card.jpg", b"\xff\xd8\xff\xe0" + b"0" * 20, ("image/jpeg", "JPEG")),
    ("scan.jpeg", b"\xff\xd8\xff\xdb" + b"0" * 20, ("image/jpeg", "JPEG")),
    ("IMG_0001.HEIC", b"\x00\x00\x00\x18ftypheic" + b"0" * 20, ("image/heic", "HEIC")),
    ("IMG_0002.heic", b"\x00\x00\x00\x18ftypmif1" + b"0" * 20, ("image/heic", "HEIC")),
    ("1099s.csv", "form,payer\n1099-INT,Harbor Savings Bank\n".encode(), ("text/csv", "CSV")),
])
def test_allowed_types(name, data, expected):
    assert sniff(name, data) == expected


@pytest.mark.parametrize("name,data,message", [
    ("Westmark export.xlsx", b"PK\x03\x04", "Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV. Save it as PDF or CSV and try again."),
    ("notes", b"hello", "Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV. Save it as PDF or CSV and try again."),
    ("fake.pdf", b"<html>", "Not attached: the file inside isn't a PDF. Save it again and try again."),
    ("data.csv", b"a,b\x00c", "Not attached: the file inside isn't a CSV. Save it again and try again."),
])
def test_refused_types(name, data, message):
    with pytest.raises(FileRefused) as e:
        sniff(name, data)
    assert str(e.value) == message


def test_names_and_tax_form_nudges():
    assert clean_name("C:\\Users\\me\\Statement Sep 2026.pdf") == "Statement Sep 2026.pdf"
    assert clean_name("../../etc/passwd.pdf") == "passwd.pdf"
    assert clean_name("bad\x07name.pdf") == "badname.pdf"
    assert clean_name("") == "file"
    assert looks_like_tax_form("1099-INT 2025 Harbor Savings.pdf") and looks_like_tax_form("SSA-1099 2025.pdf")
    assert not looks_like_tax_form("Statement Sep 2026.pdf")
