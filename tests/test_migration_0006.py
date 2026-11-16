from alembic import command
from sqlalchemy import inspect

from steward.db.engine import make_engine
from steward.db.keys import ensure_key
from steward.db.migrate import _config

NEW = {"plan", "ss_earnings", "child", "asset_class"}


def test_0006_creates_the_plan_tables_and_downgrades_cleanly(settings):
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    cfg = _config(eng)
    command.upgrade(cfg, "head")
    assert NEW <= set(inspect(eng).get_table_names())
    command.downgrade(cfg, "0005")
    assert not (NEW & set(inspect(eng).get_table_names()))
    command.upgrade(cfg, "head")
    assert NEW <= set(inspect(eng).get_table_names())
    eng.dispose()
