from steward import clock
import re
from datetime import timedelta

from steward.auth import sessions
from steward.db.directory_models import Session as DbSession
from steward.auth.users import create_user


def _mk(ddb):
    return create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")


def test_login_sets_cookie_and_me(client, ddb):
    _mk(ddb)
    r = client.post("/api/auth/login", json={"username": "JR", "password": "pw-one-two-3",
                                             "device_label": "JR's phone"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "jr"
    c = r.headers["set-cookie"].lower()
    assert "httponly" in c and "secure" in c and "samesite=lax" in c
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["session"]["device_label"] == "JR's phone"


def test_me_includes_the_signed_in_persons_own_email(client, ddb):
    _mk(ddb)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert client.get("/api/auth/me").json()["user"]["email"] == "jr@x.com"


def test_bad_password_and_lockout_messages(client, ddb):
    _mk(ddb)
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "jr", "password": "no"})
        assert r.status_code == 401 and r.json()["error"] == "That username or password isn't right."
    r = client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert r.status_code == 423 and r.json()["error"].startswith("Too many tries.")
    assert re.fullmatch(r"Too many tries\. Try again in \d+ minutes?\.", r.json()["error"])


def test_anyone_can_lock_password_sign_in_and_the_threat_model_says_so(client, ddb):
    """Gate finding SEC-5: the lockout counts per account, not per device, so five wrong tries from anyone lock the
    account's password sign-in for 15 minutes, and 423 against 401 shows whether the username exists."""
    from tests.public_docs import ROOT, flat
    _mk(ddb)
    for name in ("jr", "nobody-here"):
        for _ in range(5):
            client.post("/api/auth/login", json={"username": name, "password": "no"})
    assert client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"}).status_code == 423
    assert client.post("/api/auth/login", json={"username": "nobody-here", "password": "no"}).status_code == 401
    rows = (ROOT / "docs/explanations/threat-model.md").read_text(encoding="utf-8").splitlines()
    s5 = flat(next(r for r in rows if "(../CLAIMS.md#s5)" in r and r.startswith("|")))
    assert "anyone who can reach the sign-in page" in s5 and "15 minutes" in s5 and "username exists" in s5


def test_logout_invalidates_server_side(client, ddb):
    _mk(ddb)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    token = client.cookies["steward_session"]
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("steward_session", token)  # reuse the old token
    assert client.get("/api/auth/me").status_code == 401


def test_revoke_other_device(client, ddb):
    _mk(ddb)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3", "device_label": "A"})
    tok_a = client.cookies["steward_session"]
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3", "device_label": "B"})
    sessions = client.get("/api/auth/sessions").json()["sessions"]
    sid_a = next(s["id"] for s in sessions if s["device_label"] == "A")
    assert client.delete(f"/api/auth/sessions/{sid_a}").status_code == 204
    client.cookies.set("steward_session", tok_a)
    assert client.get("/api/auth/me").status_code == 401


def test_unauthenticated(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and r.json() == {"error": "Please sign in."}


def test_logout_clears_cookie(client, ddb):
    _mk(ddb)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    r = client.post("/api/auth/logout")
    assert "steward_session=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()


def _login(client, name="jr", label=""):
    return client.post("/api/auth/login", json={"username": name, "password": "pw-one-two-3",
                                                "device_label": label})


def test_cannot_revoke_another_users_session(client, ddb):
    _mk(ddb)
    create_user(ddb, "bo", "bo@x.com", "Bo", "pw-one-two-3")
    _login(client, "jr", "A")
    tok_a = client.cookies["steward_session"]
    sid_a = client.get("/api/auth/me").json()["session"]["id"]
    client.cookies.clear()
    _login(client, "bo", "B")
    assert client.delete(f"/api/auth/sessions/{sid_a}").status_code == 404
    client.cookies.set("steward_session", tok_a)
    assert client.get("/api/auth/me").status_code == 200


def test_expired_sessions(client, ddb):
    u = _mk(ddb)
    t = clock.now()
    token, _ = sessions.create_session(ddb, u, "x", t, 30)
    assert sessions.resolve(ddb, token, t + timedelta(days=31)) is None
    _login(client, "jr", "web")
    sid = client.get("/api/auth/me").json()["session"]["id"]
    ddb.rollback()  # end the read snapshot so we see the request's commit
    row = ddb.get(DbSession, sid)
    row.expires_at = t - timedelta(days=1)
    ddb.commit()
    assert client.get("/api/auth/me").status_code == 401
    assert not sessions.revoke(ddb, sid, u.id, t)
    token2, s2 = sessions.create_session(ddb, u, "y", t, 30)
    client.cookies.set("steward_session", token2)
    s2.expires_at = t - timedelta(seconds=1)
    ddb.commit()
    assert client.get("/api/auth/sessions").status_code == 401


def test_expired_session_not_listed_or_revocable(client, ddb):
    u = _mk(ddb)
    _login(client, "jr", "live")
    t = clock.now()
    _, old = sessions.create_session(ddb, u, "old", t, 30)
    old.expires_at = t - timedelta(days=1)
    ddb.commit()
    labels = [s["device_label"] for s in client.get("/api/auth/sessions").json()["sessions"]]
    assert labels == ["live"]
    assert client.delete(f"/api/auth/sessions/{old.id}").status_code == 404


def test_resolve_updates_last_seen(ddb):
    u = _mk(ddb)
    t = clock.now()
    token, s = sessions.create_session(ddb, u, "x", t, 30)
    later = t + timedelta(hours=2)
    sessions.resolve(ddb, token, later)
    ddb.refresh(s)
    assert s.last_seen_at == later


def test_login_cookie_lifetime_and_path(client, ddb):
    _mk(ddb)
    c = _login(client).headers["set-cookie"].lower()
    assert "max-age=2592000" in c and "path=/" in c


def test_the_sessions_last_seen_is_stamped_at_most_every_five_minutes(signed_in, ddb, fake_clock):
    """Phase 18: the stamp was a committed write on every signed-in request. Inside five minutes a request writes
    nothing; after, the next one stamps, through begin_write, since a GET's directory session is read-only in tests."""
    from sqlalchemy import select

    def seen():
        ddb.rollback()                                  # a fresh snapshot
        return ddb.scalar(select(DbSession.last_seen_at))
    first = seen()
    fake_clock.advance(timedelta(minutes=4))
    assert signed_in.get("/api/auth/me").status_code == 200
    assert seen() == first
    fake_clock.advance(timedelta(minutes=2))
    assert signed_in.get("/api/auth/me").status_code == 200
    assert seen() > first + timedelta(minutes=5)


def test_a_get_reads_the_directory_and_cannot_write_it_in_tests(app):
    """A GET's directory session is a plain read (BEGIN: no write lock). Tests make a write in it an error, so a GET
    that writes the directory without begin_write fails here, as a book GET does."""
    from types import SimpleNamespace

    import pytest
    from sqlalchemy import text, update
    from sqlalchemy.exc import DBAPIError

    from steward.db.directory_models import User
    from steward.deps import _directory_session
    with _directory_session(SimpleNamespace(method="GET", app=app)) as s:
        assert s.execute(text("SELECT 1")).scalar() == 1
        with pytest.raises(DBAPIError, match="readonly"):
            s.execute(update(User).values(display_name="x"))
