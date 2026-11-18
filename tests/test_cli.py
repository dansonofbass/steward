from steward import clock
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from steward.auth import sessions, users
from steward.cli import app
from steward.db.engine import make_engine
from steward.db.keys import read_key

runner = CliRunner()


def test_init_key_migrate_create_user_reset(settings):
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert settings.key_path.exists()
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    r = runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"])
    assert r.exit_code == 0 and "Created jr" in r.output
    r = runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"])
    assert r.exit_code == 1 and "already exists" in r.output

    from steward.books.registry import open_books
    books = open_books(settings)
    engine = books.directory
    now = clock.now()
    with Session(engine) as db:
        token, _ = sessions.create_session(db, users.find_user(db, "jr"), "laptop", now, 30)
        assert sessions.resolve(db, token, now) is not None

    r = runner.invoke(app, ["reset-password", "jr", "--password", "new-pass-word-9"])
    assert r.exit_code == 0 and "Password updated" in r.output

    with Session(engine) as db:
        assert sessions.resolve(db, token, clock.now()) is None
    books.dispose()


def test_reset_password_unknown_user(settings):
    runner.invoke(app, ["init-key"])
    runner.invoke(app, ["migrate"])
    r = runner.invoke(app, ["reset-password", "nobody", "--password", "new-pass-word-9"])
    assert r.exit_code == 1 and "No user nobody" in r.output


def test_migrate_without_key_fails_clearly(settings):
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 1 and "steward init-key" in r.output


def test_wrong_key_is_reported_in_plain_words(settings):
    runner.invoke(app, ["init-key"])
    runner.invoke(app, ["migrate"])
    settings.key_path.write_text("ab" * 32)
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 1 and "doesn't open" in r.output


def test_no_args_shows_help():
    r = runner.invoke(app, [])
    assert "init-key" in r.output and "serve" in r.output


def test_seed_demo_refuses_then_force_adds(settings):
    from sqlalchemy import func, select
    from steward.db.models import Transaction
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert runner.invoke(app, ["migrate"]).exit_code == 0

    def count():
        from steward.books.registry import open_books
        books = open_books(settings)
        with Session(books.engine_for(books.book("ours"))) as db:
            n = db.scalar(select(func.count()).select_from(Transaction))
        books.dispose()
        return n

    assert runner.invoke(app, ["seed-demo", "--years", "1"]).exit_code == 0
    first = count()
    assert first > 0
    r = runner.invoke(app, ["seed-demo", "--years", "1"])
    assert r.exit_code == 1 and "already has transactions" in r.output
    assert count() == first
    r = runner.invoke(app, ["seed-demo", "--years", "1", "--force"])
    assert r.exit_code == 0, r.output
    assert count() > first


def test_seed_demo_marks_its_finished_profile_seen(settings):
    """Issue #30: the demo's profile is complete, so its people land on Home, not on Profile's first visit."""
    from steward.books.registry import open_books
    from steward.db.directory_models import User
    from steward.demo import DEMO_LOGINS
    from steward.services.profile import FINISHED, marks_out, section_states
    from steward import clock
    from sqlalchemy import select
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    assert runner.invoke(app, ["seed-demo", "--years", "1"]).exit_code == 0
    books = open_books(settings)
    try:
        with Session(books.directory) as ddb:
            ids = [ddb.scalar(select(User.id).where(User.username == u)) for u, *_ in DEMO_LOGINS]
        with Session(books.engine_for(books.book("ours"))) as db:
            assert all(s.status in FINISHED for s in section_states(db))
            assert all(marks_out(db, uid, clock.now())["seen"] for uid in ids)
    finally:
        books.dispose()


def test_serve_without_key_explains_and_never_binds(settings, monkeypatch):
    import uvicorn

    def boom(*a, **k):
        raise AssertionError("uvicorn.run must not be reached")

    monkeypatch.setattr(uvicorn, "run", boom)
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 1 and "steward init-key" in r.output


def _prepared(settings):
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert runner.invoke(app, ["migrate"]).exit_code == 0


