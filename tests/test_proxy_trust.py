"""Steward behind its proxies (tailscale serve through Docker, or steward-proxy's Caddy).

`steward serve` runs uvicorn with proxy_headers=True and forwarded_allow_ips=STEWARD_TRUSTED_PROXIES: loopback and
the private ranges Docker hands out, which is where both proxies connect from. So the X-Forwarded-For and
X-Forwarded-Proto they set become the request's client address and scheme, and a tailnet device that reached Steward
some other way can claim neither. Only the files in ALLOWED read them:
- the write check (api/origin.py: the scheme, for an older browser's Origin);
- the headers (api/headers.py: HSTS over HTTPS);
- the per-address limits (auth/ratelimit.py), and the sign-in lockout for a request with no device cookie
  (auth/devices.py, issue #7);
- Get Steward ready's address row (api/ready.py: managers only, display only; it shows the scheme Steward saw and, when
  a proxy isn't trusted, that proxy's address for the STEWARD_TRUSTED_PROXIES line, and decides nothing with them).
Anything else that starts reading them is added here on purpose."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from steward.auth.passkeys import relying_party
from tests.factories import make_user

SRC = Path(__file__).resolve().parents[1] / "src/steward"
READS_PROXY_INFO = re.compile(r"request\.client|\.url\.scheme|x-forwarded|request\.base_url|url_for\("
                              r"|scope\[.(client|scheme).\]|scope\.get\(.(client|scheme).")
ALLOWED = {"api/headers.py", "api/origin.py", "api/ready.py", "auth/devices.py", "auth/ratelimit.py"}


def test_only_the_allowed_files_read_the_client_address_or_scheme():
    hits = {str(p.relative_to(SRC)) for p in sorted(SRC.rglob("*.py"))
            if any(READS_PROXY_INFO.search(line.lower()) for line in p.read_text().splitlines())}
    assert hits == ALLOWED, f"{sorted(hits ^ ALLOWED)}: only ALLOWED may read what a proxy says (see the docstring)"


def _seen(peer: str, headers: dict, trusted: str) -> dict:
    """What uvicorn's proxy-header handling, set up as `steward serve` sets it, makes of one request."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    got = {}

    async def echo(scope, receive, send):
        got.update(client=scope["client"][0], scheme=scope["scheme"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    TestClient(ProxyHeadersMiddleware(echo, trusted_hosts=trusted), base_url="http://nas",
               client=(peer, 40000)).get("/", headers=headers)
    return got


def test_the_proxies_pass_on_the_device_and_https_but_a_device_cannot_claim_them(settings):
    trusted = settings.trusted_proxies
    via = {"X-Forwarded-For": "100.101.102.103", "X-Forwarded-Proto": "https"}
    device = {"client": "100.101.102.103", "scheme": "https"}
    assert _seen("172.20.0.1", via, trusted) == device          # tailscale serve, through Docker's port publishing
    assert _seen("172.20.0.3", via, trusted) == device          # steward-proxy's Caddy on the compose network
    assert _seen("127.0.0.1", via, trusted) == device           # e2e and dev: uvicorn on loopback
    spoofed = {"X-Forwarded-For": "203.0.113.9, 100.101.102.103", "X-Forwarded-Proto": "https"}
    assert _seen("172.20.0.1", spoofed, trusted)["client"] == "100.101.102.103"   # the address the proxy added
    assert _seen("100.101.102.105", via, trusted) == {"client": "100.101.102.105", "scheme": "http"}  # no proxy


def test_passkeys_take_their_origin_from_the_base_url_on_a_custom_domain():
    rp = relying_party("https://steward.example.com")
    assert (rp.rp_id, rp.origin) == ("steward.example.com", "https://steward.example.com")


def test_the_session_cookie_is_secure_whatever_the_proxy_says(app, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    with TestClient(app, base_url="http://nas.tail1234.ts.net") as c:     # plain http, at the base URL's name
        r = c.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"},
                   headers={"X-Forwarded-Proto": "http", "X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200
    assert "secure" in r.headers["set-cookie"].lower()
