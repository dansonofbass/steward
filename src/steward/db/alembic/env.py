from alembic import context

from steward.db.engine import make_engine
from steward.db.keys import read_key
from steward.db.models import Base
from steward.settings import get_settings

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = context.config.attributes.get("engine")
    if engine is None:
        s = get_settings()
        engine = make_engine(s.db_path, read_key(s.key_path, private=s.key_file is not None))
    with engine.connect() as connection:
        # Rebuilding a table in batch mode copies it, drops it and renames the copy. With foreign keys enforced,
        # dropping a table other rows point at fails, so enforcement is off for the run. The pragma only changes
        # outside a transaction, so it goes straight to the driver before Alembic begins one.
        raw = connection.connection.driver_connection
        raw.execute("PRAGMA foreign_keys = OFF")
        try:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            # SQLite has no transactional DDL, so Alembic commits each migration on its own; what can still be open
            # here is the read of alembic_version it autobegan (always, when the book was already at head). The
            # pragma is ignored inside a transaction, which left this pooled connection without enforcement for the
            # life of the engine, so end that transaction first.
            if connection.in_transaction():
                connection.rollback()
            raw.execute("PRAGMA foreign_keys = ON")


run_migrations_online()
