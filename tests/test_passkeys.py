import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from steward.auth import passkeys as pk
from steward.auth.cookies import HOST_DEVICE
from steward.auth.users import create_user
from steward.db.directory_models import Passkey, User
from steward.deps import now

PW = {"current_password": "pw-one-two-3"}


def login(client, ddb, username="jr"):
    create_user(ddb, username, f"{username}@x.com", username.upper(), "pw-one-two-3")
    r = client.post("/api/auth/login", json={"username": username, "password": "pw-one-two-3"})
    assert r.status_code == 200


def test_relying_party_from_base_url():
    rp = pk.relying_party("https://nas.tail1234.ts.net")
    assert (rp.rp_id, rp.origin, rp.name) == ("nas.tail1234.ts.net", "https://nas.tail1234.ts.net", "Steward")
    rp = pk.relying_party("http://localhost:8431")
    assert (rp.rp_id, rp.origin) == ("localhost", "http://localhost:8431")
    with pytest.raises(ValueError):
        pk.relying_party("not a url")


def test_challenge_store_pops_once_and_expires():
    t = [1000.0]
    store = pk.ChallengeStore(ttl_s=300, clock=lambda: t[0])
    cid = store.put(b"abc", "register", 7)
    assert store.pop(cid, "login") is None          # wrong kind leaves it in place
    assert store.pop(cid, "register") == (b"abc", 7)
    assert store.pop(cid, "register") is None       # single use
    cid2 = store.put(b"def", "login", None)
    t[0] += 301
    assert store.pop(cid2, "login") is None         # expired


def test_challenge_store_is_bounded():
    store = pk.ChallengeStore(max_items=3)
    ids = [store.put(bytes([i]), "login", None) for i in range(4)]
    assert store.pop(ids[0], "login") is None       # oldest evicted
    assert store.pop(ids[3], "login") == (bytes([3]), None)


def test_register_options_require_sign_in(client):
    assert client.post("/api/auth/passkeys/register/options", json=PW).status_code == 401


def test_register_options_shape(client, ddb):
    login(client, ddb)
    r = client.post("/api/auth/passkeys/register/options", json=PW)
    assert r.status_code == 200
    body = r.json()
    o = body["options"]
    assert o["rp"] == {"name": "Steward", "id": "nas.tail1234.ts.net"}
    assert o["user"]["name"] == "jr" and o["user"]["displayName"] == "JR"
    assert o["authenticatorSelection"]["residentKey"] == "required"
    assert o["authenticatorSelection"]["userVerification"] == "required"
    assert isinstance(o["challenge"], str) and len(body["challenge_id"]) >= 16


def _fake_verified_registration(monkeypatch, cred_id=b"cred-1", pub=b"pub-1", count=0):
    def fake(rp, credential, challenge):
        assert credential["id"] == "ZmFrZQ"  # the client-side JSON is passed through untouched
        return cred_id, pub, count
    monkeypatch.setattr(pk, "verify_registration", fake)


def test_register_verify_stores_passkey(client, ddb, monkeypatch):
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    _fake_verified_registration(monkeypatch)
    r = client.post("/api/auth/passkeys/register/verify",
                    json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "JR's phone"})
    assert r.status_code == 201 and r.json()["passkey"]["label"] == "JR's phone"
    row = ddb.scalars(select(Passkey)).one()
    assert (row.credential_id, row.public_key, row.sign_count, row.label) == (b"cred-1", b"pub-1", 0, "JR's phone")
    listed = client.get("/api/auth/passkeys").json()["passkeys"]
    assert [p["label"] for p in listed] == ["JR's phone"]


def test_register_verify_rejects_reused_or_expired_challenge(client, ddb, monkeypatch):
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    _fake_verified_registration(monkeypatch)
    body = {"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "x"}
    assert client.post("/api/auth/passkeys/register/verify", json=body).status_code == 201
    r = client.post("/api/auth/passkeys/register/verify", json=body)
    assert r.status_code == 400 and r.json() == {"error": "That sign-in attempt expired. Try again.", "code": "expired"}


def test_register_verify_failure_is_plain_words(client, ddb, monkeypatch):
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]

    def boom(rp, credential, challenge):
        raise pk.VerifyFailed("bad attestation")
    monkeypatch.setattr(pk, "verify_registration", boom)
    r = client.post("/api/auth/passkeys/register/verify",
                    json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "x"})
    assert r.status_code == 400 and r.json() == {"error": "That passkey couldn't be checked. Try again."}


