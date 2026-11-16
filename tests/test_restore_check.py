"""steward restore-check (backups spec, Part 1): last night's copies open with their keys, pass integrity, sit at the
current schema, aren't empty, and every mirrored file decrypts. backups/ is left exactly as it was."""
import os
import stat
from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from steward.books.service import create_book
from steward.db.migrate import book_head
from steward.db.models import StoredFile
from steward.services import backup as bk
from steward.services import restore_check as rc
from tests.factories import make_account, make_person, make_txn

STAMP = "20261028-013230"
NOW = datetime(2026, 10, 28, 9, 0)          # 7.5 hours after the run


def _run(books, dest, monkeypatch, stamp=STAMP):
    monkeypatch.setattr(bk, "_stamp", lambda: stamp)
    written, skipped = bk.backup_all(books, dest)
    return skipped


def _file(books, info, file_id, data):
    books.file_store(info).write(file_id, data)
    with Session(books.engine_for(info)) as s:
        s.add(StoredFile(id=file_id, name="secret-name.pdf", content_type="application/pdf", size=len(data),
                         sha256="0" * 64, uploaded_by=1))
        s.commit()


def _setup(books, ddb, db):
    a = make_account(db, "Checking")
    make_txn(db, a, date(2026, 10, 1), -4321, "PRIVATE DESCRIPTION")
    db.commit()
    mom = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret"])
    _file(books, mom, 1, b"%PDF-1.4 one")
    _file(books, mom, 2, b"%PDF-1.4 two")
    return mom


def _text(r):
    return "\n".join(r.lines)


def _edit(path, key_hex, sql):
    """Changes a backup copy in place without WAL (make_engine would switch the file to WAL and leave a -wal file
    whose loss would drop the change)."""
    import sqlcipher3
    c = sqlcipher3.connect(str(path))
    c.execute(f"PRAGMA key = \"x'{key_hex}'\"")
    c.execute(sql)
    c.commit()
    c.close()


def test_a_good_run_restores_and_says_so(books, ddb, db, monkeypatch, tmp_path):
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    assert _run(books, dest, monkeypatch) == []
    r = rc.restore_check(books, dest, now=NOW)
    assert r.ok and r.failures == 0 and r.stamp == STAMP and r.books == 2 and r.files == 2, _text(r)
    head = book_head()
    assert f"ours: ok (schema {head}, 1 transaction, 0 files)" in r.lines
    assert f"margaret-ellis: ok (schema {head}, 0 transactions, 2 files)" in r.lines
    assert r.lines[-1] == f"Backup {STAMP} restores: 2 books, 2 files."


def test_a_sample_is_not_expected_in_the_backup(books, ddb, monkeypatch, tmp_path):
    """backup_all walks books.books(), which leaves Samples out, so the check must not ask for one."""
    u = make_person(ddb, "sampler")
    create_book(books, ddb, name="Sample", kind="household", by=u.id, sample_of=u.id)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    r = rc.restore_check(books, dest, now=NOW)
    assert r.ok and r.books == 1, _text(r)
    assert not any("sample" in line.lower() for line in r.lines), _text(r)


def test_no_backup_or_a_stale_one_fails(books, monkeypatch, tmp_path):
    r = rc.restore_check(books, tmp_path / "empty", now=NOW)
    assert not r.ok and r.stamp is None and "No backup in" in _text(r)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch, stamp="20261026-013230")
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "55 hours old" in _text(r) and "the last 30 hours" in _text(r)
    assert rc.restore_check(books, dest, now=NOW, max_age_hours=72).ok


def test_a_book_skipped_last_night_fails_and_is_named(books, ddb, db, monkeypatch, tmp_path):
    """Review Focus 1: backup_all says Skipped and exits 0; the check is what fails."""
    mom = _setup(books, ddb, db)
    books.unavailable[mom.id] = "The book's file is missing."
    dest = tmp_path / "bk"
    assert _run(books, dest, monkeypatch) == ["Skipped margaret-ellis: The book's file is missing."]
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and f"margaret-ellis: no copy in backup {STAMP}." in r.lines


