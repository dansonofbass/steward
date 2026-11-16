"""Task 8.5's wiring audit: each place the gateway's parts meet is pinned by a test. Issued tokens reach every
redaction and check, the real detectors sit behind Guarded, serve builds the app the tests build, a NAS that goes away
cancels the turn, and a request that was sent and then cancelled counts at its reservation."""
import asyncio
import re

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from steward_gateway import app as app_mod
from steward_gateway import cli
from steward_gateway.app import create_gateway_app
from steward_gateway.checks import Part, Stopped, check_parts
from steward_gateway.ledger import Ledger
from steward_gateway.loop import run_turn
from steward_gateway.redact import Guarded, Span
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.gateway.fake_anthropic import Reply, text
from tests.gateway.fakes import NameListDetector
from tests.gateway.test_loop import NOW, Stream, StubClient, run_stub, start_frame, statuses, turn
from tests.waiting import CEILING, wait_until

TOKEN = "c" * 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Tagger:
    """Tags every match of a pattern as a name, the way GLiNER reads "Person 1" or a bracket as a person."""
    name = "gliner"

    def __init__(self, pattern):
        self.re = re.compile(pattern)

    def detect(self, text):
        return [Span(m.start(), m.end(), "[name]", "gliner") for m in self.re.finditer(text)]


ALIASES = Tagger(r"Person \d+")
BRACKETED = Tagger(r"\[[a-z ]+\]")


def issued_start(question, issued, asker="Person 2"):
    s = start_frame(question=question, asker=asker)
    s["issued"] = list(issued)
    return s


# --- Task 9: check_parts passes `issued` to the model pass on the question path ---------------------------------------
def test_check_parts_protects_issued_aliases_in_the_question():
    parts = [Part("question", {"text": "How old is Person 1?"})]
    check_parts(parts, detectors=[ALIASES], salt="2" * 32, hashes=frozenset(), issued={"Person 1"})
    with pytest.raises(Stopped) as e:
        check_parts(parts, detectors=[ALIASES], salt="2" * 32, hashes=frozenset(), issued=frozenset())
    assert (e.value.check, e.value.path) == ("model", "parts[0].text")


# --- Task 11: run_turn passes protocol.issued(start) to redact and that plus its own brackets to the checks ----------
def test_the_turn_keeps_issued_aliases_and_redacts_the_rest(gw_cfg):
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]),
                                 issued_start("Did Person 1 pay Person 7?", ["Person 1"]), detectors=[ALIASES])
    assert done["stop"] == "end_turn"
    assert nas.of("redacted")[0]["text"] == "Did Person 1 pay [name]?"     # Person 7 wasn't issued
    assert fake.requests[0]["messages"][-2]["content"][0]["text"] == "Did Person 1 pay [name]?"


def test_the_question_check_in_a_turn_needs_the_issued_list(gw_cfg, monkeypatch):
    """A detector that reads "Person 1" as a name: the turn's check on the question passes with the issued list and
    stops without it (final review, Task 9/8)."""
    from steward_gateway import loop as loop_mod
    start = issued_start("How old is Person 1?", ["Person 1"])
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]), start, detectors=[ALIASES])
    assert done["stop"] == "end_turn"
    assert fake.requests[0]["messages"][-2]["content"][0]["text"] == "How old is Person 1?"

    real = loop_mod.check_parts
    monkeypatch.setattr(loop_mod, "check_parts", lambda parts, **kw: real(parts, **{**kw, "issued": frozenset()}))
    done, fake, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]), start, detectors=[ALIASES])
    assert (done["stop"], done["check"]) == ("stopped_check", "model")
    assert fake.requests == [] and "sent" not in nas.kinds()


def test_the_turn_counts_its_own_brackets_as_issued(gw_cfg):
    # The second pass reads the redacted question; the "[name]" the gateway inserted must not stop the turn.
    done, _, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]), start_frame(question="Did Tom Becker call?"),
                              detectors=[NameListDetector(), BRACKETED])
    assert nas.of("redacted")[0]["text"] == "Did [name] call?"
    assert done["stop"] == "end_turn"