def test_serve_says_whether_backups_are_on(settings, monkeypatch):
    import uvicorn
    _prepared(settings)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 0 and f"Backups: daily at 03:00 to {settings.backups_dir}" in r.output.splitlines()
    monkeypatch.setenv("STEWARD_BACKUP_AT", "")
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 0 and "Backups: off" in r.output.splitlines()


def test_serve_prints_the_effective_zone_and_backup_time(settings, monkeypatch):
    import uvicorn
    from steward.app_settings import AppSettings
    from steward.books.registry import BookRegistry
    from tests.test_app_settings import BY
    _prepared(settings)
    monkeypatch.delenv("STEWARD_TIMEZONE")
    from steward.settings import Settings
    books = BookRegistry(Settings(_env_file=None))
    AppSettings(books.settings, books.directory, books.master).save(
        "general", {"timezone": "America/Chicago"}, **BY)
    AppSettings(books.settings, books.directory, books.master).save("backups", {"at": "04:30"}, **BY)
    books.dispose()
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    out = runner.invoke(app, ["serve"]).output.splitlines()
    assert "Time zone: America/Chicago" in out and f"Backups: daily at 04:30 to {settings.backups_dir}" in out


def test_seed_demo_refuses_in_prod_without_override(settings, monkeypatch):
    from sqlalchemy import func, select
    from steward.books.registry import open_books
    from steward.db.directory_models import User
    _prepared(settings)
    monkeypatch.setenv("STEWARD_ENV", "prod")
    monkeypatch.delenv("STEWARD_ALLOW_DEMO", raising=False)
    r = runner.invoke(app, ["seed-demo", "--years", "1"])
    assert r.exit_code == 1
    assert ("Refusing to seed demo data into a production vault. "
            "Set STEWARD_ALLOW_DEMO=1 on a throwaway database to override.") in r.output.replace("\n", " ")
    books = open_books(settings)
    with Session(books.directory) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
    books.dispose()
    monkeypatch.setenv("STEWARD_ALLOW_DEMO", "1")
    assert runner.invoke(app, ["seed-demo", "--years", "1"]).exit_code == 0


def test_commands_need_a_migrated_database(settings, monkeypatch):
    import uvicorn

    def boom(*a, **k):
        raise AssertionError("uvicorn.run must not be reached")

    monkeypatch.setattr(uvicorn, "run", boom)
    runner.invoke(app, ["init-key"])
    for args in (["serve"], ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"],
                 ["reset-password", "jr", "--password", "pw-one-two-3"], ["seed-demo"], ["backup"]):
        r = runner.invoke(app, args)
        assert r.exit_code == 1 and "No database at" in r.output and "`steward migrate` first." in r.output, args
    assert not settings.db_path.exists()


def test_malformed_key_is_reported_without_traceback(settings):
    settings.key_path.write_text("zz" * 32)
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 1 and "is not 64 hex characters." in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_backup_writes_a_copy_per_book_that_opens_with_its_key(settings, monkeypatch, tmp_path):
    from steward.books.registry import open_books
    from steward.db.engine import check_key
    from steward.services import backup as bk
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"]).exit_code == 0
    dest = tmp_path / "bk"
    monkeypatch.setattr(bk, "_stamp", lambda: "20260101-000001")
    r = runner.invoke(app, ["backup", "--dir", str(dest)])
    assert r.exit_code == 0, r.output
    lines = r.output.split()
    assert [Path(x).name for x in lines] == ["steward-directory-20260101-000001.db", "steward-ours-20260101-000001.db"]
    books = open_books(settings)
    eng = make_engine(dest / "steward-ours-20260101-000001.db", books.key_for(books.book("ours")))
    check_key(eng)
    eng.dispose()
    books.dispose()


