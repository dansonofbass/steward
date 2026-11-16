from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine


class MigrationFailed(RuntimeError):
    pass


def _config(engine: Engine, *, household: bool = True) -> Config:
    cfg = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
    cfg.attributes["engine"] = engine
    cfg.attributes["household"] = household   # 0014 tags business accounts in household books only
    return cfg


def run_migrations(engine: Engine, household: bool = True) -> None:
    migrate_to(engine, "head", household=household)


def migrate_to(engine: Engine, revision: str, household: bool = True) -> None:
    """Upgrades to one revision: head for a book; an older one for the empty copy a restore builds to learn what a
    backup at that revision must look like."""
    try:
        command.upgrade(_config(engine, household=household), revision)
    except Exception as e:  # noqa: BLE001 — any failure must stop startup
        raise MigrationFailed(str(e)) from e


def _directory_config(engine: Engine) -> Config:
    cfg = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent / "alembic_directory"))
    cfg.attributes["engine"] = engine
    return cfg


def run_directory_migrations(engine: Engine) -> None:
    try:
        command.upgrade(_directory_config(engine), "head")
    except Exception as e:  # noqa: BLE001 — the caller decides whether this stops startup
        raise MigrationFailed(str(e)) from e


def book_head() -> str:
    """The book migrations' head revision: what a book (and a backup of one) must be at."""
    from alembic.script import ScriptDirectory
    return ScriptDirectory(str(Path(__file__).parent / "alembic")).get_current_head()


def book_revisions() -> set[str]:
    """Every book revision Alembic knows."""
    from alembic.script import ScriptDirectory
    return {s.revision for s in ScriptDirectory(str(Path(__file__).parent / "alembic")).walk_revisions()}


def directory_head() -> str:
    from alembic.script import ScriptDirectory
    return ScriptDirectory(str(Path(__file__).parent / "alembic_directory")).get_current_head()


def book_revision(engine: Engine) -> str | None:
    """A book's Alembic revision as it stands (read before an upgrade); None for a file Alembic hasn't touched."""
    from sqlalchemy import inspect, text
    with engine.connect() as c:
        if "alembic_version" not in inspect(c).get_table_names():
            return None
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar()