def test_label_is_trimmed_and_capped(client, ddb, monkeypatch):
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    _fake_verified_registration(monkeypatch)
    r = client.post("/api/auth/passkeys/register/verify",
                    json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "  " + "x" * 100})
    assert r.json()["passkey"]["label"] == "x" * 80


def test_delete_own_passkey_only(client, ddb, monkeypatch):
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    _fake_verified_registration(monkeypatch)
    pid = client.post("/api/auth/passkeys/register/verify",
                      json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "p"}).json()["passkey"]["id"]
    client.post("/api/auth/logout")
    login(client, ddb, "spouse")
    r = client.delete(f"/api/auth/passkeys/{pid}")
    assert r.status_code == 404 and r.json() == {"error": "That passkey isn't on your account."}
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    assert client.delete(f"/api/auth/passkeys/{pid}").status_code == 200
    assert client.get("/api/auth/passkeys").json()["passkeys"] == []


def test_delete_answers_the_passkeys_still_accepted_for_the_device_to_hear(client, ddb, monkeypatch):
    # Issue #13: after a removal the page calls PublicKeyCredential.signalAllAcceptedCredentials, so the device's
    # credential manager stops offering the removed passkey. The answer is the list as it stands after the delete.
    login(client, ddb)
    user_handle = client.post("/api/auth/passkeys/register/options", json=PW).json()["options"]["user"]["id"]
    first = _register(client, ddb, monkeypatch, cred_id=b"cred-1")
    _register(client, ddb, monkeypatch, cred_id=b"cred-2")
    r = client.delete(f"/api/auth/passkeys/{first}")
    assert r.status_code == 200
    assert r.json() == {"accepted": {"rp_id": "nas.tail1234.ts.net", "user_id": user_handle,
                                     "credential_ids": [pk.bytes_to_base64url(b"cred-2")]}}
    only = ddb.scalars(select(Passkey)).one()
    r = client.delete(f"/api/auth/passkeys/{only.id}")
    assert r.json()["accepted"]["credential_ids"] == []   # the last one gone: the device hides them all


def test_the_signal_names_the_same_user_handle_the_passkey_was_made_with():
    # signalAllAcceptedCredentials matches on (rpId, userId); a handle that drifted from registration's hides nothing.
    user = User(id=42, username="jr", email="jr@x.com", display_name="JR")
    o = json.loads(pk.registration_options(pk.relying_party("https://nas.tail1234.ts.net"), user, [])[0])
    assert o["user"]["id"] == pk.user_handle(user)


def test_login_options_need_no_auth_and_allow_any_credential(client):
    r = client.post("/api/auth/passkeys/login/options")
    assert r.status_code == 200
    o = r.json()["options"]
    assert o["rpId"] == "nas.tail1234.ts.net"
    assert o["userVerification"] == "required"
    assert o.get("allowCredentials") in (None, [])  # discoverable: the browser offers whatever passkey it holds


def _register(client, ddb, monkeypatch, cred_id=b"cred-1"):
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    _fake_verified_registration(monkeypatch, cred_id=cred_id)
    return client.post("/api/auth/passkeys/register/verify",
                       json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "p"}).json()["passkey"]["id"]


def test_login_verify_signs_in_and_bumps_sign_count(client, ddb, monkeypatch):
    login(client, ddb)
    _register(client, ddb, monkeypatch)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]
    monkeypatch.setattr(pk, "verify_authentication", lambda rp, credential, challenge, passkey: 5)
    raw_id = pk.bytes_to_base64url(b"cred-1")
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": cid, "credential": {"id": raw_id, "rawId": raw_id}, "device_label": "JR's phone"})
    assert r.status_code == 200 and r.json()["user"]["username"] == "jr"
    assert client.get("/api/auth/me").json()["session"]["device_label"] == "JR's phone"
    assert ddb.scalars(select(Passkey)).one().sign_count == 5


def test_login_verify_unknown_credential(client, ddb, monkeypatch):
    login(client, ddb)
    client.post("/api/auth/logout")
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]
    raw_id = pk.bytes_to_base64url(b"nope")
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": cid, "credential": {"id": raw_id, "rawId": raw_id}, "device_label": ""})
    assert r.status_code == 401
    assert r.json() == {"error": "That passkey isn't registered any more. Sign in with your password and add it again.",
                        "code": "unknown_credential"}


