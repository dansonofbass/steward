from datetime import datetime, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from steward.db.directory_models import Book, DirectoryBase, Membership, User
from steward.db.engine import make_engine
from steward.db.keys import directory_key, ensure_key
from steward.db.migrate import run_directory_migrations

NOW = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)


@pytest.fixture
def deng(settings):
    eng = make_engine(settings.directory_path, directory_key(ensure_key(settings.key_path)))
    run_directory_migrations(eng)
    yield eng
    eng.dispose()


def test_paths(settings):
    assert settings.directory_path == settings.data_dir / "directory.db"
    assert settings.backups_dir == settings.data_dir / "backups"
    assert settings.books_dir == settings.data_dir / "books"


def test_directory_tables(deng):
    assert {"user", "passkey", "password_reset", "session", "book", "membership", "membership_change",
            "directory_event", "directory_meta", "advisor_grant", "setup_link", "app_setting"} <= set(inspect(deng).get_table_names())


def test_directory_migration_matches_models(deng):
    with deng.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), DirectoryBase.metadata) == []


def test_kind_and_role_are_checked(deng):
    with Session(deng) as s:
        s.add(Book(slug="x", name="X", kind="other", owner_names="[]", file="books/x/book.db", key_scheme="derived",
                   created_at=NOW))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
        u = User(username="jr", email="jr@x.com", display_name="JR", password_hash="x", created_at=NOW)
        b = Book(slug="ours", name="Ours", kind="household", owner_names="[]", file="steward.db", key_scheme="raw",
                 created_at=NOW)
        s.add_all([u, b]); s.flush()
        s.add(Membership(user_id=u.id, book_id=b.id, role="owner", created_at=NOW))
        with pytest.raises(IntegrityError):
            s.flush()


def _old_directory(settings):
    from alembic import command
    from sqlalchemy import text
    from steward.db.migrate import _directory_config
    eng = make_engine(settings.directory_path, directory_key(ensure_key(settings.key_path)))
    command.upgrade(_directory_config(eng), "d0002")
    return eng, text, command, _directory_config


def test_the_placeholder_backfill_marks_only_real_placeholders(settings):
    eng, text, command, config = _old_directory(settings)
    try:
        stamp, future = "2026-01-01 00:00:00.000000", "2999-01-01 00:00:00.000000"
        with eng.begin() as c:
            c.execute(text("INSERT INTO book (id, slug, name, kind, owner_names, file, key_scheme, created_at) "
                           "VALUES (1, 'b', 'B', 'parent', '[]', 'x', 'derived', :t)"), {"t": stamp})
            for uid, name in ((1, "invited-0123456789ab"), (2, "invited-0123456789ac"), (3, "invited-0123456789ad"),
                              (4, "invited-0123456789ae"), (5, "ordinary")):
                c.execute(text("INSERT INTO user (id, username, email, display_name, password_hash, created_at, "
                               "failed_logins) VALUES (:i, :u, :e, 'N', 'x', :t, 0)"),
                          {"i": uid, "u": name, "e": f"{name}@example.com", "t": stamp})
            # 1: genuine, open invite. 2: signed in. 3: has a membership. 4: no open invite or link.
            c.execute(text("INSERT INTO pending_invite (book_id, user_id, role, invited_by, token_hash, created_at, "
                           "expires_at) VALUES (1, 1, 'viewer', 5, 'h1', :t, :f)"), {"t": stamp, "f": future})
            for uid in (2, 3):
                c.execute(text("INSERT INTO pending_invite (book_id, user_id, role, invited_by, token_hash, created_at, "
                               "expires_at) VALUES (1, :i, 'viewer', 5, :h, :t, :f)"),
                          {"i": uid, "h": f"h{uid}", "t": stamp, "f": future})
            c.execute(text("INSERT INTO session (user_id, token_hash, device_label, created_at, last_seen_at, "
                           "expires_at) VALUES (2, 's', 'd', :t, :t, :f)"), {"t": stamp, "f": future})
            c.execute(text("INSERT INTO membership (user_id, book_id, role, created_at) VALUES (3, 1, 'viewer', :t)"),
                      {"t": stamp})
        command.upgrade(config(eng), "head")
        with eng.connect() as c:
            marked = {r[0]: r[1] for r in c.execute(text("SELECT id, is_placeholder FROM user"))}
        assert marked == {1: 1, 2: 0, 3: 0, 4: 0, 5: 0}
    finally:
        eng.dispose()


def test_d0003_downgrade_drops_the_column_and_keeps_the_people(settings):
    eng, text, command, config = _old_directory(settings)
    try:
        with eng.begin() as c:
            c.execute(text("INSERT INTO user (id, username, email, display_name, password_hash, created_at, "
                           "failed_logins) VALUES (1, 'jr', 'jr@x.com', 'JR', 'x', '2026-01-01 00:00:00.000000', 0)"))
        command.upgrade(config(eng), "head")
        command.downgrade(config(eng), "d0002")
        assert "is_placeholder" not in {c["name"] for c in inspect(eng).get_columns("user")}
        with eng.connect() as c:
            assert c.execute(text("SELECT username FROM user")).scalar() == "jr"
    finally:
        eng.dispose()


def test_d0004_downgrade_drops_advisor_grant(settings):
    eng, text, command, cfg = _old_directory(settings)
    command.upgrade(cfg(eng), "d0004")
    assert "advisor_grant" in inspect(eng).get_table_names()
    command.downgrade(cfg(eng), "d0003")
    assert "advisor_grant" not in inspect(eng).get_table_names()
    eng.dispose()