def test_book_create_and_list(settings):
    _prepared(settings)
    runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"])
    r = runner.invoke(app, ["book", "create", "Mom (Robin's)", "--kind", "parent", "--owner", "Margaret",
                            "--owner", "Joint", "--manager", "jr"])
    assert r.exit_code == 0 and "Created book mom-robins (Mom (Robin's))" in r.output, r.output
    assert runner.invoke(app, ["book", "create", "X", "--manager", "nobody"]).output.strip() == "No user nobody."
    bad = runner.invoke(app, ["book", "create", "X", "--kind", "parent", "--manager", "jr"])
    assert bad.exit_code == 1 and "owner names" in bad.output
    second = runner.invoke(app, ["book", "create", "Ours too", "--kind", "household", "--manager", "jr"])
    assert second.exit_code == 1 and "Steward has one household book, made at setup." in second.output
    out = runner.invoke(app, ["book", "list"]).output
    assert "ours\thousehold\tOurs" in out and "mom-robins\tparent\tMom (Robin's)" in out


def test_backup_rejects_quote_in_dir(settings, tmp_path):
    _prepared(settings)
    r = runner.invoke(app, ["backup", "--dir", str(tmp_path / "it's")])
    assert r.exit_code == 1 and "absolute path without quote" in r.output


def test_restore_check_passes_on_a_fresh_backup_and_fails_without_one(settings, monkeypatch, tmp_path):
    from steward.services import backup as bk
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"]).exit_code == 0
    dest = tmp_path / "bk"
    r = runner.invoke(app, ["restore-check", "--dir", str(dest)])
    assert r.exit_code == 1 and "No backup in" in r.output
    monkeypatch.setattr(bk, "_stamp", lambda: datetime.now().strftime("%Y%m%d-%H%M%S"))
    assert runner.invoke(app, ["backup", "--dir", str(dest)]).exit_code == 0
    r = runner.invoke(app, ["restore-check", "--dir", str(dest)])
    assert r.exit_code == 0, r.output
    assert "ours: ok (" in r.output and "restores: 1 book, 0 files." in r.output


def test_restore_check_rejects_a_bad_max_age(settings):
    _prepared(settings)
    r = runner.invoke(app, ["restore-check", "--max-age-hours", "0"])
    assert r.exit_code == 2 and "--max-age-hours" in r.output and "No such command" not in r.output


def _live_bytes(settings):
    """Every file under the data folder but backups/, -wal and -shm, by its bytes. Each command disposes its engines,
    and SQLite checkpoints the WAL into the main file and deletes it when the last connection closes, so the main
    files' bytes are a stable picture of what's on disk."""
    root = settings.data_dir
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and not p.is_relative_to(settings.backups_dir) and not p.name.endswith(("-wal", "-shm"))}


def _backed_up_with_a_pending_backfill(settings, monkeypatch):
    """A directory, ours and a parent book, last night's backup in data/backups, then an account in the parent book
    with no inventory item, which start-up's backfill would add (a write a restore-check must never make)."""
    from steward.books.registry import open_books
    from steward.services import backup as bk
    from tests.factories import make_account
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"]).exit_code == 0
    assert runner.invoke(app, ["book", "create", "Margaret Ellis", "--kind", "parent", "--owner", "Margaret",
                               "--manager", "jr"]).exit_code == 0
    monkeypatch.setattr(bk, "_stamp", lambda: datetime.now().strftime("%Y%m%d-%H%M%S"))
    assert runner.invoke(app, ["backup"]).exit_code == 0
    books = open_books(settings)
    with Session(books.engine_for(books.book("margaret-ellis"))) as s:
        make_account(s, "Savings")
        s.commit()
    books.dispose()


def test_restore_check_leaves_the_live_books_and_directory_as_they_were(settings, monkeypatch):
    _backed_up_with_a_pending_backfill(settings, monkeypatch)
    before = _live_bytes(settings)
    assert {Path("directory.db"), Path("steward.db"), Path("books/margaret-ellis/book.db")} <= set(before)
    r = runner.invoke(app, ["restore-check"])
    assert r.exit_code == 0, r.output
    assert "margaret-ellis: ok (" in r.output and "restores: 2 books, 0 files." in r.output
    assert _live_bytes(settings) == before


