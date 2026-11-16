"""Open-source evaluation 6.4 and 6.5: a write reaches the API only from Steward's own pages, and no other site may
read an answer (there is no CORS, on purpose)."""
import pytest
from starlette.middleware.cors import CORSMiddleware

from steward.api.origin import REFUSED, allowed
from steward.auth.users import create_user

BASE = "https://nas.tail1234.ts.net"
HOST = "nas.tail1234.ts.net"


def _h(**kw) -> dict[bytes, bytes]:
    return {k.replace("_", "-").encode(): v.encode() for k, v in kw.items()}


@pytest.mark.parametrize("method,path,headers,scheme,ok", [
    ("GET", "/api/x", _h(sec_fetch_site="cross-site"), "https", True),                 # reads are never refused
    ("POST", "/transactions", _h(sec_fetch_site="cross-site"), "https", True),         # off the API: the SPA's 404
    ("POST", "/api/x", _h(sec_fetch_site="same-origin"), "https", True),
    ("POST", "/api/x", _h(sec_fetch_site="none"), "https", True),                      # typed or bookmarked
    ("POST", "/api/x", _h(sec_fetch_site="same-site"), "https", False),                # a sibling host on the domain
    ("PUT", "/api/x", _h(sec_fetch_site="cross-site"), "https", False),
    ("DELETE", "/api/x", _h(sec_fetch_site="cross-site", origin=BASE, host=HOST), "https", False),  # the browser wins
    ("PATCH", "/api/x", _h(sec_fetch_site=""), "https", False),
    ("POST", "/api/x", _h(origin=BASE, host=HOST), "https", True),                     # an older browser
    ("POST", "/api/x", _h(origin=BASE, host=HOST), "http", True),     # XFP not trusted: the base URL still matches
    ("POST", "/api/x", _h(origin="http://localhost:8441", host="localhost:8441"), "http", True),     # e2e, dev
    ("POST", "/api/x", _h(origin="https://evil.example", host=HOST), "https", False),
    ("POST", "/api/x", _h(origin="https://blog.tail1234.ts.net", host=HOST), "https", False),
    ("POST", "/api/x", _h(origin=f"http://{HOST}", host=HOST), "https", False),        # a plain-http page, same name
    ("PUT", "/api/x", _h(origin="null", host=HOST), "https", False),
    ("POST", "/api/x", _h(origin="https://", host=""), "https", False),                # no Host to match
    ("POST", "/api/x", _h(host=HOST), "https", True),                                  # no browser: CLI, gateway
])
def test_allowed(method, path, headers, scheme, ok):
    assert allowed(method, path, headers, scheme, BASE) is ok


def test_the_8443_fallback_port_is_part_of_the_origin():
    base = f"https://{HOST}:8443"
    assert allowed("POST", "/api/x", _h(origin=base, host=f"{HOST}:8443"), "https", base)
    assert not allowed("POST", "/api/x", _h(origin=BASE, host=f"{HOST}:8443"), "https", base)


def test_a_cross_site_or_same_site_write_is_refused(client):
    for site in ("cross-site", "same-site"):
        r = client.post("/api/auth/login", json={"username": "jr", "password": "x"}, headers={"Sec-Fetch-Site": site})
        assert r.status_code == 403 and r.json() == {"error": REFUSED}, site


def test_sign_in_and_passkey_flows_pass_from_stewards_own_pages(client, ddb):
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    own = {"Sec-Fetch-Site": "same-origin", "Origin": BASE}
    body = {"username": "jr", "password": "pw-one-two-3"}
    assert client.post("/api/auth/login", json=body, headers=own).status_code == 200
    assert client.post("/api/auth/passkeys/login/options", json={}, headers=own).status_code == 200
    assert client.post("/api/auth/forgot", json={"username": "jr"}, headers=own).status_code == 202
    assert client.post("/api/auth/logout", headers=own).status_code == 204
    assert client.post("/api/auth/login", json=body, headers={"Origin": BASE}).status_code == 200   # older browser
    assert client.post("/api/auth/login", json=body).status_code == 200                             # no browser


def test_a_cross_site_upload_is_refused_before_its_body_is_read(signed_in):
    """The raw-body and multipart routes the evaluation named: refused as cross-site, not as too big or signed out."""
    cross = {"Sec-Fetch-Site": "cross-site"}
    for path, kw in (("/api/b/ours/import/files", {"files": {"file": ("a.csv", b"Date,Amount\n", "text/csv")}}),
                     ("/api/b/ours/import/statements", {"files": {"file": ("s.pdf", b"%PDF-1.4\n", "application/pdf")}}),
                     ("/api/b/ours/ss/import?person=jr", {"content": b"<x/>", "headers": {"Content-Type": "application/xml"}}),
                     ("/api/b/ours/accounts/1/positions/preview", {"files": {"file": ("p.csv", b"a,b\n", "text/csv")}}),
                     ("/api/b/ours/accounts/1/positions", {"files": {"file": ("p.csv", b"a,b\n", "text/csv")}})):
        headers = {**kw.pop("headers", {}), **cross}
        r = signed_in.post(path, headers=headers, **kw)
        assert r.status_code == 403 and r.json() == {"error": REFUSED}, path
    big = b"{" + b" " * (1100 * 1024) + b"}"              # over BodyLimit's 1 MB default
    r = signed_in.post("/api/auth/forgot", content=big, headers={"Content-Type": "application/json", **cross})
    assert r.status_code == 403                            # not 413: refused before a byte was counted
    r = signed_in.post("/api/auth/forgot", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413                            # the same body from no browser meets the size cap


def test_no_other_site_may_read_an_answer(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers and "access-control-allow-credentials" not in r.headers
    r = client.options("/api/auth/login", headers={"Origin": "https://evil.example",
                                                   "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "content-type"})
    assert "access-control-allow-origin" not in r.headers and "access-control-allow-credentials" not in r.headers


def test_no_cors_middleware_is_installed(app):
    assert all(m.cls is not CORSMiddleware for m in app.user_middleware)


def test_a_cross_site_put_of_the_email_settings_is_refused(client):
    r = client.put("/api/install/settings/email", json={}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json() == {"error": REFUSED}
