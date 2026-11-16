from alembic import context

from steward.db.directory_models import DirectoryBase

target_metadata = DirectoryBase.metadata


def run_migrations_online() -> None:
    engine = context.config.attributes["engine"]  # the directory is only ever migrated by steward.db.migrate
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
