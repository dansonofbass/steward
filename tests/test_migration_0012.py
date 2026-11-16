"""0012 adds the chat and advisor tables to every book (spec 4.2, 4.6, 5.1) and changes nothing else."""
from alembic import command
from sqlalchemy import inspect, text

from steward.db.engine import make_engine
from steward.db.keys import ensure_key
from steward.db.migrate import _config

NEW = {"advisor_alias", "advisor_outgoing", "chat_conversation", "chat_message", "advisor_state", "chat_seen"}


def test_0012_adds_the_tables_and_downgrades_cleanly(settings):
    eng = make_engine(settings.db_path, ensure_key(settings.key_path))
    command.upgrade(_config(eng), "0011")
    before = set(inspect(eng).get_table_names())
    command.upgrade(_config(eng), "0012")
    assert set(inspect(eng).get_table_names()) == before | NEW
    with eng.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0012"
    cols = {c["name"] for c in inspect(eng).get_columns("advisor_outgoing")}
    assert cols == {"id", "at", "user_id", "conversation_id", "turn_id", "seq", "channel", "part", "payload", "sha256",
                    "bytes", "model", "approved_by"}
    assert {c["name"] for c in inspect(eng).get_columns("chat_message")} == {
        "id", "conversation_id", "turn_id", "role", "content", "mac", "model", "usage", "created_at"}
    command.downgrade(_config(eng), "0011")
    assert set(inspect(eng).get_table_names()) == before
    eng.dispose()
