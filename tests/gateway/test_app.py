"""The gateway's HTTP and WebSocket surface, with stand-in detectors and the fake Anthropic server."""
import os
import re
from dataclasses import replace
from datetime import datetime, timezone

import anthropic
import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from steward_gateway.app import create_gateway_app
from steward_gateway.mcp import grants as G
from steward_gateway.pairing import arm
from steward_gateway.prompt import prewarm_payload
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.gateway.fake_anthropic import FakeAnthropic, Reply, text
from tests.gateway.fakes import FakeNas, FakeOllama, NameListDetector
from tests.gateway.test_loop import start_frame
from tests.servers import serve_in_thread

TOKEN = "c" * 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake():
    f = FakeAnthropic(lambda body, n: Reply([text("You spent $812.40 on dining.")]))
    with serve_in_thread(f.app()) as url:
        f.url = url
        yield f


def client_for(gw_cfg, fake, paired=True, with_client=True, detectors=None, ollama=None):
    if paired:
        write_private(gw_cfg.token_path, TOKEN)
    api = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=fake.url, max_retries=0) if with_client else None
    app = create_gateway_app(gw_cfg, detectors=[PatternDetector(), NameListDetector()] if detectors is None else detectors,
                             client=api, now=lambda: NOW, ollama=ollama)
    return TestClient(app)