def test_a_typed_bracket_is_not_issued_by_the_nas(gw_cfg):
    done, _, nas, _, _ = turn(gw_cfg, lambda b, n: Reply([text("ok")]), start_frame(question="Did [payee] call?"),
                              detectors=[BRACKETED])
    assert nas.of("redacted")[0]["text"] == "Did [name] call?"    # replaced, since only the NAS's tokens are kept


# --- Task 12: the app hands the START frame to run_turn, and the preview takes the same issued tokens -------------
def _app(gw_cfg, detectors, client=None, ledger=None):
    write_private(gw_cfg.token_path, TOKEN)
    return create_gateway_app(gw_cfg, detectors=detectors, client=client, ledger=ledger, now=lambda: NOW)


def test_the_app_turn_uses_the_issued_tokens(gw_cfg):
    from tests.gateway.fake_anthropic import FakeAnthropic
    from tests.servers import serve_in_thread
    fake = FakeAnthropic(lambda body, n: Reply([text("ok")]))
    with serve_in_thread(fake.app()) as url:
        api = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
        with TestClient(_app(gw_cfg, [ALIASES], client=api)) as c, c.websocket_connect("/v1/turn", headers=AUTH) as ws:
            ws.send_json(issued_start("Did Person 1 pay Person 7?", ["Person 1"]))
            frames = []
            while not frames or frames[-1]["type"] != "done":
                frames.append(ws.receive_json())
                if frames[-1]["type"] == "record":
                    ws.send_json({"type": "recorded", "seq": frames[-1]["seq"]})
    assert [f["text"] for f in frames if f["type"] == "redacted"] == ["Did Person 1 pay [name]?"]
    assert frames[-1]["stop"] == "end_turn"


def test_the_preview_takes_the_issued_tokens(gw_cfg):
    with TestClient(_app(gw_cfg, [ALIASES])) as c:
        r = c.post("/v1/redact", json={"text": "Did Person 1 pay Person 7?", "issued": ["Person 1"]}, headers=AUTH)
        assert r.json()["text"] == "Did Person 1 pay [name]?"
        assert c.post("/v1/redact", json={"text": "Did Person 1 pay?"}, headers=AUTH).json()["text"] == "Did [name] pay?"
        for bad in (["Margaret"], "Person 1", [1]):
            assert c.post("/v1/redact", json={"text": "x", "issued": bad}, headers=AUTH).status_code == 422


# --- The real detectors are wrapped in Guarded ------------------------------------------------------------------------
def test_the_real_detectors_are_wrapped_in_guarded(gw_cfg, monkeypatch):
    made = []

    class Spy(Guarded):
        def __init__(self, detectors):
            made.append(list(detectors))
            super().__init__(detectors)
    real = PatternDetector()
    monkeypatch.setattr(app_mod, "load_real_detectors", lambda: ([real], None))
    monkeypatch.setattr(app_mod, "Guarded", Spy)
    with TestClient(_app(gw_cfg, None)) as c:
        assert c.post("/v1/redact", json={"text": "call 714-555-0102"}, headers=AUTH).json()["text"] == "call [phone]"
    assert made == [[real]]


# --- serve builds the app with create_gateway_app and hands it to serving.run; run uses no uvicorn log config -------
def test_serve_builds_the_app_and_runs_uvicorn_without_its_log_config(gw_cfg, monkeypatch):
    import uvicorn

    from steward_gateway import logs, serving
    built, ran, configs = [], [], []
    sentinel = object()
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(cli, "api_key", lambda cfg: None)
    monkeypatch.setattr(logs, "setup_logging", lambda: None)
    monkeypatch.setattr(app_mod, "create_gateway_app", lambda cfg, **kw: built.append((cfg, kw)) or sentinel)
    real_run = serving.run
    monkeypatch.setattr(serving, "run", lambda cfg, app: ran.append((cfg, app)))
    from typer.testing import CliRunner
    r = CliRunner().invoke(cli.app, ["serve"])
    assert r.exit_code == 0, r.output
    assert built == [(gw_cfg, {})]
    assert ran == [(gw_cfg, sentinel)]

    class FakeServer:
        def __init__(self, config):
            configs.append(config)

        def run(self, sockets=None):
            configs.append(sockets)

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr(serving, "bind_sockets", lambda cfg: ["main", "side"])
    real_run(gw_cfg, sentinel)
    assert configs[0].log_config is None and configs[1] == ["main", "side"]