def test_login_verify_deleted_passkey_is_refused(client, ddb, monkeypatch):
    login(client, ddb)
    pid = _register(client, ddb, monkeypatch)
    client.delete(f"/api/auth/passkeys/{pid}")
    client.post("/api/auth/logout")
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]
    raw_id = pk.bytes_to_base64url(b"cred-1")
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": cid, "credential": {"id": raw_id, "rawId": raw_id}, "device_label": ""})
    assert r.status_code == 401 and "isn't registered any more" in r.json()["error"]


def test_login_verify_bad_signature_is_plain_words(client, ddb, monkeypatch):
    login(client, ddb)
    _register(client, ddb, monkeypatch)
    client.post("/api/auth/logout")
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]

    def boom(rp, credential, challenge, passkey):
        raise pk.VerifyFailed("signature")
    monkeypatch.setattr(pk, "verify_authentication", boom)
    raw_id = pk.bytes_to_base64url(b"cred-1")
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": cid, "credential": {"id": raw_id, "rawId": raw_id}, "device_label": ""})
    assert r.status_code == 400 and r.json() == {"error": "That passkey couldn't be checked. Try again."}
    assert client.get("/api/auth/me").status_code == 401


def test_login_verify_bad_raw_id_is_400(client):
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": cid, "credential": {"id": "***", "rawId": "***"}, "device_label": ""})
    assert r.status_code == 400 and r.json() == {"error": "That passkey couldn't be checked. Try again."}


def test_login_verify_expired_challenge_says_so_in_a_code_the_page_reads(client):
    # Issue #13: the username box's autofill starts again quietly on this answer instead of showing it.
    raw_id = pk.bytes_to_base64url(b"cred-1")
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": "gone", "credential": {"id": raw_id, "rawId": raw_id}, "device_label": ""})
    assert r.status_code == 400 and r.json()["code"] == "expired"


def test_the_username_box_fetches_a_new_challenge_before_the_old_one_expires():
    # web/src/auth/passkeys.ts restarts the autofill wait with fresh options on this clock, so a pick from a sign-in
    # page left open still finds its challenge here.
    src = (Path(__file__).resolve().parents[1] / "web/src/auth/passkeys.ts").read_text()
    def ms(name: str) -> int:
        return int(re.search(rf"{name} = ([0-9_]+);", src).group(1).replace("_", ""))
    assert ms("CHALLENGE_LIFE_MS") == pk.CHALLENGE_TTL_S * 1000
    assert 0 < ms("AUTOFILL_REFRESH_MS") < pk.CHALLENGE_TTL_S * 1000


def test_revoke_all_can_keep_one(ddb):
    from steward.auth import sessions
    from steward.deps import now
    u = create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    t = now()
    tok1, s1 = sessions.create_session(ddb, u, "a", t, 30)
    tok2, s2 = sessions.create_session(ddb, u, "b", t, 30)
    sessions.revoke_all_for_user(ddb, u.id, t + timedelta(seconds=1), keep=s1.id)
    assert sessions.resolve(ddb, tok1, t + timedelta(seconds=2)) is not None
    assert sessions.resolve(ddb, tok2, t + timedelta(seconds=2)) is None


BAD = "That passkey couldn't be checked. Try again."


def test_register_verify_malformed_credential_is_400_with_real_verifier(client, ddb):
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    r = client.post("/api/auth/passkeys/register/verify",
                    json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "x"})
    assert r.status_code == 400 and r.json() == {"error": BAD}


def test_login_verify_malformed_credential_is_400_with_real_verifier(client, ddb, monkeypatch):
    login(client, ddb)
    _register(client, ddb, monkeypatch)
    client.post("/api/auth/logout")
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]
    raw_id = pk.bytes_to_base64url(b"cred-1")
    r = client.post("/api/auth/passkeys/login/verify",
                    json={"challenge_id": cid, "credential": {"id": raw_id, "rawId": raw_id}, "device_label": ""})
    assert r.status_code == 400 and r.json() == {"error": BAD}


def test_login_device_label_is_capped(client, ddb, monkeypatch):
    login(client, ddb)
    _register(client, ddb, monkeypatch)
    client.post("/api/auth/logout")
    cid = client.post("/api/auth/passkeys/login/options").json()["challenge_id"]
    monkeypatch.setattr(pk, "verify_authentication", lambda rp, credential, challenge, passkey: 1)
    raw_id = pk.bytes_to_base64url(b"cred-1")
    client.post("/api/auth/passkeys/login/verify",
                json={"challenge_id": cid, "credential": {"id": raw_id, "rawId": raw_id}, "device_label": "d" * 200})
    assert client.get("/api/auth/me").json()["session"]["device_label"] == "d" * 120


