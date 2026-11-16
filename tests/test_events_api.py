from sqlalchemy import func, select

from steward.db.models import EventLog, UndoEntry
from steward.deps import now
from steward.events import log_event, resolve_event, resolve_events
from steward.services.undo import CHANGED_SINCE
from tests.factories import make_user


def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_list_and_resolve(client, db):
    login(client, db)
    e1 = log_event(db, "warn", "sync", "Marcus needs you to sign in again at SimpleFIN", actionable=True)
    e2 = log_event(db, "info", "system", "Started")
    db.commit()
    ev = client.get("/api/b/ours/events").json()["events"]
    assert [x["id"] for x in ev] == [e2.id, e1.id]
    assert set(ev[1]) == {"id", "at", "level", "kind", "message", "actionable", "resolved_at"}
    assert ev[1]["resolved_at"] is None and ev[1]["actionable"] is True
    assert client.post(f"/api/b/ours/events/{e1.id}/resolve").status_code == 200
    assert client.get("/api/b/ours/events?unresolved=true").json()["events"][0]["id"] == e2.id
    assert len(client.get("/api/b/ours/events?unresolved=true").json()["events"]) == 1
    assert client.get("/api/b/ours/events?limit=1").json()["events"][0]["id"] == e2.id
    assert client.get("/api/b/ours/events").json()["events"][1]["resolved_at"] is not None
    assert client.post("/api/b/ours/events/999/resolve").status_code == 404
    assert client.get("/api/b/ours/summary").json()["needs_attention"] == []


def test_dismissing_a_sync_warning_remembers_it_on_the_institution(client, db):
    from steward.db.models import Institution, Source
    login(client, db)
    msg = "Marcus needs you to sign in again at SimpleFIN"
    db.add(Institution(name="Marcus", source=Source.simplefin, simplefin_org_id="m", last_error=msg))
    e = log_event(db, "warn", "sync", msg, actionable=True)
    db.commit()
    assert client.post(f"/api/b/ours/events/{e.id}/resolve").status_code == 200
    db.rollback()  # leave the snapshot this session was reading
    assert db.scalar(select(Institution.dismissed_error).where(Institution.simplefin_org_id == "m")) == msg
    assert db.get(EventLog, e.id).resolved_at is not None


def test_requires_sign_in(client):
    assert client.get("/api/b/ours/events").status_code == 401
    assert client.post("/api/b/ours/events/1/resolve").status_code == 401


def test_resolve_by_kind(db):
    log_event(db, "warn", "sync", "a", actionable=True)
    log_event(db, "warn", "sync", "b", actionable=True)
    other = log_event(db, "warn", "import", "c")
    db.commit()
    assert resolve_events(db, "sync", now()) == 2 and resolve_events(db, "sync", now()) == 0
    assert other.resolved_at is None


def test_resolve_event_is_idempotent(db):
    e = log_event(db, "info", "sync", "x")
    t1 = now()
    assert resolve_event(db, e.id, t1) is True
    first = e.resolved_at
    assert resolve_event(db, e.id, now()) is True and e.resolved_at == first
    assert resolve_event(db, 12345, t1) is False


def test_resolve_events_matching_prefix_only(db):
    from datetime import datetime, timezone
    from steward.events import resolve_events_matching
    t = datetime(2026, 10, 12, tzinfo=timezone.utc)
    a = log_event(db, "warn", "sync", "Big Bank needs you to sign in again at SimpleFIN", actionable=True)
    b = log_event(db, "warn", "sync", "Marcus needs you to sign in again at SimpleFIN", actionable=True)
    c = log_event(db, "warn", "import", "Big Bank import failed", actionable=True)
    d = log_event(db, "warn", "sync", "100%_Bank: odd", actionable=True)
    assert resolve_events_matching(db, "sync", "Big Bank", t) == 1
    assert resolve_events_matching(db, "sync", "%", t) == 0  # wildcard characters are literal
    assert a.resolved_at == t and b.resolved_at is None and c.resolved_at is None and d.resolved_at is None


def test_dismiss_returns_undo_and_undo_reopens_the_event(client, db):
    login(client, db)
    e = log_event(db, "error", "chat", "A sent answer is missing from the record.", actionable=True)
    db.commit()
    r = client.post(f"/api/b/ours/events/{e.id}/resolve")
    assert r.status_code == 200 and set(r.json()) == {"undo"}
    db.rollback()
    assert db.get(EventLog, e.id).resolved_at is not None
    entry = db.get(UndoEntry, r.json()["undo"])
    assert entry.action == "dismiss" and "missing from the record" not in entry.before + entry.after   # ids and times only
    rows = db.scalar(select(func.count()).select_from(EventLog))
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    db.rollback()
    assert db.get(EventLog, e.id).resolved_at is None
    assert db.scalar(select(func.count()).select_from(EventLog)) == rows        # reopened, nothing deleted
    assert [x["id"] for x in client.get("/api/b/ours/events?unresolved=true").json()["events"]] == [e.id]


def test_undo_after_the_event_changed_since_is_refused(client, db):
    login(client, db)
    e = log_event(db, "warn", "sync", "Big Bank needs you to sign in again at SimpleFIN", actionable=True)
    db.commit()
    token = client.post(f"/api/b/ours/events/{e.id}/resolve").json()["undo"]
    db.rollback()
    ev = db.get(EventLog, e.id)
    ev.resolved_at = None                       # the next sync reopened it...
    db.commit()
    resolve_event(db, e.id, now())              # ...and resolved it again, at a new time
    db.commit()
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (409, {"error": CHANGED_SINCE})


def test_a_viewer_cannot_dismiss(client, db, ddb, ours):
    from tests.factories import login as sign_in, make_person
    make_person(ddb, "val", [(ours.id, "viewer")])
    e = log_event(db, "warn", "sync", "Big Bank needs you to sign in again at SimpleFIN", actionable=True)
    db.commit()
    sign_in(client, "val")
    assert client.post(f"/api/b/ours/events/{e.id}/resolve").status_code == 403
    db.rollback()
    assert db.scalar(select(EventLog.resolved_at).where(EventLog.id == e.id)) is None
