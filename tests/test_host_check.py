"""Issue #8 (gate finding SEC-8): the API answers only at Steward's own names. A hostile page on a name later pointed
at 127.0.0.1 (DNS rebinding) calls Steward as its own origin, with its own name in Host, so /api/ refuses every name
but STEWARD_BASE_URL's host, a loopback name and STEWARD_ALLOWED_HOSTS. The names below are the ones real installs
use: the demo on localhost, the HTTPS proxy (which passes the Host through), tailscale serve, a NAS on a VPN name,
and the compose healthchecks."""
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from steward.api.hosts import WRONG_HOST, HostCheck, host_name
from steward.app import create_app
from steward.settings import ALLOWED_HOSTS_RULE, Settings

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _app(monkeypatch, base_url: str, allowed: str | None = None):
    monkeypatch.setenv("STEWARD_BASE_URL", base_url)
    if allowed is None:
        monkeypatch.delenv("STEWARD_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("STEWARD_ALLOWED_HOSTS", allowed)
    return Settings(_env_file=None)


def _status(settings, books, host: str, path: str = "/api/health", method: str = "GET") -> int:
    with TestClient(create_app(settings, books), base_url=f"http://{host}") as c:
        return c.request(method, path).status_code


@pytest.mark.parametrize("header,name", [
    ("nas.tail1234.ts.net", "nas.tail1234.ts.net"),
    ("NAS.Tail1234.ts.net:443", "nas.tail1234.ts.net"),
    ("nas.tail1234.ts.net.", "nas.tail1234.ts.net"),
    ("localhost:8420", "localhost"),
    ("127.0.0.1:8420", "127.0.0.1"),
    ("[::1]:8420", "::1"),
    ("[::1]", "::1"),
    ("", ""),
    ("[::1", ""),
    ("a b", ""),
])
def test_host_name_reads_the_name_without_its_port(header, name):
    assert host_name(header) == name


@pytest.mark.parametrize("base_url,hosts", [
    # The demo (deploy/compose.demo.yml), on its port or another, and the e2e server.
    ("http://localhost:8420", ["localhost:8420", "127.0.0.1:8420", "[::1]:8420"]),
    ("http://localhost:8425", ["localhost:8425", "127.0.0.1:8425"]),
    # tailscale serve, and the 8443 fallback (deploy/nas/README.md): the tailnet name, as the browser sent it.
    ("https://steward.tail1234.ts.net", ["steward.tail1234.ts.net"]),
    ("https://nas.tail1234.ts.net:8443", ["nas.tail1234.ts.net:8443"]),
    # steward-proxy, any of its three Caddyfiles: Caddy passes the browser's Host through to steward:8420.
    ("https://steward.example.com", ["steward.example.com", "Steward.Example.com"]),
    ("https://steward.lan", ["steward.lan"]),
    # Healthchecks inside the container, and a curl on the box.
    ("https://steward.example.com", ["127.0.0.1:8420", "localhost:8420"]),
])
def test_the_names_real_installs_use_are_answered(settings, books, monkeypatch, base_url, hosts):
    s = _app(monkeypatch, base_url)
    for host in hosts:
        assert _status(s, books, host) == 200, host


def test_any_other_name_gets_421_and_a_plain_message(client):
    for host in ("evil.example", "nas.tail1234.ts.net.evil.example", "10.0.0.5:8420", "steward"):
        client.headers["host"] = host
        for method, path in (("GET", "/api/health"), ("POST", "/api/auth/login"), ("POST", "/api/auth/forgot"),
                             ("GET", "/api/auth/me"), ("GET", "/api")):
            r = client.request(method, path, json={"username": "jr", "password": "x"})
            assert r.status_code == 421 and r.json() == {"error": WRONG_HOST}, (host, method, path)
            assert r.headers["x-content-type-options"] == "nosniff"     # the 421 carries the security headers


def test_a_lockout_or_a_reset_email_cant_come_from_a_rebound_name(client, ddb, app):
    from steward.auth.users import create_user
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.headers["host"] = "rebound.example"
    for _ in range(60):
        assert client.post("/api/auth/login", json={"username": "jr", "password": "no"}).status_code == 421
    assert client.post("/api/auth/forgot", json={"username": "jr"}).status_code == 421
    assert app.state.mailer.sent == []
    client.headers["host"] = "nas.tail1234.ts.net"
    assert client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"}).status_code == 200


def test_pages_off_the_api_are_not_checked(client):
    client.headers["host"] = "evil.example"
    assert client.get("/login").status_code != 421


def test_steward_allowed_hosts_adds_names(settings, books, monkeypatch):
    """A NAS reached at a VPN name or address besides STEWARD_BASE_URL's, or the gateway's nas_url (a 100.x address)."""
    s = _app(monkeypatch, "https://steward.example.com", " nas.tail1234.ts.net , 100.101.102.103,[fd7a:115c::1],")
    assert s.api_hosts == frozenset({"steward.example.com", "nas.tail1234.ts.net", "100.101.102.103", "fd7a:115c::1",
                                     "localhost", "127.0.0.1", "::1"})
    for host in ("nas.tail1234.ts.net", "100.101.102.103:443", "[fd7a:115c::1]:443", "steward.example.com"):
        assert _status(s, books, host) == 200, host
    assert _status(s, books, "other.tail1234.ts.net") == 421


def test_an_ipv6_base_url_and_unbracketed_ipv6_names_are_steward_s_own(settings, books, monkeypatch):
    """urlsplit gives STEWARD_BASE_URL's IPv6 host without its brackets; it is still the base name, and a CSP report
    about it says "this address"."""
    from steward.api.csp_report import blocked_of
    s = _app(monkeypatch, "http://[fd7a:115c::1]:8420", "fd7a:115c::2")
    assert {"fd7a:115c::1", "fd7a:115c::2"} <= s.api_hosts
    for host in ("[fd7a:115c::1]:8420", "[FD7A:115C:0::1]", "[fd7a:115c::2]:443"):
        assert _status(s, books, host) == 200, host
    assert _status(s, books, "[fd7a:115c::3]:8420") == 421
    assert blocked_of("http://[fd7a:115c::1]:8420/x.js", s.api_hosts) == "this address"


@pytest.mark.parametrize("header", ["fd7a:115c::1", "fd7a:115c::1:8420", "[steward.lan]", "[steward.lan]:443"])
def test_a_host_header_takes_ipv6_only_in_brackets_and_brackets_only_round_ipv6(header):
    assert host_name(header) == ""


@pytest.mark.parametrize("value", ["https://steward.lan", "steward.lan:8443", "steward lan", "*.example.com",
                                   "steward.lan/x", "[fd7a::1", "[steward.lan]", "fd7a::zz"])
def test_steward_allowed_hosts_takes_only_plain_names(settings, monkeypatch, value):
    monkeypatch.setenv("STEWARD_ALLOWED_HOSTS", value)
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None)
    assert ALLOWED_HOSTS_RULE in str(e.value)


