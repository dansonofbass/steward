from steward import clock
from datetime import timedelta

from steward.auth import sessions
from steward.auth.cookies import HOST_SESSION, SESSION
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
    """Issue #7: five wrong tries lock this device's password sign-in for the account, and the lock answers exactly
    as a wrong password and a name nobody has do, so no answer shows that a username exists."""
    _mk(ddb)
    wrong = {"error": "That username or password isn't right."}
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "jr", "password": "no"})
        assert r.status_code == 401 and r.json() == wrong
    r = client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert r.status_code == 401 and r.json() == wrong
    r = client.post("/api/auth/login", json={"username": "nobody-here", "password": "no"})
    assert r.status_code == 401 and r.json() == wrong


def test_logout_invalidates_server_side(client, ddb):
    _mk(ddb)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    token = client.cookies[HOST_SESSION]
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set(HOST_SESSION, token)  # reuse the old token
    assert client.get("/api/auth/me").status_code == 401


def test_revoke_other_device(client, ddb):
    _mk(ddb)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3", "device_label": "A"})
    tok_a = client.cookies[HOST_SESSION]
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3", "device_label": "B"})
    sessions = client.get("/api/auth/sessions").json()["sessions"]
    sid_a = next(s["id"] for s in sessions if s["device_label"] == "A")
    assert client.delete(f"/api/auth/sessions/{sid_a}").status_code == 204
    client.cookies.set(HOST_SESSION, tok_a)
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
    tok_a = client.cookies[HOST_SESSION]
    sid_a = client.get("/api/auth/me").json()["session"]["id"]
    client.cookies.clear()
    _login(client, "bo", "B")
    assert client.delete(f"/api/auth/sessions/{sid_a}").status_code == 404
    client.cookies.set(HOST_SESSION, tok_a)
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
    client.cookies.set(HOST_SESSION, token2)
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


def _set_cookies(r) -> list[str]:
    return [v for k, v in r.headers.multi_items() if k == "set-cookie"]


def test_on_https_the_session_cookie_takes_the_host_prefix(client, ddb):
    """Issue #14: __Host- means Secure, path / and no Domain, so no other host on the domain can set or shadow it."""
    _mk(ddb)
    c, = (v for v in _set_cookies(_login(client)) if "steward_session" in v)
    assert c.startswith(f"{HOST_SESSION}=") and "domain" not in c.lower()
    assert {"secure", "httponly", "path=/", "samesite=lax"} <= {p.strip().lower() for p in c.split(";")}
    assert client.get("/api/auth/me").status_code == 200


def test_on_a_plain_http_install_the_session_cookie_keeps_its_name(settings, books, ddb, monkeypatch):
    """A __Host- cookie must come over https, so the demo on http://localhost keeps the plain name."""
    from fastapi.testclient import TestClient
    from steward.app import create_app
    from steward.settings import Settings
    _mk(ddb)
    monkeypatch.setenv("STEWARD_BASE_URL", "http://localhost:8420")
    with TestClient(create_app(Settings(_env_file=None), books), base_url="http://localhost:8420") as c:
        cookie, = (v for v in _set_cookies(_login(c)) if "steward_session" in v)
    assert cookie.startswith(f"{SESSION}=")


def test_a_session_cookie_from_0_1_0_still_signs_in_and_moves_to_the_new_name(client, ddb):
    """Renaming the cookie mustn't sign anyone out: the old name works for this release, and an answer moves it."""
    u = _mk(ddb)
    token, _ = sessions.create_session(ddb, u, "old phone", clock.now(), 30)
    client.cookies.set(SESSION, token, domain="nas.tail1234.ts.net")    # as the browser keeps it
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["session"]["device_label"] == "old phone"
    moved = _set_cookies(r)
    assert any(v.startswith(f"{HOST_SESSION}={token};") and "secure" in v.lower() for v in moved)
    assert any(v.startswith(f"{SESSION}=") and "max-age=0" in v.lower() for v in moved)
    assert client.cookies.get(SESSION) is None and client.cookies.get(HOST_SESSION) == token
    assert client.get("/api/auth/me").status_code == 200


