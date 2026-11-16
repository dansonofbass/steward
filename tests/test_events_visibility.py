"""Import notices stay managers-only on every path (PDF statements spec P4; Engineering choice 14): the day-6 "staged
statements expire" notice can name uploaded files, so a viewer never sees, counts or acts on an EventLog row of kind
"import": not in the events list (the Log screen), not in /summary's needs attention (a parent book's Home), not in
Home's For you, and not dismissable. Managers are unchanged. One predicate, steward.events.event_visible, decides."""
import re
from pathlib import Path

from sqlalchemy import select

from steward.db.models import EventLog
from steward.events import MANAGERS_ONLY, event_visible, log_event
from tests.factories import login, make_person

NOTICE = 'Staged statements expire tomorrow: "chase-march.pdf". Import or remove them.'


def _setup(db, ddb, ours):
    imp = log_event(db, "warn", "import", NOTICE, actionable=True)
    other = log_event(db, "warn", "sync", "Big Bank needs you to sign in again at SimpleFIN", actionable=True)
    db.commit()
    make_person(ddb, "val", [(ours.id, "viewer")])
    make_person(ddb, "mgr", [(ours.id, "manager")])
    return imp, other


def test_the_predicate():
    assert MANAGERS_ONLY == frozenset({"import"})
    assert event_visible(EventLog(kind="import"), manager=True) is True
    assert event_visible(EventLog(kind="import"), manager=False) is False
    assert event_visible(EventLog(kind="sync"), manager=False) is True


def test_a_viewers_events_list_never_holds_an_import_notice(client, db, ddb, ours):
    imp, other = _setup(db, ddb, ours)
    login(client, "val")
    for q in ("", "?unresolved=true", "?limit=1"):
        got = client.get(f"/api/b/ours/events{q}").json()["events"]
        assert [e["id"] for e in got] == [other.id], q            # the limit counts what a viewer may see
        assert "chase-march" not in str(got)
    login(client, "mgr")
    assert {e["id"] for e in client.get("/api/b/ours/events").json()["events"]} == {imp.id, other.id}


def test_a_viewers_needs_attention_never_counts_an_import_notice(client, db, ddb, ours):
    imp, other = _setup(db, ddb, ours)
    login(client, "val")
    assert [x["id"] for x in client.get("/api/b/ours/summary").json()["needs_attention"]] == [other.id]
    login(client, "mgr")
    assert {x["id"] for x in client.get("/api/b/ours/summary").json()["needs_attention"]} == {imp.id, other.id}


def test_a_viewers_home_never_holds_an_import_notice(client, db, ddb, ours):
    imp, other = _setup(db, ddb, ours)
    login(client, "val")
    rows = [x for x in client.get("/api/b/ours/home").json()["for_you"] if x["kind"] == "event"]
    assert [x["id"] for x in rows] == [other.id]


def test_a_viewer_cant_dismiss_an_import_notice(client, db, ddb, ours):
    imp, _ = _setup(db, ddb, ours)
    login(client, "val")
    assert client.post(f"/api/b/ours/events/{imp.id}/resolve").status_code in (403, 404)
    db.rollback()
    assert db.scalar(select(EventLog.resolved_at).where(EventLog.id == imp.id)) is None


def test_the_resolve_route_itself_refuses_a_hidden_event(db, monkeypatch):
    """Behind the viewer write gate, the route checks the predicate too, so marking it viewer_ok later can't leak."""
    import pytest
    from fastapi import HTTPException

    from steward.api import events as api
    e = log_event(db, "warn", "import", NOTICE, actionable=True)
    db.commit()

    class Viewer:
        is_manager, user_id = False, 1
    with pytest.raises(HTTPException) as caught:
        api.resolve(e.id, db=db, ctx=Viewer())
    assert caught.value.status_code == 404
    assert db.get(EventLog, e.id).resolved_at is None


SRC = Path(__file__).parents[1] / "src" / "steward"
# Modules that read EventLog only to dedupe or resolve their own kind, never to show a person anything.
INTERNAL = {"events.py", "books/jobs.py", "services/plan.py", "services/simplefin/sync.py", "services/statements/stage.py",
            "services/same_account/merge.py", "services/same_account/journal.py", "services/undo.py",
            "inventory/accounts.py", "advisor/monitor.py"}


def test_every_person_facing_eventlog_read_goes_through_the_predicate():
    """A ratchet: a module that queries EventLog is either internal (above) or uses event_visible / visible_to. Emails
    (watch/) and the Ask advisor's tools read no EventLog row at all."""
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        text = p.read_text()
        if "/alembic" in rel or rel.startswith("db/") or not re.search(r"\bEventLog\b", text):
            continue
        assert not rel.startswith(("watch/", "advisor/tools")), rel
        if rel not in INTERNAL and re.search(r"select\(EventLog|db\.get\(EventLog", text):
            assert "event_visible" in text or "visible_to" in text, rel
