import re
from datetime import timedelta

import pytest

from steward.auth.users import create_user, check_login
from steward.books.service import add_membership
from steward.auth import reset
from steward.deps import now


def _both_manage_ours(ddb, ours, *people):
    """Resetting another person's password needs a shared book that the caller manages (plan ruling 8)."""
    for u in people:
        add_membership(ddb, u.id, ours.id, "manager", by=None)
    ddb.commit()


def test_forgot_sends_the_base_url_link_whatever_name_it_came_on(client, ddb, app):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    r = client.post("/api/auth/forgot", json={"username": "JR"},
                    headers={"host": "127.0.0.1:8420"})   # a curl on the box: loopback, so answered
    assert r.status_code == 202
    (to, subject, body), = app.state.mailer.sent
    assert to == "jr@x.com"
    link = re.search(r"https?://\S+", body).group(0)
    assert link.startswith("https://nas.tail1234.ts.net/reset?token=")
    assert "127.0.0.1" not in body


def test_forgot_unknown_user_sends_nothing_same_response(client, app):
    r = client.post("/api/auth/forgot", json={"username": "ghost"})
    assert r.status_code == 202 and app.state.mailer.sent == []


def test_reset_single_use_and_expiry(client, ddb, app):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/forgot", json={"username": "jr"})
    token = re.search(r"token=(\S+)", app.state.mailer.sent[0][2]).group(1)
    r = client.post("/api/auth/reset", json={"token": token, "password": "brand-new-pass-1"})
    assert r.status_code == 200
    assert check_login(ddb, "jr", "brand-new-pass-1", now())
    r = client.post("/api/auth/reset", json={"token": token, "password": "another-pass-22"})
    assert (r.status_code, r.json()) == (400, {"error": "That link has expired or was already used.", "gone": True})


def test_expired_token(ddb, app):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    t0 = now()
    reset.request_reset(ddb, app.state.mailer, "https://nas.tail1234.ts.net", "jr", t0)
    token = re.search(r"token=(\S+)", app.state.mailer.sent[0][2]).group(1)
    with pytest.raises(reset.BadToken):
        reset.consume(ddb, token, "another-pass-22", t0 + timedelta(minutes=16))


def test_weak_password_does_not_burn_link(client, ddb, app):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/forgot", json={"username": "jr"})
    token = re.search(r"token=(\S+)", app.state.mailer.sent[0][2]).group(1)
    r = client.post("/api/auth/reset", json={"token": token, "password": "short"})
    assert r.status_code == 400 and "gone" not in r.json()            # the page keeps its form for another try
    assert client.post("/api/auth/reset", json={"token": token, "password": "long-enough-pass-9"}).status_code == 200


def test_the_gone_link_words_are_the_web_apps():
    """Issue #19: the web app's copy of the expired-link message, which the reset page's tests reply with, is the server's."""
    from pathlib import Path
    copy = (Path(__file__).resolve().parents[1] / "web/src/lib/copy.ts").read_text()
    assert f'export const RESET_LINK_GONE = "{reset.LINK_GONE}";' in copy


def test_email_reset_revokes_existing_sessions(client, ddb, app):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/forgot", json={"username": "jr"})
    token = re.search(r"token=(\S+)", app.state.mailer.sent[0][2]).group(1)
    assert client.post("/api/auth/reset", json={"token": token, "password": "brand-new-pass-1"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_spouse_resets_other_not_self(client, ddb, ours):
    jr = create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    sp = create_user(ddb, "wife", "w@x.com", "W", "pw-four-five-6")
    _both_manage_ours(ddb, ours, jr, sp)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert client.post(f"/api/users/{sp.id}/reset-password", json={"current_password": "pw-one-two-3", "password": "reset-by-jr-77"}).status_code == 204
    assert client.post(f"/api/users/{jr.id}/reset-password", json={"current_password": "pw-one-two-3", "password": "self-reset-88"}).status_code == 403
    ddb.expire_all()  # the API wrote through its own session
    ddb.rollback()  # end the read snapshot so we see the request's commit
    assert check_login(ddb, "wife", "reset-by-jr-77", now())
    assert client.get("/api/auth/me").status_code == 200


def test_spouse_reset_revokes_target_sessions(client, ddb, app, ours):
    from fastapi.testclient import TestClient
    jr = create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    sp = create_user(ddb, "wife", "w@x.com", "W", "pw-four-five-6")
    _both_manage_ours(ddb, ours, jr, sp)
    other = TestClient(app, base_url="https://nas.tail1234.ts.net")
    other.post("/api/auth/login", json={"username": "wife", "password": "pw-four-five-6"})
    assert other.get("/api/auth/me").status_code == 200
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    client.post(f"/api/users/{sp.id}/reset-password", json={"current_password": "pw-one-two-3", "password": "reset-by-jr-77"})
    assert other.get("/api/auth/me").status_code == 401


def test_forgot_still_202_when_mail_fails(settings, books, ddb):
    from fastapi.testclient import TestClient
    from steward.app import create_app

    class BoomMailer:
        def send(self, to, subject, body):
            raise RuntimeError("smtp down")

    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    with TestClient(create_app(settings, books, mailer=BoomMailer()),
                    base_url="https://nas.tail1234.ts.net") as c:
        r = c.post("/api/auth/forgot", json={"username": "jr"})
    assert r.status_code == 202
    assert r.json() == {"message": "If that account exists, we sent a link. It works for 15 minutes."}


def test_consuming_one_link_closes_the_others(client, ddb, app):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/forgot", json={"username": "jr"})
    client.post("/api/auth/forgot", json={"username": "jr"})
    t1, t2 = [re.search(r"token=(\S+)", m[2]).group(1) for m in app.state.mailer.sent]
    assert client.post("/api/auth/reset", json={"token": t1, "password": "brand-new-pass-1"}).status_code == 200
    assert client.post("/api/auth/reset", json={"token": t2, "password": "another-pass-22"}).status_code == 400


def test_spouse_reset_closes_open_links(client, ddb, app, ours):
    jr = create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    sp = create_user(ddb, "wife", "w@x.com", "W", "pw-four-five-6")
    _both_manage_ours(ddb, ours, jr, sp)
    client.post("/api/auth/forgot", json={"username": "wife"})
    token = re.search(r"token=(\S+)", app.state.mailer.sent[0][2]).group(1)
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert client.post(f"/api/users/{sp.id}/reset-password", json={"current_password": "pw-one-two-3", "password": "reset-by-jr-77"}).status_code == 204
    assert client.post("/api/auth/reset", json={"token": token, "password": "another-pass-22"}).status_code == 400
