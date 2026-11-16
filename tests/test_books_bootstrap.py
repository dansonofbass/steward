import json
import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from steward.books import bootstrap
from steward.books.registry import BookRegistry, DirectoryUnavailable, open_books
from steward.db.directory_models import Book, DirectoryEvent, Membership, MembershipChange
from steward.db.engine import make_engine
from steward.db.keys import ensure_key
from tests.books_fixtures import make_pre_books_vault, sign_in_rows


def test_a_fresh_install_gets_ours_and_a_directory(settings):
    ensure_key(settings.key_path)
    books = open_books(settings)
    try:
        assert settings.directory_path.exists() and settings.db_path.exists()
        [ours] = books.books()
        assert (ours.slug, ours.name, ours.kind, ours.file, ours.key_scheme) == ("ours", "Ours", "household", "steward.db", "raw")
        assert [o.key for o in ours.owner_names] == ["jr", "spouse", "joint", "business"]
        assert not list(settings.backups_dir.glob("pre-books-*")) if settings.backups_dir.exists() else True
        with books.engine_for(ours).connect() as c:
            assert c.execute(text("SELECT count(*) FROM account")).scalar() == 0
    finally:
        books.dispose()


def test_the_move_copies_sign_in_rows_exactly_and_makes_everyone_a_manager(settings):
    key = make_pre_books_vault(settings)
    old = make_engine(settings.db_path, key)
    before = sign_in_rows(old)
    old.dispose()
    books = open_books(settings)
    try:
        assert sign_in_rows(books.directory) == before
        with Session(books.directory) as s:
            ours = s.scalar(select(Book).where(Book.slug == "ours"))
            assert ours.key_scheme == "raw" and ours.file == "steward.db"
            assert json.loads(ours.owner_names)[0] == {"key": "jr", "label": "Person 1"}
            members = s.execute(select(Membership.user_id, Membership.role).order_by(Membership.user_id)).all()
            assert members == [(1, "manager"), (2, "manager")]
            changes = s.execute(select(MembershipChange.user_id, MembershipChange.action, MembershipChange.role_after,
                                       MembershipChange.by_user_id)).all()
            assert sorted(changes) == [(1, "added", "manager", None), (2, "added", "manager", None)]
        [backup] = settings.backups_dir.glob("pre-books-steward-*.db")
        copy = make_engine(backup, key)
        assert sign_in_rows(copy) == before
        copy.dispose()
    finally:
        books.dispose()


def test_prepare_twice_changes_nothing_and_takes_one_backup(settings):
    make_pre_books_vault(settings)
    books = open_books(settings)
    rows = sign_in_rows(books.directory)
    books.prepare()
    assert sign_in_rows(books.directory) == rows
    with Session(books.directory) as s:
        assert s.scalar(text("SELECT count(*) FROM membership")) == 2
    books.dispose()
    assert len(list(settings.backups_dir.glob("pre-books-steward-*.db"))) == 1


