import pytest
import sqlalchemy.exc
from sqlalchemy import text

from steward.db.keys import ensure_key, read_key, KeyMissing
from steward.db.engine import make_engine, check_key, WrongKey


def test_ensure_key_creates_0600_hex(tmp_path):
    p = tmp_path / "steward.key"
    k = ensure_key(p)
    assert len(k) == 64 and int(k, 16) >= 0
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert ensure_key(p) == k  # idempotent


def test_read_key_missing(tmp_path):
    with pytest.raises(KeyMissing):
        read_key(tmp_path / "nope.key")


def test_wrong_key_cannot_open(tmp_path):
    db = tmp_path / "s.db"
    good = ensure_key(tmp_path / "a.key")
    eng = make_engine(db, good)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t(x INTEGER)"))
        c.execute(text("INSERT INTO t VALUES (1)"))
    eng.dispose()

    bad = make_engine(db, "00" * 32)
    with pytest.raises(WrongKey):
        check_key(bad)

    again = make_engine(db, good)
    check_key(again)
    with again.connect() as c:
        assert c.execute(text("SELECT x FROM t")).scalar() == 1


def test_file_is_not_plaintext(tmp_path):
    db = tmp_path / "s.db"
    eng = make_engine(db, ensure_key(tmp_path / "a.key"))
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t(x TEXT)"))
        c.execute(text("INSERT INTO t VALUES ('needle-needle-needle')"))
    eng.dispose()
    assert b"needle" not in db.read_bytes()
    assert not db.read_bytes().startswith(b"SQLite format 3")


def test_driver_errors_are_wrapped_by_sqlalchemy(tmp_path):
    eng = make_engine(tmp_path / "s.db", ensure_key(tmp_path / "a.key"))
    with eng.begin() as c:
        c.execute(text("CREATE TABLE u(x TEXT UNIQUE)"))
        c.execute(text("INSERT INTO u VALUES ('a')"))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        with eng.begin() as c:
            c.execute(text("INSERT INTO u VALUES ('a')"))


def test_read_key_rejects_non_hex_and_prefixed(tmp_path):
    p = tmp_path / "k"
    p.write_text("zz" * 32)
    with pytest.raises(KeyMissing, match="not 64 hex characters"):
        read_key(p)
    p.write_text("0x" + "ab" * 31)
    with pytest.raises(KeyMissing, match="not 64 hex characters"):
        read_key(p)


def test_a_read_session_writes_only_through_begin_write_and_leaves_its_connection_writable(tmp_path):
    """A book's GET session reads on a plain BEGIN, with query_only on in tests; begin_write moves it to a BEGIN
    IMMEDIATE transaction. The pooled connection it used must not stay query_only for the next session."""
    from sqlalchemy.orm import Session

    from steward.db.engine import WRITE, begin_write
    eng = make_engine(tmp_path / "s.db", ensure_key(tmp_path / "a.key"))
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t(x INTEGER)"))
    with Session(eng.execution_options(read=True, query_only=True)) as s:
        assert s.execute(text("SELECT count(*) FROM t")).scalar() == 0
        with pytest.raises(sqlalchemy.exc.OperationalError, match="readonly"):
            s.execute(text("INSERT INTO t VALUES (1)"))
        s.rollback()
        begin_write(s)
        assert s.connection().get_execution_options()["immediate"] is True
        s.execute(text("INSERT INTO t VALUES (2)"))
        s.commit()
        assert s.connection().get_execution_options()["read"] is True      # the next transaction reads again
    for opts in ({}, WRITE, {"immediate": True}):        # the scheduler's sessions, a POST's, a sync's
        with Session(eng.execution_options(**opts)) as s:
            s.execute(text("INSERT INTO t VALUES (3)"))
            s.commit()
    with Session(eng.execution_options(immediate=True)) as s:
        begin_write(s)                                   # not a read session: nothing to do
        assert s.execute(text("SELECT count(*) FROM t")).scalar() == 4
    eng.dispose()


def test_a_backup_after_a_read_only_session_still_writes_its_copy(tmp_path):
    """A test GET leaves its pooled connection with PRAGMA query_only on; a backup takes a raw connection, which skips
    the begin hook that resets it, so the backup must make it writable itself (VACUUM INTO writes)."""
    from sqlalchemy.orm import Session
    from steward.services.backup import backup_engine
    eng = make_engine(tmp_path / "s.db", ensure_key(tmp_path / "a.key"))
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t (x INTEGER)")
    with Session(eng.execution_options(read=True, query_only=True)) as s:
        s.execute(text("SELECT count(*) FROM t")).scalar()
    out = tmp_path / "copies"
    out.mkdir()
    assert backup_engine(eng, out, "s", "20261026-000000").exists()


def test_every_pooled_connection_enforces_foreign_keys_after_an_upgrade(tmp_path):
    """Start-up runs Alembic on the engine the book then serves from. On a book already at head Alembic's read of the
    version table left a transaction open, so the closing PRAGMA foreign_keys = ON was ignored and that pooled
    connection served requests without foreign keys (and every test with them off: it is the first one handed out)."""
    from steward.db.migrate import run_migrations
    eng = make_engine(tmp_path / "book.db", ensure_key(tmp_path / "k.key"))
    run_migrations(eng)                 # a new book: every migration runs
    run_migrations(eng)                 # already at head, as at every restart
    conns = [eng.connect() for _ in range(6)]
    try:
        assert [c.execute(text("PRAGMA foreign_keys")).scalar() for c in conns] == [1] * 6
    finally:
        for c in conns:
            c.close()
        eng.dispose()