def test_restore_check_never_prepares_the_books(settings, monkeypatch):
    from steward.books.registry import BookRegistry
    _backed_up_with_a_pending_backfill(settings, monkeypatch)

    def boom(self):
        raise AssertionError("restore-check must not migrate or backfill the live books")

    monkeypatch.setattr(BookRegistry, "prepare", boom)
    r = runner.invoke(app, ["restore-check"])
    assert r.exit_code == 0, r.output
    assert r.output.rstrip().endswith("restores: 2 books, 0 files.")


def test_restore_check_says_plainly_when_the_key_is_wrong_or_missing(settings):
    _prepared(settings)
    settings.key_path.write_text("ab" * 32)
    r = runner.invoke(app, ["restore-check"])
    assert r.exit_code == 1, r.output
    assert r.output.strip() == f"The key at {settings.key_path} doesn't open {settings.directory_path}.", r.output
    settings.key_path.unlink()
    r = runner.invoke(app, ["restore-check"])
    assert r.exit_code == 1 and "steward init-key" in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_migrate_warns_when_this_years_limits_are_missing(settings, monkeypatch):
    monkeypatch.setattr("steward.services.limits.have_year", lambda year: False)
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 0 and "has no contribution limits for" in r.output


def test_serve_trusts_the_proxies_forwarded_headers(settings, monkeypatch):
    """tailscale serve and steward-proxy connect from Docker's private addresses; uvicorn believes their
    X-Forwarded-For and X-Forwarded-Proto only from STEWARD_TRUSTED_PROXIES (tests/test_proxy_trust.py)."""
    import uvicorn
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda asgi, **kw: seen.update(kw))
    _prepared(settings)
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 0, r.output
    assert seen["proxy_headers"] is True
    assert seen["forwarded_allow_ips"] == "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def test_serve_says_the_time_zone_before_it_starts(settings, monkeypatch):
    import uvicorn
    _prepared(settings)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 0 and "Time zone: America/Los_Angeles" in r.output.splitlines()


def test_a_bad_time_zone_stops_a_command_with_one_line(settings, monkeypatch):
    monkeypatch.setenv("STEWARD_TIMEZONE", "Pacific")
    r = runner.invoke(app, ["book", "list"])
    assert r.exit_code == 1 and r.output.startswith("STEWARD_TIMEZONE must be a time zone name")


def test_serve_in_prod_refuses_a_vault_that_keeps_a_demo_login(settings, monkeypatch):
    import uvicorn

    def boom(*a, **k):
        raise AssertionError("uvicorn.run must not be reached")

    monkeypatch.setattr(uvicorn, "run", boom)
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "spouse", "s@x.com", "Sam", "--password", "pw-demo-spouse-2026"]).exit_code == 0
    monkeypatch.setenv("STEWARD_ENV", "prod")
    r = runner.invoke(app, ["serve"])
    said = r.output.replace("\n", " ")
    assert r.exit_code == 1
    assert "spouse still signs in with the demo password, and STEWARD_ENV is prod." in said
    assert "`steward reset-password spouse`" in said and "pw-demo" not in r.output


def test_serve_and_seed_demo_refuse_an_unknown_steward_env_in_one_plain_line(settings, monkeypatch):
    """Issue #9: STEWARD_ENV=production used to start with the demo sign-ins in place. Now nothing starts."""
    import uvicorn
    from steward.settings import ENV_RULE

    def boom(*a, **k):
        raise AssertionError("serve must not start")
    monkeypatch.setattr(uvicorn, "run", boom)
    monkeypatch.setenv("STEWARD_ENV", "production")
    monkeypatch.delenv("STEWARD_ALLOW_DEMO", raising=False)
    for command in (["serve"], ["seed-demo", "--years", "1"]):
        r = runner.invoke(app, command)
        assert r.exit_code == 1 and r.output.replace("\n", " ").strip() == ENV_RULE, (command, r.output)