def test_a_crash_before_the_rename_starts_again_cleanly(settings, monkeypatch):
    key = make_pre_books_vault(settings)
    real_replace = os.replace
    calls = {"n": 0}

    def crash_once(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("power cut")
        return real_replace(src, dst)

    monkeypatch.setattr(bootstrap.os, "replace", crash_once)
    with pytest.raises(OSError):
        open_books(settings)
    assert not settings.directory_path.exists()
    assert settings.directory_path.with_name("directory.db.partial").exists()
    books = open_books(settings)   # the next start removes the partial file and builds it again
    try:
        assert not settings.directory_path.with_name("directory.db.partial").exists()
        old = make_engine(settings.backups_dir / next(p.name for p in settings.backups_dir.iterdir()), key)
        assert sign_in_rows(books.directory) == sign_in_rows(old)
        old.dispose()
        assert len(list(settings.backups_dir.glob("pre-books-steward-*.db"))) == 1
    finally:
        books.dispose()


def test_a_wrong_key_refuses_to_start_and_names_the_file(settings):
    make_pre_books_vault(settings)
    settings.key_path.write_text("cd" * 32 + "\n")
    with pytest.raises(DirectoryUnavailable, match="steward.db"):
        open_books(settings)
    assert not settings.directory_path.exists()


def test_a_book_whose_file_is_missing_is_unavailable_and_logged(settings):
    ensure_key(settings.key_path)
    books = open_books(settings)
    with Session(books.directory) as s:
        s.add(Book(slug="gone", name="Gone", kind="parent", owner_names="[]", file="books/gone/book.db",
                   key_scheme="derived", created_at=bootstrap.utc_now()))
        s.commit()
    books.upgrade_all()
    gone = books.book("gone")
    assert books.unavailable[gone.id] == "The book's file is missing."
    with Session(books.directory) as s:
        assert s.scalar(select(DirectoryEvent.message).where(DirectoryEvent.book_id == gone.id)) == \
            "Book gone can't be opened: The book's file is missing."
    assert books.engine_for(books.book("ours")) is not None   # the others carry on
    books.dispose()


def test_engines_are_cached_by_book_id(settings):
    ensure_key(settings.key_path)
    books = open_books(settings)
    ours = books.book("ours")
    assert books.engine_for(ours) is books.engine_for(ours)
    assert books.plan_cache(ours.id) is books.plan_cache(ours.id)
    assert books.sync_lock(ours.id) is books.sync_lock(ours.id)
    books.close(ours.id)
    assert books.engine_for(ours) is not None
    books.dispose()


def test_registry_is_constructed_without_touching_the_disk(settings):
    ensure_key(settings.key_path)
    BookRegistry(settings)
    assert not settings.directory_path.exists() and not settings.db_path.exists()


def test_the_move_logs_one_plain_line_with_the_count_and_the_backup_name(settings, caplog):
    import logging
    make_pre_books_vault(settings)
    caplog.set_level(logging.INFO)
    books = open_books(settings)
    books.dispose()
    [backup] = settings.backups_dir.glob("pre-books-steward-*.db")
    lines = [r.getMessage() for r in caplog.records if "directory.db" in r.getMessage()]
    assert lines == [f"Moved sign-in for 2 people to directory.db; backup {backup.name}"]
    assert "jr@example.com" not in caplog.text and "Sam" not in caplog.text


def _take_backup(settings):
    key = make_pre_books_vault(settings)
    backup = bootstrap.backup_before_books(settings, key)
    return key, backup


def test_a_newer_wal_file_means_the_backup_is_not_reused(settings):
    key, backup = _take_backup(settings)
    dest = backup.parent
    assert bootstrap._reusable_backup(settings, dest, key) == backup
    wal = settings.db_path.with_name(settings.db_path.name + "-wal")
    wal.write_bytes(b"")
    later = backup.stat().st_mtime + 100
    os.utime(wal, (later, later))
    assert bootstrap._reusable_backup(settings, dest, key) is None


def test_a_backup_that_does_not_open_is_not_reused(settings):
    key, backup = _take_backup(settings)
    backup.write_bytes(b"not a database" * 100)
    os.utime(backup, (backup.stat().st_mtime + 100,) * 2)
    assert bootstrap._reusable_backup(settings, backup.parent, key) is None


def test_checking_a_backup_does_not_touch_it(settings):
    key, backup = _take_backup(settings)
    before = backup.stat().st_mtime_ns
    names = sorted(p.name for p in backup.parent.iterdir())
    assert bootstrap._reusable_backup(settings, backup.parent, key) == backup
    assert backup.stat().st_mtime_ns == before
    assert sorted(p.name for p in backup.parent.iterdir()) == names      # no -wal or -shm left beside it


def test_a_reused_backup_still_checks_the_key_against_the_live_file(settings):
    key, backup = _take_backup(settings)
    older = backup.with_name("pre-books-steward-20200101-000000.db")   # not the name a restart in this second would take
    backup.rename(older)
    backup = older
    old = backup.stat().st_mtime - 100
    settings.db_path.unlink()
    other = make_engine(settings.db_path, "ab" * 32)
    with other.begin() as c:
        c.execute(text("CREATE TABLE t (id integer)"))
    other.dispose()
    os.utime(settings.db_path, (old, old))
    assert bootstrap._reusable_backup(settings, backup.parent, key) == backup
    with pytest.raises(DirectoryUnavailable):
        bootstrap.backup_before_books(settings, key)


def test_a_restart_reuses_the_backup_when_the_live_file_is_untouched(settings):
    key, backup = _take_backup(settings)
    older = backup.with_name("pre-books-steward-20200101-000000.db")   # not the name a restart in this second would take
    backup.rename(older)
    then = older.stat().st_mtime
    os.utime(settings.db_path, (then - 100, then - 100))
    names = sorted(p.name for p in older.parent.iterdir())
    assert bootstrap.backup_before_books(settings, key) == older
    assert sorted(p.name for p in older.parent.iterdir()) == names      # exactly one backup
    assert not settings.db_path.with_name(settings.db_path.name + "-wal").exists()