def test_the_check_leaves_the_backups_folder_as_it_was(books, ddb, db, monkeypatch, tmp_path):
    """Review Focus 2: no -wal/-shm beside a copy, nothing added or changed, and the scratch folder is gone."""
    import tempfile
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    before = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    assert rc.restore_check(books, dest, now=NOW).ok
    after = {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    assert after == before
    assert list(scratch.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0 file")
def test_an_unreadable_copy_is_a_failure_line_not_a_traceback(books, ddb, db, monkeypatch, tmp_path):
    """A copy the check can't read (on the NAS, a root-owned 0600 file) is that book's failure; the others go on."""
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    p = dest / f"steward-margaret-ellis-{STAMP}.db"
    p.chmod(0)
    try:
        r = rc.restore_check(books, dest, now=NOW)
    finally:
        p.chmod(0o600)
    assert not r.ok and r.failures == 1, _text(r)
    assert "margaret-ellis: the copy can't be read (the file is missing or unreadable)." in r.lines
    assert any(line.startswith("ours: ok (") for line in r.lines), _text(r)


def test_scratch_copies_are_private(books, ddb, db, monkeypatch, tmp_path):
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    for p in dest.glob("*.db"):
        p.chmod(0o644)
    modes = []
    real = rc.make_engine

    def spy(path, key):
        modes.append(stat.S_IMODE(path.stat().st_mode))
        return real(path, key)

    monkeypatch.setattr(rc, "make_engine", spy)
    assert rc.restore_check(books, dest, now=NOW).ok
    assert modes == [0o600, 0o600, 0o600]


def test_a_wrong_key_fails_without_saying_the_key(books, ddb, db, monkeypatch, tmp_path):
    """Review Focus 3."""
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    wrong = "ab" * 32
    r = rc.restore_check(books, dest, now=NOW, master=wrong)
    assert not r.ok and "directory: the key doesn't open it." in r.lines
    assert wrong not in _text(r) and books.master not in _text(r)


def test_a_damaged_copy_fails(books, ddb, db, monkeypatch, tmp_path):
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    p = dest / f"steward-ours-{STAMP}.db"
    raw = bytearray(p.read_bytes())
    for i in range(len(raw) // 2, len(raw) // 2 + 64):
        raw[i] ^= 0xFF
    p.write_bytes(bytes(raw))
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and any(line.startswith("ours: ") and "ok (" not in line for line in r.lines), _text(r)


def test_a_copy_at_an_older_schema_fails(books, ddb, db, monkeypatch, tmp_path):
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    _edit(dest / f"steward-ours-{STAMP}.db", books.master, "UPDATE alembic_version SET version_num = '0022'")
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and f"ours: schema 0022, expected {book_head()}." in r.lines


def test_an_empty_copy_of_a_live_book_fails(books, ddb, db, monkeypatch, tmp_path):
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    _edit(dest / f"steward-ours-{STAMP}.db", books.master, 'DELETE FROM "transaction"')
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "ours: the copy has no transactions, but the book has 1." in r.lines


def test_a_missing_damaged_or_swapped_file_fails(books, ddb, db, monkeypatch, tmp_path):
    """Review Focus 4: the AAD binds the file id, so file 2's ciphertext stored as file 1 doesn't decrypt."""
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    mirror = dest / "steward-margaret-ellis-files"
    (mirror / "1").write_bytes((mirror / "2").read_bytes())
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "margaret-ellis: file 1 doesn't decrypt (the file doesn't match its key or id)." in r.lines
    (mirror / "1").unlink()
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "margaret-ellis: file 1 is missing from the backup." in r.lines
    assert "secret-name" not in _text(r) and "%PDF" not in _text(r)


def test_an_unavailable_live_book_skips_only_the_comparison(books, ddb, db, monkeypatch, tmp_path):
    """Review Focus 5."""
    mom = _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    books.unavailable[mom.id] = "The book's file is missing."
    r = rc.restore_check(books, dest, now=NOW)
    assert r.ok, _text(r)
    assert any(line.startswith("margaret-ellis: ok (") and "the live book couldn't be opened" in line for line in r.lines)


def test_nothing_private_is_printed(books, ddb, db, monkeypatch, tmp_path):
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    out = _text(rc.restore_check(books, dest, now=NOW))
    for private in ("PRIVATE DESCRIPTION", "43.21", "4321", "secret-name", books.master, "Checking"):
        assert private not in out, private


def test_a_directory_listing_no_books_fails(books, ddb, db, monkeypatch, tmp_path):
    from steward.db.keys import directory_key
    _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    _edit(dest / f"steward-directory-{STAMP}.db", directory_key(books.master), "DELETE FROM book")
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "directory: lists no books." in r.lines, _text(r)


def test_a_future_or_impossible_stamp_fails(books, tmp_path):
    future = tmp_path / "f"
    future.mkdir()
    (future / "steward-directory-20261028-103000.db").write_bytes(b"")
    r = rc.restore_check(books, future, now=NOW)
    assert not r.ok and "The newest backup is dated in the future (20261028-103000); check this machine's clock." in r.lines
    bad = tmp_path / "b"
    bad.mkdir()
    (bad / "steward-directory-20269999-999999.db").write_bytes(b"")
    r = rc.restore_check(books, bad, now=NOW)
    assert not r.ok and "The newest backup's name has a bad date (20269999-999999)." in r.lines


def test_a_missing_table_is_a_failure_line_not_a_traceback(books, ddb, db, monkeypatch, tmp_path):
    from steward.db.keys import book_key, directory_key
    mom = _setup(books, ddb, db)
    dest = tmp_path / "bk"
    _run(books, dest, monkeypatch)
    _edit(dest / f"steward-margaret-ellis-{STAMP}.db", book_key(books.master, mom.id), "DROP TABLE file")
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "margaret-ellis: the copy can't be read (a table is missing or damaged)." in r.lines, _text(r)
    _edit(dest / f"steward-directory-{STAMP}.db", directory_key(books.master), "DROP TABLE alembic_version")
    r = rc.restore_check(books, dest, now=NOW)
    assert not r.ok and "directory: the copy can't be read (a table is missing or damaged)." in r.lines, _text(r)
