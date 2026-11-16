import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.books.service import create_book
from steward.db.directory_models import User
from steward.db.engine import check_key, make_engine
from steward.db.keys import directory_key
from steward.services import backup as bk
from tests.factories import make_user


def test_one_copy_per_book_and_the_directory_each_keeping_14(books, ddb, db, monkeypatch, tmp_path):
    make_user(db)
    create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    n = iter(range(100))
    monkeypatch.setattr(bk, "_stamp", lambda: f"20260101-0000{next(n):02d}")
    dest = tmp_path / "bk"
    written, skipped = bk.backup_all(books, dest)
    assert skipped == []
    assert sorted(p.name for p in written) == ["steward-directory-20260101-000000.db", "steward-mom-20260101-000000.db",
                                               "steward-ours-20260101-000000.db"]
    assert oct(dest.stat().st_mode & 0o777) == "0o700"
    copy = make_engine(dest / "steward-directory-20260101-000000.db", directory_key(books.master))
    check_key(copy)
    with Session(copy) as s:
        assert s.scalar(select(User.username)) == "jr"
    copy.dispose()
    mom_copy = make_engine(dest / "steward-mom-20260101-000000.db", books.key_for(books.book("mom")))
    check_key(mom_copy)
    mom_copy.dispose()
    for _ in range(16):
        bk.backup_all(books, dest)
    for prefix in ("steward-directory-", "steward-ours-", "steward-mom-"):
        left = sorted(p.name for p in dest.iterdir() if p.name.startswith(prefix))
        assert len(left) == 14 and left[-1] == f"{prefix}20260101-000016.db", prefix


def test_a_slug_that_starts_like_another_is_pruned_on_its_own(books, ddb, monkeypatch, tmp_path):
    create_book(books, ddb, name="Ours 2", kind="parent", owner_labels=["A"])   # slug ours-2
    n = iter(range(100))
    monkeypatch.setattr(bk, "_stamp", lambda: f"20260101-0000{next(n):02d}")
    dest = tmp_path / "bk"
    for _ in range(20):
        bk.backup_all(books, dest, keep=3)
    names = sorted(p.name for p in dest.iterdir())
    assert len([x for x in names if x.startswith("steward-ours-2-")]) == 3
    assert len([x for x in names if x.startswith("steward-ours-2026")]) == 3


def test_an_unavailable_book_is_skipped_and_said(books, ddb, tmp_path):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    books.unavailable[mom.id] = "The book's file is missing."
    written, skipped = bk.backup_all(books, tmp_path / "bk")
    assert skipped == ["Skipped mom: The book's file is missing."]
    assert not any("steward-mom-" in p.name for p in written)


def test_a_quote_in_the_folder_is_refused(books, tmp_path):
    with pytest.raises(ValueError, match="absolute path without quote"):
        bk.backup_all(books, tmp_path / "it's")


def test_a_books_files_are_mirrored_into_the_backups(books, ddb, tmp_path, monkeypatch):
    n = iter(range(100))
    monkeypatch.setattr(bk, "_stamp", lambda: f"20260101-0000{next(n):02d}")
    from steward.books.service import create_book
    from steward.services.backup import backup_all
    mom = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret"])
    store = books.file_store(mom)
    store.write(1, b"%PDF-1.4 one")
    dest = tmp_path / "bk"
    backup_all(books, dest)
    mirror = dest / "steward-margaret-ellis-files"
    assert (mirror / "1").read_bytes() == store.path(1).read_bytes()
    store.write(2, b"%PDF-1.4 two")
    store.remove(1)                      # removed in the app: its encrypted copy stays (ruling 5)
    backup_all(books, dest)
    assert sorted(p.name for p in mirror.iterdir() if p.name.isdigit()) == ["1", "2"]
    assert oct(mirror.stat().st_mode & 0o777) == "0o700" and oct((mirror / "2").stat().st_mode & 0o777) == "0o600"


def test_a_removed_files_copy_goes_14_days_after_it_was_removed(tmp_path):
    from datetime import datetime, timedelta, timezone
    from steward.services.backup import mirror_files
    src, dest = tmp_path / "files", tmp_path / "mirror"
    src.mkdir()
    (src / "1").write_bytes(b"one")
    (src / "2").write_bytes(b"two")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert mirror_files(src, dest, now=t0) == 2
    (src / "1").unlink()
    mirror_files(src, dest, now=t0 + timedelta(days=1))          # first noticed missing
    assert (dest / "1").exists() and (dest / "1.gone").exists()
    mirror_files(src, dest, now=t0 + timedelta(days=14, hours=23))   # 13 days 23 hours after noticed
    assert (dest / "1").exists()
    mirror_files(src, dest, now=t0 + timedelta(days=15))
    assert not (dest / "1").exists() and not (dest / "1.gone").exists() and (dest / "2").exists()
    (src / "3").write_bytes(b"three")
    mirror_files(src, dest, now=t0 + timedelta(days=16))
    (src / "3").unlink()
    mirror_files(src, dest, now=t0 + timedelta(days=17))
    (src / "3").write_bytes(b"three")                             # present again clears its tombstone
    mirror_files(src, dest, now=t0 + timedelta(days=18))
    assert not (dest / "3.gone").exists()


def test_a_same_size_file_with_different_bytes_is_copied_again(tmp_path):
    from steward.services.backup import mirror_files
    src, dest = tmp_path / "files", tmp_path / "mirror"
    src.mkdir()
    (src / "1").write_bytes(b"AAAA")
    assert mirror_files(src, dest) == 1
    assert mirror_files(src, dest) == 0                 # same size, same bytes: skipped
    (src / "1").write_bytes(b"BBBB")                    # an id reused after a restore
    assert mirror_files(src, dest) == 1
    assert (dest / "1").read_bytes() == b"BBBB"


def test_a_mirror_error_in_one_book_is_said_and_the_others_still_get_copies(books, ddb, tmp_path, monkeypatch):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    dad = create_book(books, ddb, name="Dad", kind="parent", owner_labels=["Joe"])
    books.file_store(mom).write(1, b"%PDF-1.4 one")
    books.file_store(dad).write(1, b"%PDF-1.4 two")
    real = bk.mirror_files

    def flaky(src, dest, now=None):
        if "mom" in dest.name:
            raise OSError(28, "No space left on device")
        return real(src, dest, now)

    monkeypatch.setattr(bk, "mirror_files", flaky)
    written, skipped = bk.backup_all(books, tmp_path / "bk")
    assert skipped == ["Skipped the files copy for mom: No space left on device"]
    assert (tmp_path / "bk" / "steward-dad-files" / "1").exists()
    assert any(p.name.startswith("steward-mom-") and p.suffix == ".db" for p in written)


def test_a_folder_that_holds_the_key_is_refused(books, settings):
    with pytest.raises(ValueError, match="holds the encryption key"):
        bk.backup_all(books, settings.data_dir)
    assert not list(settings.data_dir.glob("steward-directory-*.db"))