def test_serve_in_prod_refuses_a_vault_an_older_demo_seeded(settings, monkeypatch):
    """The demo's Person 1 was jr before it was alex (RETIRED_DEMO_LOGINS): a vault seeded then is still refused."""
    import uvicorn

    def boom(*a, **k):
        raise AssertionError("uvicorn.run must not be reached")

    monkeypatch.setattr(uvicorn, "run", boom)
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-demo-jr-2026"]).exit_code == 0
    monkeypatch.setenv("STEWARD_ENV", "prod")
    r = runner.invoke(app, ["serve"])
    said = r.output.replace("\n", " ")
    assert r.exit_code == 1
    assert "jr still signs in with the demo password, and STEWARD_ENV is prod." in said
    assert "`steward reset-password jr`" in said and "pw-demo" not in r.output


def test_serve_in_prod_starts_for_a_real_account_with_a_retired_demo_username(settings, monkeypatch):
    """Only the password refuses: a real jr with its own password starts as usual."""
    import uvicorn
    ran = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.append(k))
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"]).exit_code == 0
    monkeypatch.setenv("STEWARD_ENV", "prod")
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 0, r.output
    assert ran


def test_seed_people_never_makes_a_retired_demo_login(ddb, ours):
    from steward.auth import users
    from steward.demo import RETIRED_DEMO_LOGINS, seed_people
    seed_people(ddb, ours.id)
    assert all(users.find_user(ddb, username) is None for username, _pw in RETIRED_DEMO_LOGINS)


def test_serve_in_prod_starts_when_no_demo_login_is_left(settings, monkeypatch):
    import uvicorn
    ran = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: ran.append(k))
    _prepared(settings)
    # A demo username whose password was reset: the guard checks it and lets it start.
    assert runner.invoke(app, ["create-user", "alex", "alex@x.com", "Alex", "--password", "pw-one-two-3"]).exit_code == 0
    monkeypatch.setenv("STEWARD_ENV", "prod")
    r = runner.invoke(app, ["serve"])
    assert r.exit_code == 0, r.output
    assert ran                                       # two Argon2 checks, then uvicorn


def test_serve_under_test_skips_the_check_for_the_e2e_vault(settings, monkeypatch):
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    _prepared(settings)
    assert runner.invoke(app, ["create-user", "alex", "alex@x.com", "Alex", "--password", "pw-demo-alex-2026"]).exit_code == 0
    assert runner.invoke(app, ["serve"]).exit_code == 0


def test_the_demo_logins_are_the_ones_the_demo_seeds(ddb, ours):
    from steward.auth import users
    from steward.auth.demo_guard import demo_login_left
    from steward.auth.passwords import verify_password
    from steward.demo import DEMO_LOGINS, seed_people
    seed_people(ddb, ours.id)
    for username, email, name, password in DEMO_LOGINS:
        u = users.find_user(ddb, username)
        assert (u.email, u.display_name) == (email, name) and verify_password(u.password_hash, password)
    assert demo_login_left(ddb) == "alex"


def test_a_bad_ping_url_stops_a_command_with_one_line_that_never_shows_it(settings, monkeypatch):
    monkeypatch.setenv("STEWARD_BACKUP_PING_URL", "ftp://hc-ping.example/9f2c-secret")
    r = runner.invoke(app, ["book", "list"])
    assert r.exit_code == 1 and r.output.startswith("STEWARD_BACKUP_PING_URL must be")
    assert "9f2c-secret" not in r.output


def test_backup_refuses_a_folder_that_holds_the_key(settings):
    _prepared(settings)
    r = runner.invoke(app, ["backup", "--dir", str(settings.data_dir)])
    assert r.exit_code == 1 and "holds the encryption key" in r.output


def test_cli_output_is_plain_even_where_ci_forces_colour():
    """GitHub Actions sets GITHUB_ACTIONS, which makes Typer colour its output; conftest turns that off so the CLI
    tests read the same text everywhere."""
    import typer.rich_utils

    assert typer.rich_utils.FORCE_TERMINAL is False
    r = runner.invoke(app, ["restore-check", "--max-age-hours", "0"])
    assert "\x1b[" not in r.output
