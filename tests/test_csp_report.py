"""Issue #14: the page's CSP reports what it blocks to /api/csp-report, so a regression after a release gets noticed.
The log line holds the directive and what was blocked, as a keyword or an origin, never the page's address, the
blocked file's path or query, or the sample of script the browser sends. The door is limited per device."""
import io
import json
import logging

import pytest

from steward import logs
from steward.api.csp_report import MAX_REPORTS
from steward.auth.ratelimit import CSP_REPORT

SECRET_PAGE = "https://nas.tail1234.ts.net/b/zqxwv-family/transactions?q=zqxwvsearch"


@pytest.fixture
def written():
    stream = io.StringIO()
    logs.configure(stream)
    logging.getLogger("steward").setLevel(logging.DEBUG)
    return stream


def _legacy(directive="script-src-elem", blocked="https://evil.example/zqxwv/x.js?token=zqxwvtoken"):
    """report-uri's body, as Firefox and Safari send it."""
    return {"csp-report": {"document-uri": SECRET_PAGE, "referrer": SECRET_PAGE, "violated-directive": directive,
                           "effective-directive": directive, "original-policy": "default-src 'self'",
                           "blocked-uri": blocked, "script-sample": "zqxwv-sample()", "status-code": 200}}


def _reporting(directive="require-trusted-types-for", blocked="trusted-types-sink"):
    """The Reporting API's body (report-to), as Chromium sends it."""
    return [{"type": "csp-violation", "age": 10, "url": SECRET_PAGE, "user_agent": "x",
             "body": {"documentURL": SECRET_PAGE, "referrer": SECRET_PAGE, "effectiveDirective": directive,
                      "blockedURL": blocked, "sample": "Element innerHTML|<img src=zqxwv>", "disposition": "enforce",
                      "originalPolicy": "default-src 'self'", "statusCode": 200, "sourceFile": SECRET_PAGE,
                      "lineNumber": 3}}]


def _post(client, body, kind):
    return client.post("/api/csp-report", content=json.dumps(body), headers={"Content-Type": kind})


def test_a_report_logs_its_directive_and_blocked_origin_only(client, written):
    assert _post(client, _legacy(), "application/csp-report").status_code == 204
    assert _post(client, _reporting(), "application/reports+json").status_code == 204
    out = written.getvalue()
    assert "CSP blocked script-src-elem: https://evil.example" in out
    assert "CSP blocked require-trusted-types-for: trusted-types-sink" in out
    assert "zqxwv" not in out.lower() and "/b/" not in out and "x.js" not in out


@pytest.mark.parametrize("blocked,shown", [
    ("inline", "inline"), ("eval", "eval"), ("wasm-eval", "wasm-eval"), ("data", "data"), ("blob", "blob"),
    ("trusted-types-policy", "trusted-types-policy"), ("data:image/png;base64,zqxwv", "data"),
    ("https://cdn.example:8443/a.js", "https://cdn.example:8443"), ("https://nas.tail1234.ts.net/x", "this address"),
    ("chrome-extension://abcdef/x.js", "chrome-extension://abcdef"), ("zqxwv words", "other"), ("", "other"),
    ("https://[FD7A:115C::2]:8443/x", "https://[fd7a:115c::2]:8443"), ("http://[::1]:8420/x", "this address"),
])
def test_what_was_blocked_is_a_keyword_or_an_origin(client, written, blocked, shown):
    _post(client, _legacy(blocked=blocked), "application/csp-report")
    assert f"CSP blocked script-src-elem: {shown}\n" in written.getvalue()


def test_a_made_up_directive_or_body_is_logged_as_other_or_dropped(client, written):
    assert _post(client, _legacy(directive="zqxwv; drop table"), "application/csp-report").status_code == 204
    assert _post(client, {"nothing": 1}, "application/json").status_code == 204
    assert client.post("/api/csp-report", content=b"\xff not json").status_code == 204
    assert _post(client, [{"type": "deprecation", "body": {"id": "zqxwv"}}], "application/reports+json").status_code == 204
    out = written.getvalue()
    assert out.count("CSP blocked") == 1 and "CSP blocked other: https://evil.example" in out and "zqxwv" not in out


def test_a_batch_logs_at_most_its_cap(client, written):
    _post(client, _reporting() * (MAX_REPORTS + 5), "application/reports+json")
    assert written.getvalue().count("CSP blocked") == MAX_REPORTS


def test_the_door_is_limited_per_device(client, written):
    for _ in range(CSP_REPORT.tries):
        assert _post(client, _legacy(), "application/csp-report").status_code == 204
    assert _post(client, _legacy(), "application/csp-report").status_code == 429
    assert written.getvalue().count("CSP blocked") == CSP_REPORT.tries


def test_a_report_needs_no_sign_in_but_comes_only_from_stewards_pages(client):
    assert _post(client, _legacy(), "application/csp-report").status_code == 204
    r = client.post("/api/csp-report", content=json.dumps(_legacy()), headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
