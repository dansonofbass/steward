from alembic import command
from sqlalchemy import inspect

from steward.db.engine import make_engine
from steward.db.migrate import _config
from tests.books_fixtures import make_pre_books_vault, snapshot

POINTERS = {"import_batch": "imported_by", "plan": "saved_by", "setup_step": "user_id", "user_setup": "user_id"}


def test_0008_keeps_every_other_row_and_drops_the_sign_in_tables_and_their_foreign_keys(settings):
    key = make_pre_books_vault(settings)
    eng = make_engine(settings.db_path, key)
    before = snapshot(eng)
    command.upgrade(_config(eng), "0008")
    assert snapshot(eng) == before
    insp = inspect(eng)
    assert not {"user", "passkey", "password_reset", "session"} & set(insp.get_table_names())
    for table, column in POINTERS.items():
        assert all(fk["referred_table"] != "user" for fk in insp.get_foreign_keys(table)), table
        assert column in {c["name"] for c in insp.get_columns(table)}
    assert {fk["referred_table"] for fk in insp.get_foreign_keys("transaction")} == {"account", "import_batch", "transaction"}
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1   # enforcement is back on afterwards
    eng.dispose()


def test_0008_downgrades_and_upgrades_on_an_empty_book(settings):
    from steward.db.keys import ensure_key
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    cfg = _config(eng)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0007")
    assert "user" in inspect(eng).get_table_names()
    command.upgrade(cfg, "head")
    assert "user" not in inspect(eng).get_table_names()
    eng.dispose()