def test_every_route_needs_the_token(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:
        assert c.get("/v1/health").status_code == 401
        assert c.get("/v1/health", headers={"Authorization": "Bearer " + "d" * 64}).status_code == 401
        r = c.get("/v1/health", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["key_set"] and body["redaction_ready"] and not body["chat_stopped"]
        assert body["budget"]["cap_cents"] == 1000 and body["budget"]["model"] == "claude-opus-5-5"


def test_a_non_ascii_token_is_refused_not_an_error(gw_cfg, fake):
    """hmac.compare_digest raises TypeError on a str that isn't ASCII; the header is compared as bytes (final review,
    Task 12)."""
    bad = {"Authorization": "Bearer ".encode() + "é".encode("latin-1") * 64}
    with client_for(gw_cfg, fake) as c:
        r = c.get("/v1/health", headers=bad)
        assert (r.status_code, r.json()) == (401, {"error": "Not allowed."})
        with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/v1/turn", headers=bad) as ws:
            ws.receive_json()
        assert e.value.code == 1008


def test_unpaired_says_so(gw_cfg, fake):
    with client_for(gw_cfg, fake, paired=False) as c:
        r = c.get("/v1/health", headers=AUTH)
        assert (r.status_code, r.json()) == (503, {"error": "{gateway} isn't paired with Steward yet."})


def test_redact_returns_text_and_edits(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:
        r = c.post("/v1/redact", json={"text": "Did Tom Becker call 714-555-0102?"}, headers=AUTH)
        assert r.json()["text"] == "Did [name] call [phone]?"
        assert [e["layer"] for e in r.json()["edits"]] == ["gliner", "presidio"]
        assert c.post("/v1/redact", json={"text": "x" * 4001}, headers=AUTH).status_code == 422


def test_redact_refuses_without_the_models(gw_cfg, fake):
    with client_for(gw_cfg, fake, detectors=[]) as c:
        r = c.post("/v1/redact", json={"text": "hello"}, headers=AUTH)
        assert (r.status_code, r.json()["error"]) == (503, "Chat is paused because {gateway}'s privacy check isn't ready.")
        assert c.get("/v1/health", headers=AUTH).json()["redaction_ready"] is False


def test_a_turn_over_the_websocket(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c, c.websocket_connect("/v1/turn", headers=AUTH) as ws:
        ws.send_json(start_frame())
        frames = []
        while True:
            f = ws.receive_json()
            frames.append(f)
            if f["type"] == "record":
                ws.send_json({"type": "recorded", "seq": f["seq"]})
            if f["type"] == "done":
                break
    assert frames[-1]["stop"] == "end_turn" and len(fake.requests) == 1


def test_a_cancel_mid_request_stops_the_turn_and_done_carries_the_charge(gw_cfg, fake):
    """Final review, finding 1: a cancel frame that arrives while a request streams is acted on at once. The request
    was sent, so it counts at its full reservation, and the done frame says so for the NAS to record."""
    import asyncio

    from tests.gateway.test_loop import Stream, StubClient

    async def hang():
        await asyncio.Event().wait()
    write_private(gw_cfg.token_path, TOKEN)
    app = create_gateway_app(gw_cfg, detectors=[PatternDetector(), NameListDetector()],
                             client=StubClient(lambda **kw: Stream(enter=hang)), now=lambda: NOW)
    with TestClient(app) as c, c.websocket_connect("/v1/turn", headers=AUTH) as ws:
        ws.send_json(start_frame())
        while (f := ws.receive_json())["type"] != "sent":
            if f["type"] == "record":
                ws.send_json({"type": "recorded", "seq": f["seq"]})
        ws.send_json({"type": "cancel", "reason": "stopped"})
        done = ws.receive_json()        # it comes only if the cancel stopped the hanging request (the suite's
                                        # 120 s ceiling fails the test otherwise)
    assert (done["type"], done["stop"], done["requests"]) == ("done", "cancelled", 1)
    assert done["cost_nd"] > 0


def test_a_websocket_without_the_token_is_refused(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/v1/turn") as ws:
                ws.receive_json()


def test_stop_chat_refuses_turns(gw_cfg, fake):
    gw_cfg.stop_flag_path.write_text("")
    with client_for(gw_cfg, fake) as c, c.websocket_connect("/v1/turn", headers=AUTH) as ws:
        assert c.get("/v1/health", headers=AUTH).json()["chat_stopped"] is True
        ws.send_json(start_frame())
        assert ws.receive_json()["stop"] == "stopped_by_gateway"
    assert fake.requests == []


def test_settings_and_usage(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:
        assert c.get("/v1/settings", headers=AUTH).json() == {
            "cap_cents": 1000, "max_cap_cents": 10_000, "model": "claude-opus-5-5",
            "models": ["claude-opus-5-5", "claude-sonnet-5-5"]}
        assert c.post("/v1/settings", json={"cap_cents": 2500, "model": "claude-sonnet-5-5"}, headers=AUTH).status_code == 200
        assert c.get("/v1/settings", headers=AUTH).json()["cap_cents"] == 2500
        r = c.post("/v1/settings", json={"cap_cents": 20_000}, headers=AUTH)
        assert (r.status_code, r.json()["error"]) == (422, "Choose a budget from $1 to $100.")
        assert c.get("/v1/usage", headers=AUTH).json()["month"] == "2026-10"


def test_settings_save_both_or_neither(gw_cfg, fake):
    """The cap and the model are both checked before either is saved (final review, Task 12)."""
    with client_for(gw_cfg, fake) as c:
        r = c.post("/v1/settings", json={"cap_cents": 2500, "model": "claude-haiku-5-5"}, headers=AUTH)
        assert (r.status_code, r.json()["error"]) == (422, "Choose Claude Opus 5.5 or Claude Sonnet 5.5.")
        r = c.post("/v1/settings", json={"cap_cents": 20_000, "model": "claude-sonnet-5-5"}, headers=AUTH)
        assert (r.status_code, r.json()["error"]) == (422, "Choose a budget from $1 to $100.")
        r = c.post("/v1/settings", json={"cap_cents": "2500", "model": "claude-sonnet-5-5"}, headers=AUTH)
        assert r.status_code == 422
        s = c.get("/v1/settings", headers=AUTH).json()
        assert (s["cap_cents"], s["model"]) == (1000, "claude-opus-5-5")
        assert c.post("/v1/settings", json={"model": "claude-sonnet-5-5"}, headers=AUTH).json()["model"] == "claude-sonnet-5-5"
        assert c.get("/v1/settings", headers=AUTH).json()["cap_cents"] == 1000


def test_a_refused_prewarm_logs_anthropics_reason(gw_cfg, caplog):
    import logging
    from steward_gateway.logs import ScrubFilter
    caplog.handler.addFilter(ScrubFilter())
    caplog.set_level(logging.INFO, logger="steward_gateway")
    f = FakeAnthropic(lambda body, n: Reply([], status=400, error_type="invalid_request_error",
                                            error_message="system.0.cache_control: not allowed here"))
    with serve_in_thread(f.app()) as url:
        f.url = url
        with client_for(gw_cfg, f) as c:
            plan = c.post("/v1/prewarm/plan", json={"book_id": 1, "user_id": 2}, headers=AUTH).json()
            r = c.post("/v1/prewarm", json={"book_id": 1, "user_id": 2, "sha256": plan["sha256"]}, headers=AUTH)
    assert r.json() == {"sent": False}
    assert ("prewarm.failed error_type=BadRequestError error_kind=invalid_request_error "
            "error_message=system.0.cache_control: not allowed here") in caplog.text, caplog.text


def test_prewarm_sends_the_prefix_once_per_five_minutes(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:
        plan = c.post("/v1/prewarm/plan", json={"book_id": 1, "user_id": 2}, headers=AUTH).json()
        assert plan["due"] is True and plan["payload"] == prewarm_payload()
        r = c.post("/v1/prewarm", json={"book_id": 1, "user_id": 2, "sha256": plan["sha256"]}, headers=AUTH)
        assert r.json()["sent"] is True
        assert c.post("/v1/prewarm/plan", json={"book_id": 1, "user_id": 2}, headers=AUTH).json()["due"] is False
        assert c.post("/v1/prewarm", json={"book_id": 1, "user_id": 2, "sha256": plan["sha256"]}, headers=AUTH).json() == {"sent": False}
        assert c.post("/v1/prewarm", json={"book_id": 1, "user_id": 2, "sha256": "0" * 64}, headers=AUTH).status_code == 409
        sent = c.get("/v1/sent", params={"since": "2026-10-20T00:00:00+00:00"}, headers=AUTH).json()["sent"]
        assert [(s["sha256"], s["channel"], s["book_id"]) for s in sent] == [(plan["sha256"], "prewarm", 1)]
    assert len(fake.requests) == 1
    body = fake.requests[0]
    assert body["max_tokens"] == 0 and "stream" not in body and body["messages"] == [{"role": "user", "content": "warmup"}]


def test_pair_needs_no_token_but_an_armed_code(gw_cfg, fake):
    with client_for(gw_cfg, fake, paired=False) as c:
        assert c.post("/v1/pair", json={"code": "ABCD-EFGH-JKMN-PQRS"}).status_code == 404
        arm(gw_cfg, "ABCD-EFGH-JKMN-PQRS", NOW)
        r = c.post("/v1/pair", json={"code": "abcd efgh jkmn pqrs"})
        assert r.status_code == 200 and len(r.json()["token"]) == 64
        assert c.get("/v1/health", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200


def test_the_gateway_refuses_to_start_with_a_readable_env_file(gw_cfg, fake):
    gw_cfg.env_path.write_text("ANTHROPIC_API_KEY=test-key-not-real\n")
    os.chmod(gw_cfg.env_path, 0o644)
    from steward_gateway.secrets import SecretFileError
    with pytest.raises(SecretFileError):
        with TestClient(create_gateway_app(gw_cfg, detectors=[PatternDetector()])):
            pass


# Controller addition: what start-up must do before the app accepts a turn.

def _start(gw_cfg, **kw):
    return TestClient(create_gateway_app(gw_cfg, detectors=[PatternDetector()], **kw))


def test_start_up_refuses_a_readable_token_file(gw_cfg):
    from steward_gateway.secrets import SecretFileError
    gw_cfg.token_path.write_text(TOKEN)
    os.chmod(gw_cfg.token_path, 0o644)
    with pytest.raises(SecretFileError):
        with _start(gw_cfg):
            pass


def test_start_up_refuses_a_readable_history_key(gw_cfg):
    from steward_gateway.secrets import SecretFileError
    gw_cfg.history_key_path.write_text("a" * 64)
    os.chmod(gw_cfg.history_key_path, 0o644)
    with pytest.raises(SecretFileError):
        with _start(gw_cfg):
            pass


def test_start_up_reads_the_key_through_the_permission_check(gw_cfg, monkeypatch):
    import steward_gateway.app as app_module
    calls = []
    real = app_module.api_key
    monkeypatch.setattr(app_module, "api_key", lambda cfg: calls.append(cfg) or real(cfg))
    with _start(gw_cfg):
        pass
    assert calls == [gw_cfg]


def test_start_up_sets_up_scrubbing_logs(gw_cfg):
    import logging
    from steward_gateway.logs import ScrubFilter
    for name in ("httpx", "anthropic"):
        logging.getLogger(name).filters[:] = []
    with _start(gw_cfg):
        for name in ("httpx", "anthropic"):
            assert any(isinstance(f, ScrubFilter) for f in logging.getLogger(name).filters), name
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(name)
            assert lg.propagate and not lg.handlers, name
        assert any(isinstance(f, ScrubFilter) for h in logging.getLogger().handlers for f in h.filters)


def test_start_up_settles_reservations_left_by_a_crash_before_any_turn(gw_cfg):
    from steward_gateway.ledger import Ledger
    ledger = Ledger(gw_cfg.ledger_path, gw_cfg.timezone, gw_cfg.default_cap_cents, gw_cfg.max_cap_cents,
                    gw_cfg.default_model)
    ledger.reserve(now=NOW, book_id=1, user_id=2, turn_id="t_00000000000000a1", channel="turn",
                   model="claude-opus-5-5", estimate_nd=3_000_000_000)
    assert ledger.state(NOW, gw_cfg)["spent_cents"] == 0
    write_private(gw_cfg.token_path, TOKEN)
    with TestClient(create_gateway_app(gw_cfg, detectors=[PatternDetector()], ledger=ledger, now=lambda: NOW)) as c:
        budget = c.get("/v1/health", headers=AUTH).json()["budget"]
    assert budget["spent_cents"] == 300


def test_the_title_route_and_health_use_ollama(gw_cfg, fake):
    o = FakeOllama(title="Dining this year and last")
    with client_for(gw_cfg, fake, ollama=o) as client:
        r = client.post("/v1/title", json={"text": "Are we spending more on dining?"}, headers=AUTH)
        assert r.json() == {"title": "Dining this year and last"} and o.asked == ["Are we spending more on dining?"]
        assert client.get("/v1/health", headers=AUTH).json()["ollama"] is True
        assert client.post("/v1/title", json={"text": 5}, headers=AUTH).status_code == 422


def test_the_title_route_refuses_a_request_without_the_token(gw_cfg, fake):
    """Final review, Task 3: a title is made from a redacted question, but only the paired NAS may ask for one."""
    o = FakeOllama(title="Dining this year and last")
    with client_for(gw_cfg, fake, ollama=o) as client:
        for headers in ({}, {"Authorization": "Bearer " + "d" * 64}):
            r = client.post("/v1/title", json={"text": "Are we spending more on dining?"}, headers=headers)
            assert (r.status_code, r.json()) == (401, {"error": "Not allowed."})
    assert o.asked == []


def test_no_title_and_no_ollama_call_while_ollama_is_away(gw_cfg, fake):
    """Release spec 2026-11-05, section 7: with no local model a title comes back empty at once; the NAS keeps the
    question's first words."""
    o = FakeOllama(title="Dining this year and last", up=False)
    with client_for(gw_cfg, fake, ollama=o) as client:
        r = client.post("/v1/title", json={"text": "Are we spending more on dining?"}, headers=AUTH)
        assert r.json() == {"title": None} and o.asked == []
        assert client.get("/v1/health", headers=AUTH).json()["ollama"] is False


def test_health_says_what_the_gateway_runs_on(gw_cfg, fake):
    with client_for(gw_cfg, fake, ollama=FakeOllama(accelerated=True)) as client:
        h = client.get("/v1/health", headers=AUTH).json()
    assert (h["accelerator"], h["ollama_accelerated"]) == ("cpu", True)       # stand-in detectors have no device
    with client_for(gw_cfg, fake, detectors=[]) as client:
        h = client.get("/v1/health", headers=AUTH).json()
    assert (h["accelerator"], h["ollama_accelerated"]) == (None, None)        # no models, nothing loaded in Ollama


# S17: every gateway route but pairing needs Steward's pairing token. The sweep reads app.routes, so a route added later
# is swept without anyone adding a case.
NOT_ALLOWED = (401, {"error": "Not allowed."})
WRONG = {"Authorization": "Bearer " + "d" * 64}
# The only routes that may answer a request without the pairing token, each with its one answer. Pairing takes a
# one-time code instead. Claude Code's address answers GET and DELETE with "Use POST." before any token check
# (mcp/server.py); that answer carries nothing.
OPEN_ANSWERS = {
    ("POST", "/v1/pair"): (422, {"error": "That request wasn't understood."}),
    ("GET", "/mcp/{alias}"): (405, {"error": "Use POST."}),
    ("DELETE", "/mcp/{alias}"): (405, {"error": "Use POST."}),
}


def token_sweep(app):
    """(kind, method, path) for each method of each HTTP route, and for each WebSocket route."""
    for route in app.routes:
        if isinstance(route, APIWebSocketRoute):
            yield "ws", "WS", route.path
        elif isinstance(route, APIRoute):
            for method in sorted(route.methods):
                yield "http", method, route.path
        else:
            yield "other", type(route).__name__, getattr(route, "path", "?")


def routes_open_without_the_token(app, client) -> list[str]:
    """Every route that answers a missing or a wrong token with anything but its refusal: 401 over HTTP (or the route's
    one answer in OPEN_ANSWERS), and a 1008 close on a WebSocket."""
    found = []
    for kind, method, path in token_sweep(app):
        url = re.sub(r"\{[^}]+\}", "steward-1", path)
        if kind == "other":
            found.append(f"{method} {path} isn't a route the sweep can check")
            continue
        for headers in ({}, WRONG):
            if kind == "ws":
                try:
                    with client.websocket_connect(url, headers=headers):
                        pass
                    found.append(f"WS {path} accepted the socket")
                except WebSocketDisconnect as e:
                    if e.code != 1008:
                        found.append(f"WS {path} closed with {e.code}")
                continue
            r = client.request(method, url, json={}, headers=headers)
            try:
                got = (r.status_code, r.json())
            except ValueError:
                got = (r.status_code, r.text)
            if got != OPEN_ANSWERS.get((method, path), NOT_ALLOWED):
                found.append(f"{method} {path} answered {r.status_code}")
    return found


def test_every_route_but_pairing_refuses_a_missing_or_wrong_token(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:         # paired: unpaired, every route answers 503
        swept = [(m, p) for _, m, p in token_sweep(c.app)]
        assert ("POST", "/v1/pair") in swept and ("WS", "/v1/turn") in swept
        assert len([x for x in swept if x not in OPEN_ANSWERS]) >= 16
        assert routes_open_without_the_token(c.app, c) == []


def test_claude_codes_route_takes_its_own_token_not_the_pairing_token(gw_cfg):
    write_private(gw_cfg.token_path, TOKEN)
    G.add(gw_cfg, "stg1.ours." + "A" * 43)
    own = {"Authorization": f"Bearer {G.mcp_token(gw_cfg, create=True)}"}
    assert own != AUTH
    app = create_gateway_app(replace(gw_cfg, mcp=True), detectors=[PatternDetector(), NameListDetector()],
                             client=None, nas=FakeNas(), now=lambda: NOW)
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    with TestClient(app) as c:
        for headers in ({}, AUTH, WRONG):
            r = c.post("/mcp/steward-1", json=ping, headers=headers)
            assert (r.status_code, r.json()) == NOT_ALLOWED, headers
        assert c.post("/mcp/steward-1", json=ping, headers=own).json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
        assert ("http", "POST", "/mcp/{alias}") in set(token_sweep(app))
        assert routes_open_without_the_token(app, c) == []


def test_the_token_sweep_notices_an_open_route(gw_cfg, fake):
    with client_for(gw_cfg, fake) as c:
        @c.app.get("/v1/rogue")
        async def rogue():
            return {}
        assert routes_open_without_the_token(c.app, c) == ["GET /v1/rogue answered 200"] * 2
