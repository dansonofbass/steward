from pathlib import Path

import sqlcipher3
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool


class WrongKey(RuntimeError):
    pass


_QUERY_ONLY = "steward.query_only"
WRITE = {"immediate": True, "read": False, "query_only": False}


def make_engine(db_path: Path, key_hex: str) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def creator():
        conn = sqlcipher3.connect(str(db_path), check_same_thread=False, timeout=30)
        # Raw hex key: no KDF, no quoting problems.
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    engine = create_engine("sqlite://", module=sqlcipher3, creator=creator, poolclass=QueuePool,
                           pool_size=5, max_overflow=5, hide_parameters=True)

    # SQLAlchemy's documented pysqlite SAVEPOINT recipe: the driver must not begin transactions
    # on its own, or a SAVEPOINT opened before any write becomes the outer transaction and its
    # RELEASE commits it. We emit BEGIN ourselves.
    # A session that may write asks for BEGIN IMMEDIATE (immediate=True): it waits for the write lock up front, so a
    # read-then-write cannot fail at once with SQLITE_BUSY_SNAPSHOT when another writer commits in between. A book's
    # GET requests ask for a plain BEGIN (read=True): WAL lets them read their snapshot beside a writer instead of
    # queuing behind it. Tests add query_only=True to those, so a write in one is an error there (begin_write below).
    @event.listens_for(engine, "connect")
    def _no_driver_begin(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(conn):
        opts = conn.get_execution_options()
        query_only = bool(opts.get("query_only"))
        if conn.info.get(_QUERY_ONLY, False) != query_only:       # the pooled connection keeps the pragma; reset it
            conn.exec_driver_sql(f"PRAGMA query_only = {'ON' if query_only else 'OFF'}")
            conn.info[_QUERY_ONLY] = query_only
        conn.exec_driver_sql("BEGIN IMMEDIATE" if opts.get("immediate") else "BEGIN")

    return engine


def begin_write(db: Session) -> None:
    """For a write in a read session (a GET's): ends its read transaction, which has nothing to keep, and begins a BEGIN
    IMMEDIATE one on the same session, so the write waits for the lock instead of failing with "database is locked"
    when another writer commits first. The session's next transaction reads again. Anywhere else, a no-op. Call it
    before reading what the write depends on."""
    current = db.connection().get_execution_options() if db.in_transaction() else db.get_bind().get_execution_options()
    if not current.get("read"):
        return
    db.rollback()
    db.connection(execution_options=WRITE)


def begin_read(db: Session) -> None:
    """The reverse of begin_write, for a POST that only reads (import staging and the batch preview; plan Engineering
    choice 7): ends any transaction, which has nothing to keep, and begins a plain BEGIN on the same session, so the
    reads take their WAL snapshot beside a writer instead of queuing for the write lock. The session's next
    transaction is the route's usual one again."""
    if db.in_transaction():
        db.rollback()
    db.connection(execution_options={"immediate": False, "read": True})


def allow_writes(raw) -> None:
    """For a raw pooled connection (engine.raw_connection()), which skips the begin hook above: turns query_only off,
    as a test GET may have left it on, so a raw write (a backup's VACUUM INTO) can run."""
    if raw.info.get(_QUERY_ONLY, False):
        raw.driver_connection.execute("PRAGMA query_only = OFF")
        raw.info[_QUERY_ONLY] = False


def check_key(engine: Engine) -> None:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT count(*) FROM sqlite_master"))
    except (DatabaseError, sqlcipher3.DatabaseError) as e:
        raise WrongKey("The encryption key does not open this database.") from e