def test_a_0_1_0_cookie_moves_on_an_answer_the_route_builds_itself(client, ddb):
    """Argon review: the move was written on FastAPI's injected response, which a route that returns its own Response
    (every 204 here) drops. A layer adds it to whatever answer goes out now."""
    u = _mk(ddb)
    token, _ = sessions.create_session(ddb, u, "old phone", clock.now(), 30)
    _, other = sessions.create_session(ddb, u, "tablet", clock.now(), 30)
    client.cookies.set(SESSION, token, domain="nas.tail1234.ts.net")
    r = client.delete(f"/api/auth/sessions/{other.id}")
    assert r.status_code == 204
    moved = _set_cookies(r)
    assert sum(v.startswith(f"{HOST_SESSION}={token};") for v in moved) == 1
    assert any(v.startswith(f"{SESSION}=") and "max-age=0" in v.lower() for v in moved)
    assert client.cookies.get(SESSION) is None and client.cookies.get(HOST_SESSION) == token
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and not _set_cookies(r)                # moved once, not on every answer


def test_signing_out_this_device_with_a_0_1_0_cookie_hands_back_no_revoked_token(client, ddb):
    """Review of the move: revoking the session the request came with must not move its now-dead token to the new
    name; both names are cleared instead."""
    u = _mk(ddb)
    token, mine = sessions.create_session(ddb, u, "old phone", clock.now(), 30)
    client.cookies.set(SESSION, token, domain="nas.tail1234.ts.net")
    r = client.delete(f"/api/auth/sessions/{mine.id}")
    assert r.status_code == 204
    cleared = _set_cookies(r)
    assert not any(v.startswith(f"{HOST_SESSION}={token};") for v in cleared)
    assert any(v.startswith(f"{HOST_SESSION}=") and "max-age=0" in v.lower() for v in cleared)
    assert any(v.startswith(f"{SESSION}=") and "max-age=0" in v.lower() for v in cleared)
    assert client.get("/api/auth/me").status_code == 401


def test_a_0_1_0_cookie_moves_once_on_an_answer_with_a_body(client, ddb):
    u = _mk(ddb)
    token, _ = sessions.create_session(ddb, u, "old phone", clock.now(), 30)
    client.cookies.set(SESSION, token, domain="nas.tail1234.ts.net")
    moved = _set_cookies(client.get("/api/auth/sessions"))
    assert sum(v.startswith(f"{HOST_SESSION}=") for v in moved) == 1 and sum(v.startswith(f"{SESSION}=") for v in moved) == 1


def test_a_0_1_0_cookie_beside_a_new_one_is_never_moved(client, ddb):
    """A plain-named cookie another host on the domain planted can't replace a __Host- session that is already there,
    good or not."""
    u = _mk(ddb)
    planted, _ = sessions.create_session(ddb, u, "planted", clock.now(), 30)
    client.cookies.set(HOST_SESSION, "ended-or-made-up", domain="nas.tail1234.ts.net")
    client.cookies.set(SESSION, planted, domain="nas.tail1234.ts.net")
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and not _set_cookies(r)


def test_the_0_1_0_session_cookie_name_is_read_for_one_release_only():
    """Issue #14 review: while an https install still reads the plain name, another host on the domain can plant it on
    someone signed out. The plan keeps it for 0.1.1 only; this fails from 0.1.2 on until the fallback goes."""
    import re
    from types import SimpleNamespace

    from steward import __version__
    from steward.auth import cookies
    request = SimpleNamespace(cookies={SESSION: "old"},
                              app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(
                                  base_url="https://nas.tail1234.ts.net"))))
    version = tuple(int(n) for n in re.match(r"(\d+)\.(\d+)\.(\d+)", __version__).groups())
    if version >= (0, 1, 2):
        assert cookies.read_session(request) == (None, None), "remove 0.1.0's session cookie name from cookies.py"
    else:
        assert cookies.read_session(request) == ("old", SESSION)


def test_signing_out_clears_both_names(client, ddb):
    _mk(ddb)
    _login(client)
    client.cookies.set(SESSION, "left-over")
    gone = _set_cookies(client.post("/api/auth/logout"))
    for name in (HOST_SESSION, SESSION):
        assert any(v.startswith(f"{name}=") and "max-age=0" in v.lower() for v in gone), name