def test_register_verify_duplicate_race_is_409(client, ddb, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession
    login(client, ddb)
    cid = client.post("/api/auth/passkeys/register/options", json=PW).json()["challenge_id"]
    _fake_verified_registration(monkeypatch)

    real_commit = OrmSession.commit

    def clash(self):
        if any(isinstance(o, Passkey) for o in self.new):  # only the passkey insert loses the race
            raise IntegrityError("x", {}, Exception())
        return real_commit(self)
    monkeypatch.setattr(OrmSession, "commit", clash)
    r = client.post("/api/auth/passkeys/register/verify",
                    json={"challenge_id": cid, "credential": {"id": "ZmFrZQ", "rawId": "ZmFrZQ"}, "label": "x"})
    assert r.status_code == 409 and r.json() == {"error": "This passkey is already registered."}


def test_register_options_need_your_current_password(client, ddb):
    login(client, ddb)
    r = client.post("/api/auth/passkeys/register/options", json={"current_password": "wrong-one"})
    assert r.status_code == 403 and r.json()["error"] == "That isn't your current password."
    assert client.post("/api/auth/passkeys/register/options", json={}).status_code == 422


def _lock(ddb, username):
    """The account's own lock (the backstop): it holds a device the account doesn't know. A session used without the
    device cookie it signed in with, as a copied session would be, is such a device, and stays one after a page
    gives it a new device cookie: only a sign-in makes a device known (tests/test_device_lockout.py)."""
    u = ddb.scalars(select(User).where(User.username == username)).one()
    u.locked_until = now() + timedelta(minutes=10)
    ddb.commit()


def test_register_options_refused_while_locked(client, ddb):
    login(client, ddb)
    _lock(ddb, "jr")
    client.cookies.delete(HOST_DEVICE)
    r = client.post("/api/auth/passkeys/register/options", json=PW)
    assert r.status_code == 423 and r.json()["error"].startswith("Too many tries.")
    assert "locked_until" in r.json()


def test_the_account_lock_doesnt_hold_a_device_that_signed_in(client, ddb):
    """Issue #7 review: strangers' wrong passwords can lock the account, but not the member's own signed-in phone out
    of adding a passkey or changing the password."""
    login(client, ddb)
    _lock(ddb, "jr")
    assert client.post("/api/auth/passkeys/register/options", json=PW).status_code == 200


def _two_people(client, ddb, ours):
    from steward.books.service import add_membership
    login(client, ddb)
    sp = create_user(ddb, "wife", "w@x.com", "W", "pw-four-five-6")
    for u in ddb.scalars(select(User)).all():   # both manage ours, so jr may reset wife (plan ruling 8)
        add_membership(ddb, u.id, ours.id, "manager", by=None)
    ddb.commit()
    return sp


def test_reset_other_needs_your_current_password(client, ddb, ours):
    sp = _two_people(client, ddb, ours)
    r = client.post(f"/api/users/{sp.id}/reset-password", json={"current_password": "wrong-one", "password": "reset-by-jr-77"})
    assert r.status_code == 403 and r.json()["error"] == "That isn't your current password."
    ddb.rollback()
    from steward.auth.users import check_login
    assert check_login(ddb, "wife", "pw-four-five-6", now())  # unchanged


def test_reset_other_refused_while_locked(client, ddb, ours):
    sp = _two_people(client, ddb, ours)
    _lock(ddb, "jr")
    client.cookies.delete(HOST_DEVICE)
    r = client.post(f"/api/users/{sp.id}/reset-password", json={**PW, "password": "reset-by-jr-77"})
    assert r.status_code == 423 and r.json()["error"].startswith("Too many tries.")
    assert "locked_until" in r.json()


def test_reset_other_removes_their_passkeys(client, ddb, ours):
    sp = _two_people(client, ddb, ours)
    jr = ddb.scalars(select(User).where(User.username == "jr")).one()
    for uid, cid in ((sp.id, b"wife-key"), (jr.id, b"jr-key")):
        ddb.add(Passkey(user_id=uid, credential_id=cid, public_key=b"pub", sign_count=0, label="p", created_at=now()))
    ddb.commit()
    r = client.post(f"/api/users/{sp.id}/reset-password", json={**PW, "password": "reset-by-jr-77"})
    assert r.status_code == 204
    ddb.rollback()
    assert [p.credential_id for p in ddb.scalars(select(Passkey))] == [b"jr-key"]