def test_a_request_with_no_host_is_refused():
    calls = []

    async def inner(scope, receive, send):
        calls.append(scope["path"])

    sent = []

    async def send(message):
        sent.append(message)

    import asyncio
    check = HostCheck(inner, frozenset({"localhost"}))
    scope = {"type": "http", "method": "GET", "path": "/api/health", "headers": []}
    asyncio.run(check(scope, None, send))
    assert calls == [] and sent[0]["status"] == 421
    asyncio.run(check({**scope, "headers": [(b"host", b"localhost:8420")]}, None, send))
    assert calls == ["/api/health"]


def _health_hosts(compose_file: Path) -> list[str]:
    """The host each /api/health healthcheck in a compose file asks for, as its URL names it."""
    found = []
    for name, svc in yaml.safe_load(compose_file.read_text())["services"].items():
        test = " ".join(svc.get("healthcheck", {}).get("test", []))
        for url in re.findall(r"https?://([^/'\"]+)/api/health", test):
            found.append(url.replace("$$", "$"))
    return found


def test_every_compose_healthcheck_asks_for_a_name_steward_answers(settings, books, monkeypatch):
    """deploy/compose.yml calls /api/health on 127.0.0.1, and the proxy's STEWARD_DOMAIN is STEWARD_BASE_URL's host
    (proxy.env.example). The NAS's own compose file is private; its check is in tests/test_deploy_files.py."""
    hosts = _health_hosts(DEPLOY / "compose.yml")
    assert hosts == ["127.0.0.1:8420"]
    assert "the host of STEWARD_BASE_URL" in (DEPLOY / "proxy/proxy.env.example").read_text()
    s = _app(monkeypatch, "https://steward.example.com")
    for host in hosts:
        assert _status(s, books, host) == 200, host