# --- A WebSocket disconnect cancels run_turn, and the request it sent counts at its reservation ----------------------
def test_a_nas_that_goes_away_cancels_the_turn(gw_cfg):
    cancelled = []

    async def hang():
        try:
            await asyncio.Event().wait()        # a request that never answers: only a cancel can end it
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    ledger = Ledger(gw_cfg.ledger_path, gw_cfg.timezone, 1000, gw_cfg.max_cap_cents, gw_cfg.default_model)
    app = _app(gw_cfg, [PatternDetector()], client=StubClient(lambda **kw: Stream(enter=hang)), ledger=ledger)
    with TestClient(app) as c:
        with c.websocket_connect("/v1/turn", headers=AUTH) as ws:
            ws.send_json(start_frame())
            while (f := ws.receive_json())["type"] != "record":
                pass
            ws.send_json({"type": "recorded", "seq": f["seq"]})
            while ws.receive_json()["type"] != "sent":
                pass
            # The socket closes but the test's websocket context is still open, so nothing here tears the handler
            # down: only the handler's own disconnect watch can cancel the turn (the old handler noticed at its next
            # send or receive, which never came while the request hung).
            ws.close()
            wait_until(lambda: cancelled, "the turn to be cancelled after the NAS went away")
        wait_until(lambda: "reserved" not in statuses(ledger), "the reservation to settle")
    assert cancelled == [True]
    assert statuses(ledger) == ["settled"]
    assert ledger.state(NOW, gw_cfg)["reserved_cents"] == 0 and ledger.state(NOW, gw_cfg)["spent_cents"] > 0


def test_a_sent_request_cancelled_with_no_usage_settles_at_the_reservation(gw_cfg):
    entered = asyncio.Event()

    async def hang():
        entered.set()                           # the request is in flight (sent and recorded just before it)
        await asyncio.Event().wait()
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(enter=hang))

    async def go():
        task = asyncio.create_task(run_turn(start_frame(), nas, deps))
        await asyncio.wait_for(entered.wait(), CEILING)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert statuses(ledger) == ["settled"]
    with ledger._conn() as conn:
        assert conn.execute("SELECT cost_nd FROM spend").fetchone()[0] == ledger.reserved[0]


def _connection_error(cause):
    async def enter():
        try:
            raise cause
        except Exception as e:
            raise anthropic.APIConnectionError(request=None) from e
    return enter


def test_a_request_that_never_connected_is_released(gw_cfg):
    for cause in (httpx2.ConnectError("refused"), httpx2.ConnectTimeout("no route")):
        ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(enter=_connection_error(cause)))
        assert asyncio.run(run_turn(start_frame(), nas, deps))["stop"] == "api_error"
        assert statuses(ledger)[-1] == "released"


def test_a_request_dropped_after_it_was_sent_settles_at_the_reservation(gw_cfg):
    ledger, deps, nas = run_stub(gw_cfg, lambda **kw: Stream(enter=_connection_error(httpx2.ReadError("reset"))))
    assert asyncio.run(run_turn(start_frame(), nas, deps))["stop"] == "api_error"
    assert statuses(ledger) == ["settled"]


# --- The chat client never retries (final review, finding 3) ----------------------------------------------------------
def test_the_chat_client_never_retries(gw_cfg):
    """A retry after an attempt that was sent and timed out could end in ConnectError, which reads as "never
    connected" and releases a reservation for a request Anthropic may have billed. One attempt per request."""
    client = app_mod.make_client(gw_cfg, "test-key-not-real")
    try:
        assert client.max_retries == 0
    finally:
        asyncio.run(client.close())
