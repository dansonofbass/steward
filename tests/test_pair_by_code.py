"""Pairing by code from the browser (guided setup spec 6)."""
import json
import logging
from datetime import datetime, timezone

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from steward.advisor.gateway import GatewayClient
from steward.app import create_app
from steward.services.statements.client import HttpStatementClient
from steward_gateway.pairing import arm
from tests.advisor.rig import gateway_rig
from tests.factories import login, make_person
from tests.gateway.fake_anthropic import Reply, text as reply_text

CODE = "K7M-4QX"
FIXED = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def people(ddb, ours):
    make_person(ddb, "pat", [(ours.id, "manager")])
    make_person(ddb, "vee", [(ours.id, "viewer")])


def nas(settings, books, url, http=None) -> TestClient:
    return TestClient(create_app(settings.model_copy(update={"gateway_url": url}), books, http=http),
                      base_url="https://nas.tail1234.ts.net")


def test_pairing_writes_the_token_and_swaps_the_live_client(settings, books, people, tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr("steward_gateway.app._now", lambda: FIXED)       # the rig's gateway reads this clock
    with gateway_rig(tmp_path / "gw", lambda b, n: Reply([reply_text("ok")])) as rig:
        rig.cfg.token_path.unlink()
        arm(rig.cfg, CODE, FIXED)
        with nas(settings, books, rig.url) as c:
            rt = c.app.state.advisor
            assert rt.client is None
            login(c, "pat")
            r = c.post("/api/install/gateway/pair", json={"code": "k7m 4qx"})
            assert r.json() == {"line": "Paired with the gateway."}
            token = settings.advisor_token_path.read_text()
            assert oct(settings.advisor_token_path.stat().st_mode & 0o777) == "0o600"
            assert isinstance(rt.client, GatewayClient) and rt.client.token == token and rt.monitor.client is rt.client
            assert rt.monitor.poll()["key_set"] is True                     # the monitor polls the new client
            assert c.app.state.model._headers["Authorization"] == f"Bearer {token}"
            assert isinstance(c.app.state.statements.client, HttpStatementClient)
    assert "K7M" not in caplog.text and "4QX" not in caplog.text
    with Session(books.directory) as s:
        for table in ("app_setting", "directory_meta", "directory_event"):
            assert "K7M4QX" not in json.dumps([list(map(str, row)) for row in s.execute(text(f"SELECT * FROM {table}"))])


def test_shutdown_closes_the_clients_the_app_made_and_never_a_stand_in(settings, books):
    """Teardown closes the categorizer and PDF reader clients the app made, the ones a pairing swapped in included, and
    never an object a test stood in their place (it may have no close at all)."""
    closed = []

    def watch(client, name):
        client.close = lambda: closed.append(name)

    class StandIn:
        last_error, missed = None, False

    with TestClient(create_app(settings, books)) as c:
        st = c.app.state
        watch(st.model, "first model")
        watch(st.statements.client, "first reader")
        st.use_gateway(GatewayClient("http://gw.test:8430", "t" * 64))
        assert closed == ["first model", "first reader"]
        watch(st.model, "model")
        watch(st.statements.client, "reader")
        st.model, st.statements.client = StandIn(), StandIn()
    assert closed == ["first model", "first reader", "reader", "model"]


def answering(status, body):
    def handler(request):
        assert request.url.path == "/v1/pair"
        return httpx2.Response(status, content=body if isinstance(body, bytes) else json.dumps(body).encode())
    return httpx2.Client(transport=httpx2.MockTransport(handler))


@pytest.mark.parametrize("case,status,body,code,words", [
    ("403", 403, {"error": "x", "tries_left": 4}, 422, "That code doesn't match. 4 tries left."),
    ("403-one", 403, {"error": "x", "tries_left": 1}, 422, "That code doesn't match. 1 try left."),
    ("403-last", 403, {"error": "x", "tries_left": 0}, 422, "That code doesn't match. Run steward-gateway pair again."),
    ("403-no-tries", 403, {"error": "x"}, 422, "That code doesn't match."),
    ("404", 404, {"error": "x"}, 422, "No pairing is waiting on the gateway. Run steward-gateway pair again."),
    ("500", 500, {"error": "x"}, 503, "The gateway didn't answer at http://gw.test:8430."),
    ("not-json", 403, b"<html>", 422, "That code doesn't match."),
])
def test_each_gateway_answer_has_plain_words(settings, books, people, case, status, body, code, words):
    with nas(settings, books, "http://gw.test:8430", http=answering(status, body)) as c:
        login(c, "pat")
        r = c.post("/api/install/gateway/pair", json={"code": CODE})
        assert (r.status_code, r.json()) == (code, {"error": words})
        assert not settings.advisor_token_path.exists()


def test_a_bad_code_and_a_viewer_are_refused_before_any_call(settings, books, people):
    def handler(request):
        raise AssertionError("the gateway must not be called")
    with nas(settings, books, "http://gw.test:8430", http=httpx2.Client(transport=httpx2.MockTransport(handler))) as c:
        login(c, "pat")
        r = c.post("/api/install/gateway/pair", json={"code": "AB"})
        assert (r.status_code, r.json()) == (422, {"error": "Enter the code the gateway shows."})
        login(c, "vee")
        assert c.post("/api/install/gateway/pair", json={"code": CODE}).status_code == 404


def test_no_address_answers_409(settings, books, people):
    with nas(settings, books, None) as c:
        login(c, "pat")
        r = c.post("/api/install/gateway/pair", json={"code": CODE})
        assert (r.status_code, r.json()) == (409, {"error": "Add STEWARD_GATEWAY_URL to Steward's settings file first."})


def test_five_tries_per_fifteen_minutes(settings, books, people, fake_clock):
    with nas(settings, books, "http://gw.test:8430", http=answering(403, {"tries_left": 4})) as c:
        login(c, "pat")
        for _ in range(5):
            assert c.post("/api/install/gateway/pair", json={"code": CODE}).status_code == 422
        assert c.post("/api/install/gateway/pair", json={"code": CODE}).status_code == 429


def test_the_advisor_scheduler_starts_when_the_first_pairing_lands(settings, books, monkeypatch):
    started = []

    class FakeScheduler:
        def __init__(self, *a, name="", **k):
            self.name = name

        def start(self):
            started.append(self.name)

        def stop(self):
            pass
    monkeypatch.setattr("steward.app.Scheduler", FakeScheduler)
    app = create_app(settings.model_copy(update={"env": "prod", "sync_hours": 0}), books)   # no lifespan: nothing runs
    assert app.state.advisor_scheduler is None
    app.state.use_gateway(GatewayClient("http://gw.test:8430", "t" * 64))
    assert started == ["steward-advisor"] and app.state.advisor.client.url == "http://gw.test:8430"
    app.state.advisor.client.close()
