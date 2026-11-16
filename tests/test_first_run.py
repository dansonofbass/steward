"""Release spec 2026-11-05, section 6: until the first person exists, every route but /api/health and /api/setup*
answers 503 with the line that says what to do, and the page's own files still load so /setup can. Once someone
exists, the gate stays open. The gate is on outside STEWARD_ENV=test; these tests turn it on."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from steward import clock
from steward.api.first_run import NEEDS_SETUP, gate_on, passes
from steward.app import create_app
from steward.auth import setup_link

BASE = "https://nas.tail1234.ts.net"


@pytest.fixture
def web(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Steward</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    return dist


def gated(settings, books, web=None):
    if web is not None:
        settings = settings.model_copy(update={"web_dir": web})
    return TestClient(create_app(settings, books, first_run_gate=True), base_url=BASE)


def test_with_nobody_yet_only_health_setup_and_the_page_answer(settings, books, web):
    with gated(settings, books, web) as c:
        for method, path in (("GET", "/api/auth/me"), ("POST", "/api/auth/login"), ("GET", "/api/b/ours/accounts"),
                             ("GET", "/api/books"), ("POST", "/api/auth/forgot"), ("GET", "/api/nope"),
                             ("POST", "/api/auth/passkeys/login/options")):
            r = c.request(method, path, json={})
            assert (r.status_code, r.json()) == (503, {"error": NEEDS_SETUP}), (method, path)
            assert r.headers["x-content-type-options"] == "nosniff"          # the refusal carries the headers
        r = c.get("/openapi.json")                                          # no route map for strangers
        assert not r.headers["content-type"].startswith("application/json") and "paths" not in r.text
        assert c.get("/api/health").status_code == 200
        assert c.post("/api/setup/check", json={"token": "x"}).status_code == 400
        assert c.get("/setup").status_code == 200 and "Steward" in c.get("/setup").text
        assert c.get("/assets/app.js").status_code == 200 and c.get("/").status_code == 200


def test_the_gate_opens_for_good_once_the_first_person_is_made(settings, books):
    with gated(settings, books) as c:
        with Session(books.directory) as ddb:
            token = setup_link.issue(ddb, clock.now())
        r = c.post("/api/setup", json={"token": token, "username": "casey", "display_name": "Casey",
                                       "email": "casey@example.com", "password": "pw-first-person-1"})
        assert r.status_code == 200
        assert c.get("/api/auth/me").status_code == 200
        c.cookies.clear()
        assert c.get("/api/auth/me").status_code == 401                     # now an ordinary sign-in wall


def test_the_gate_is_on_outside_tests(settings):
    assert gate_on(settings.model_copy(update={"env": "prod"}), None) is True
    assert gate_on(settings, None) is False
    assert gate_on(settings, True) is True and gate_on(settings.model_copy(update={"env": "prod"}), False) is False


@pytest.mark.parametrize("method,path,ok", [
    ("GET", "/api/health", True), ("POST", "/api/setup", True), ("POST", "/api/setup/check", True),
    ("GET", "/setup", True), ("HEAD", "/assets/x.js", True), ("GET", "/", True), ("GET", "/b/ours", True),
    ("POST", "/", False), ("GET", "/api", False), ("GET", "/api/setupx", False), ("GET", "/api/auth/me", False),
])
def test_passes_lets_through_only_health_setup_and_page_reads(method, path, ok):
    assert passes(method, path) is ok