def test_d0005_adds_the_switches_and_growth_seen_unchosen_and_its_downgrade_keeps_the_people(settings):
    eng, text, command, config = _old_directory(settings)
    try:
        command.upgrade(config(eng), "d0004")
        stamp = "2026-01-01 00:00:00.000000"
        with eng.begin() as c:
            c.execute(text("INSERT INTO book (id, slug, name, kind, owner_names, file, key_scheme, created_at) "
                           "VALUES (1, 'ours', 'Ours', 'household', '[]', 'x', 'derived', :t)"), {"t": stamp})
            c.execute(text("INSERT INTO user (id, username, email, display_name, password_hash, created_at, failed_logins, "
                           "is_placeholder) VALUES (1, 'jr', 'jr@x.com', 'JR', 'x', :t, 0, 0)"), {"t": stamp})
            c.execute(text("INSERT INTO membership (user_id, book_id, role, created_at) VALUES (1, 1, 'manager', :t)"),
                      {"t": stamp})
        command.upgrade(config(eng), "d0005")
        with eng.connect() as c:
            assert tuple(c.execute(text("SELECT celebrations, sound FROM user")).one()) == (None, None)   # never chosen
            assert c.execute(text("SELECT growth_seen FROM membership")).scalar() is None
        command.downgrade(config(eng), "d0004")
        assert not {"celebrations", "sound"} & {col["name"] for col in inspect(eng).get_columns("user")}
        assert "growth_seen" not in {col["name"] for col in inspect(eng).get_columns("membership")}
        with eng.connect() as c:
            assert c.execute(text("SELECT username FROM user")).scalar() == "jr"
            assert c.execute(text("SELECT role FROM membership")).scalar() == "manager"
    finally:
        eng.dispose()


def test_d0006_adds_setup_link_and_its_downgrade_keeps_the_people(settings):
    eng, text, command, config = _old_directory(settings)
    try:
        command.upgrade(config(eng), "d0005")
        stamp = "2026-01-01 00:00:00.000000"
        with eng.begin() as c:
            c.execute(text("INSERT INTO user (id, username, email, display_name, password_hash, created_at, failed_logins, "
                           "is_placeholder) VALUES (1, 'jr', 'jr@x.com', 'JR', 'x', :t, 0, 0)"), {"t": stamp})
        command.upgrade(config(eng), "d0006")
        assert {col["name"] for col in inspect(eng).get_columns("setup_link")} == {
            "id", "token_hash", "created_at", "expires_at", "used_at"}
        command.downgrade(config(eng), "d0005")
        assert "setup_link" not in inspect(eng).get_table_names()
        with eng.connect() as c:
            assert c.execute(text("SELECT username FROM user")).scalar() == "jr"
    finally:
        eng.dispose()


def test_d0007_adds_app_setting_and_its_downgrade_keeps_the_people(settings):
    eng, text, command, config = _old_directory(settings)
    try:
        command.upgrade(config(eng), "d0006")
        with eng.begin() as c:
            c.execute(text("INSERT INTO user (id, username, email, display_name, password_hash, created_at, failed_logins, "
                           "is_placeholder) VALUES (1, 'jr', 'jr@x.com', 'JR', 'x', '2026-01-01 00:00:00.000000', 0, 0)"))
        command.upgrade(config(eng), "d0007")
        assert {col["name"] for col in inspect(eng).get_columns("app_setting")} == {
            "key", "value", "sealed", "updated_at", "updated_by"}
        with pytest.raises(IntegrityError):          # exactly one of value and sealed
            with eng.begin() as c:
                c.execute(text("INSERT INTO app_setting (key, value, sealed, updated_at) "
                               "VALUES ('email.host', NULL, NULL, '2026-01-01 00:00:00.000000')"))
        command.downgrade(config(eng), "d0006")
        assert "app_setting" not in inspect(eng).get_table_names()
        with eng.connect() as c:
            assert c.execute(text("SELECT username FROM user")).scalar() == "jr"
    finally:
        eng.dispose()


def test_d0008_marks_every_membership_welcomed_and_adds_sample_of(settings):
    eng, text, command, config = _old_directory(settings)
    try:
        command.upgrade(config(eng), "d0007")
        with eng.begin() as c:
            c.execute(text("INSERT INTO user (id, username, email, display_name, password_hash, created_at, failed_logins, "
                           "is_placeholder) VALUES (1, 'jr', 'jr@x.com', 'JR', 'x', '2026-01-01 00:00:00.000000', 0, 0)"))
            c.execute(text("INSERT INTO book (id, slug, name, kind, owner_names, file, key_scheme, created_at) VALUES "
                           "(1, 'ours', 'Ours', 'household', '[]', 'steward.db', 'raw', '2026-01-01 00:00:00.000000')"))
            c.execute(text("INSERT INTO membership (user_id, book_id, role, created_at) "
                           "VALUES (1, 1, 'manager', '2026-02-03 04:05:06.000000')"))
        command.upgrade(config(eng), "d0008")
        with eng.connect() as c:
            assert c.execute(text("SELECT welcome_seen_at FROM membership")).scalar() == "2026-02-03 04:05:06.000000"
            assert c.execute(text("SELECT sample_of FROM book")).scalar() is None
        command.downgrade(config(eng), "d0007")
        assert "welcome_seen_at" not in {col["name"] for col in inspect(eng).get_columns("membership")}
        assert "sample_of" not in {col["name"] for col in inspect(eng).get_columns("book")}
        with eng.connect() as c:
            assert c.execute(text("SELECT role FROM membership")).scalar() == "manager"
    finally:
        eng.dispose()
