"""Open-source evaluation 6.6: security headers on every answer, and a CSP on the page.
- nosniff and no-referrer: every answer;
- HSTS: only over HTTPS;
- the CSP and COOP: HTML only, never on JSON, scripts or downloads;
- a route's own header is never doubled or replaced."""
import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from steward.api.headers import SecurityHeaders, content_security_policy
from steward.api.limits import BodyLimit
from steward.api.origin import SameOrigin
from steward.app import create_app
from steward.logs import RequestLog
from steward.web import inline_script_hashes

BASE = "https://nas.tail1234.ts.net"
WEB = Path(__file__).resolve().parents[1] / "web"
BOOT = "\n      (function () { document.documentElement.dataset.phase = 'day'; })();\n    "


def _sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def _dist(tmp_path, boot=BOOT):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(f"<!doctype html><head><script>{boot}</script>"
                                  '<script type="module" crossorigin src="/assets/app-abc123.js"></script>'
                                  "</head><div id=root></div>")
    (d / "assets" / "app-abc123.js").write_text("console.log('hi')")
    return d


def test_every_answer_carries_nosniff_and_no_referrer(client):
    for r in (client.get("/api/health"), client.get("/api/auth/me"),
              client.post("/api/auth/forgot", json={"username": "nobody"})):
        assert r.headers["x-content-type-options"] == "nosniff", r.url
        assert r.headers["referrer-policy"] == "no-referrer", r.url


def test_hsts_only_over_https(client):
    assert client.get("/api/health").headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in client.get("http://localhost:8441/api/health").headers


def test_the_page_gets_the_csp_with_its_inline_script_hash(settings, books, tmp_path):
    settings.web_dir = _dist(tmp_path)
    with TestClient(create_app(settings, books), base_url=BASE) as c:
        page, js, api = c.get("/transactions"), c.get("/assets/app-abc123.js"), c.get("/api/health")
    csp = page.headers["content-security-policy"]
    assert csp == content_security_policy((_sha(BOOT),))
    assert f"script-src 'self' {_sha(BOOT)};" in csp
    for d in ("default-src 'self'", "style-src 'self'", "img-src 'self' data:", "font-src 'self'",
              "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'",
              "frame-ancestors 'none'"):
        assert d in csp, d
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "upgrade-insecure-requests" not in csp
    assert page.headers["cross-origin-opener-policy"] == "same-origin"
    for r in (js, api):                                   # documents only: a script or JSON is never a page
        assert "content-security-policy" not in r.headers and "cross-origin-opener-policy" not in r.headers
        assert r.headers["x-content-type-options"] == "nosniff"


def test_the_hash_follows_index_html_when_it_changes(tmp_path):
    d = _dist(tmp_path)
    assert inline_script_hashes(d) == (_sha(BOOT),)
    changed = BOOT.replace("'day'", "'night'")
    (d / "index.html").write_text((d / "index.html").read_text().replace(BOOT, changed))
    assert inline_script_hashes(d) == (_sha(changed),)
    assert inline_script_hashes(tmp_path / "nothing-built") == ()


def test_the_real_index_html_has_exactly_the_theme_bootstrap_inline():
    """web/index.html's one inline script, the first-paint sky phase, is found and hashed. Vite copies it into dist
    byte for byte and the server hashes dist's copy at start, so an edit never needs a hand-kept hash."""
    body = re.search(r"<script>(.*?)</script>", (WEB / "index.html").read_text(), re.S).group(1)
    assert "dataset.phase" in body
    assert inline_script_hashes(WEB) == (_sha(body),)   # the source index.html stands in for dist's


def test_a_routes_own_headers_are_kept_and_never_doubled():
    inner = FastAPI()

    @inner.get("/api/file")
    def file():
        return Response(b"x", media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"})

    with TestClient(SecurityHeaders(inner, csp="default-src 'self'"), base_url=BASE) as c:
        r = c.get("/api/file")
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
    assert r.headers["referrer-policy"] == "same-origin"


def test_refusals_carry_the_headers_too(client):
    r = client.post("/api/auth/forgot", json={"username": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.headers["x-content-type-options"] == "nosniff"
    r = client.post("/api/auth/forgot", content=b"x" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.headers["referrer-policy"] == "no-referrer"


def test_the_layers_go_headers_then_origin_check_outermost_and_the_body_cap_innermost(app):
    order = [m.cls for m in app.user_middleware]          # outermost first
    assert order[:3] == [RequestLog, SecurityHeaders, SameOrigin] and order[-1] is BodyLimit


def test_a_compressed_read_keeps_the_headers(signed_in, db):
    from tests.factories import make_account
    for i in range(12):
        make_account(db, f"Account {i}")
    with signed_in.stream("GET", "/api/b/ours/accounts", headers={"Accept-Encoding": "gzip"}) as r:
        raw = b"".join(r.iter_raw())
    assert r.headers["content-encoding"] == "gzip" and len(json.loads(gzip.decompress(raw))["accounts"]) == 12
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
