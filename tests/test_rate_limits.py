"""Open-source evaluation 6.7: per-address limits on what someone can try without a password. In memory, timed by
steward.clock (the fake clock here, never a sleep)."""
from datetime import timedelta

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from steward.auth.ratelimit import FORGOT, INVITE_ACCEPT, PASSKEY_OPTIONS, RateLimiter, Rule
from steward.auth.users import create_user
from tests.conftest import DEFAULT_NOW

BASE = "https://nas.tail1234.ts.net"
TOO_MANY = "Too many tries. Try again in 15 minutes."
T0 = DEFAULT_NOW


def test_the_limits_are_the_planned_ones():
    assert (FORGOT.tries, FORGOT.window) == (5, timedelta(minutes=15))
    assert (PASSKEY_OPTIONS.tries, PASSKEY_OPTIONS.window) == (30, timedelta(minutes=15))
    assert (INVITE_ACCEPT.tries, INVITE_ACCEPT.window) == (10, timedelta(minutes=15))


def test_refused_tries_do_not_push_the_wait_back():
    rl, rule, ip = RateLimiter(), Rule(2, timedelta(minutes=15)), "100.64.0.1"
    assert rl.hit("door", rule, ip, T0) is None
    assert rl.hit("door", rule, ip, T0 + timedelta(minutes=1)) is None
    assert rl.hit("door", rule, ip, T0 + timedelta(minutes=2)) == T0 + timedelta(minutes=15)
    assert rl.hit("door", rule, ip, T0 + timedelta(minutes=14)) == T0 + timedelta(minutes=15)
    assert rl.hit("door", rule, ip, T0 + timedelta(minutes=15)) is None          # the first try has aged out
    assert rl.hit("door", rule, ip, T0 + timedelta(minutes=15, seconds=1)) == T0 + timedelta(minutes=16)


def test_each_door_and_each_address_counts_alone():
    rl, rule = RateLimiter(), Rule(1, timedelta(minutes=15))
    assert rl.hit("forgot", rule, "100.64.0.1", T0) is None
    assert rl.hit("forgot", rule, "100.64.0.1", T0) is not None
    assert rl.hit("forgot", rule, "100.64.0.2", T0) is None
    assert rl.hit("invite", rule, "100.64.0.1", T0) is None


def test_memory_stays_bounded():
    rl, rule = RateLimiter(max_keys=3), Rule(1, timedelta(minutes=15))
    for i in range(5):
        rl.hit("forgot", rule, f"100.64.0.{i}", T0)
    assert len(rl) == 3
    assert rl.hit("forgot", rule, "100.64.0.0", T0) is None                     # the oldest was forgotten


def test_forgot_answers_429_on_the_sixth_try_and_sends_no_sixth_email(client, ddb, app, fake_clock):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    for _ in range(5):
        assert client.post("/api/auth/forgot", json={"username": "jr"}).status_code == 202
    r = client.post("/api/auth/forgot", json={"username": "jr"})
    assert r.status_code == 429 and r.json() == {"error": TOO_MANY}
    assert r.headers["retry-after"] == "900"
    assert len(app.state.mailer.sent) == 5
    fake_clock.advance(timedelta(minutes=15))
    assert client.post("/api/auth/forgot", json={"username": "jr"}).status_code == 202


def test_unknown_usernames_count_too(client):
    for i in range(5):
        assert client.post("/api/auth/forgot", json={"username": f"ghost{i}"}).status_code == 202
    assert client.post("/api/auth/forgot", json={"username": "ghost5"}).status_code == 429


def test_passkey_sign_in_options_stop_at_thirty(client, fake_clock):
    for _ in range(30):
        assert client.post("/api/auth/passkeys/login/options", json={}).status_code == 200
    r = client.post("/api/auth/passkeys/login/options", json={})
    assert r.status_code == 429 and r.json() == {"error": TOO_MANY}
    fake_clock.advance(timedelta(minutes=15))
    assert client.post("/api/auth/passkeys/login/options", json={}).status_code == 200


def test_invite_acceptance_stops_at_ten(signed_in):
    for _ in range(10):
        assert signed_in.post("/api/invites/accept", json={"token": "not-a-real-token"}).status_code == 404
    r = signed_in.post("/api/invites/accept", json={"token": "not-a-real-token"})
    assert r.status_code == 429 and r.json() == {"error": TOO_MANY}


def test_each_tailnet_device_behind_the_proxy_has_its_own_limit(app, settings):
    """As `steward serve` runs it: uvicorn's proxy-header handling in front, tailscale serve connecting through
    Docker's port publishing. A device can't pick a fresh address, whether its proxy replaces X-Forwarded-For or
    appends to it."""
    proxied = ProxyHeadersMiddleware(app, trusted_hosts=settings.trusted_proxies)
    with TestClient(proxied, base_url=BASE, client=("172.20.0.1", 40000)) as c:
        phone = {"X-Forwarded-For": "100.101.1.1", "X-Forwarded-Proto": "https"}
        for _ in range(5):
            assert c.post("/api/auth/forgot", json={"username": "x"}, headers=phone).status_code == 202
        assert c.post("/api/auth/forgot", json={"username": "x"}, headers=phone).status_code == 429
        laptop = {"X-Forwarded-For": "100.101.1.2", "X-Forwarded-Proto": "https"}
        assert c.post("/api/auth/forgot", json={"username": "x"}, headers=laptop).status_code == 202
        spoof = {"X-Forwarded-For": "203.0.113.9, 100.101.1.1", "X-Forwarded-Proto": "https"}
        assert c.post("/api/auth/forgot", json={"username": "x"}, headers=spoof).status_code == 429