def test_every_caddyfile_passes_the_browsers_host_through():
    """Caddy's reverse_proxy keeps the Host unless told otherwise; none of the three may tell it otherwise."""
    for f in sorted((DEPLOY / "proxy").glob("Caddyfile.*")):
        text = f.read_text()
        assert "reverse_proxy steward:8420" in text, f.name
        assert not re.search(r"header_up\s+Host", text, re.I), f.name


def _through_check(scope: dict) -> tuple[list[str], int | None]:
    """The paths HostCheck passed on, and the status it answered itself (None when it passed the request on)."""
    import asyncio
    calls, sent = [], []

    async def inner(scope, receive, send):
        calls.append(scope["path"])

    async def send(message):
        sent.append(message)
    asyncio.run(HostCheck(inner, frozenset({"localhost"}))({"type": "http", "method": "GET", **scope}, None, send))
    return calls, sent[0]["status"] if sent else None


@pytest.mark.parametrize("hosts", [
    [b"attacker.example", b"localhost"],     # Starlette reads the first; the check once read the last
    [b"localhost", b"attacker.example"],
    [b"localhost", b"localhost"],
])
def test_a_request_with_more_than_one_host_is_refused(hosts):
    """Argon review: uvicorn's default parser (httptools) passes every Host header through. Starlette's
    request.headers reads the first, so a check that read another could pass a name the app then sees as Host.
    More than one Host is refused, whatever they say."""
    calls, status = _through_check({"path": "/api/health", "headers": [(b"host", h) for h in hosts]})
    assert calls == [] and status == 421


def test_an_absolute_form_target_is_checked_too():
    """Argon review: under uvicorn's h11 parser (--http h11) the path of "GET http://other/api/... HTTP/1.1" is the
    whole target, which doesn't start with /api/. httptools, the default, gives the path alone. Any path that isn't
    origin-form goes through the host check, so a wrong Host is refused under either parser."""
    target = "http://attacker.example/api/auth/me"
    assert _through_check({"path": target, "headers": [(b"host", b"attacker.example")]}) == ([], 421)
    assert _through_check({"path": "*", "headers": [(b"host", b"attacker.example")]}) == ([], 421)
    assert _through_check({"path": target, "headers": [(b"host", b"localhost")]}) == ([target], None)
    assert _through_check({"path": "/login", "headers": [(b"host", b"attacker.example")]}) == (["/login"], None)


def test_an_absolute_form_target_at_steward_s_name_reaches_no_route(client):
    """What the app does with such a path once the Host passes: no route matches it."""
    import asyncio
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "https",
             "path": "http://attacker.example/api/auth/me", "raw_path": b"http://attacker.example/api/auth/me",
             "query_string": b"", "root_path": "", "headers": [(b"host", b"nas.tail1234.ts.net")],
             "client": ("127.0.0.1", 50000), "server": ("nas.tail1234.ts.net", 443), "state": {}}
    asyncio.run(client.app(scope, receive, send))
    assert sent[0]["status"] == 404
