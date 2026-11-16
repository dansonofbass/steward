"""Claude Code over MCP (spec 7, rulings 1, 4-7): JSON-RPC over streamable HTTP with plain JSON replies, the local
token, no browser origins, the book's tools without merchant_detail, and every result checked, recorded on the NAS and
in the gateway's sent list before it is returned."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from steward_boundary.canonical import canonical
from steward_boundary.fingerprint import hashes_for
from steward_boundary.naming import THIS_MACHINE, name_in
from steward_gateway.app import create_gateway_app
from steward_gateway.mcp import grants as G
from steward_gateway.mcp import server as S
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.gateway.fakes import FakeNas, NameListDetector

GRANT = "stg1.ours." + "A" * 43
NOW = datetime(2026, 10, 21, 17, tzinfo=timezone.utc)
HOLDING = {"symbol": "VTI", "asset_class": "us_stock", "account": "Account 1", "value_cents": 100,
           "cost_basis_cents": None, "as_of": "2026-10-01"}


def holdings(symbol):
    return {"holdings": [{**HOLDING, "symbol": symbol}], "totals_by_asset_class": [{"asset_class": "us_stock",
                                                                                     "value_cents": 100}]}


@pytest.fixture
def mk(gw_cfg):
    write_private(gw_cfg.token_path, "c" * 64)
    G.add(gw_cfg, GRANT)
    token = G.mcp_token(gw_cfg, create=True)

    def make(nas, detectors=None):
        app = create_gateway_app(replace(gw_cfg, mcp=True), client=None, nas=nas, now=lambda: NOW,
                                 detectors=[PatternDetector(), NameListDetector()] if detectors is None else detectors)
        return TestClient(app), {"Authorization": f"Bearer {token}"}
    return make


def rpc(c, headers, method, params=None, id=1, alias="steward-1", extra=None):
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    return c.post(f"/mcp/{alias}", json=body, headers={**headers, **(extra or {})})


def sent(c):
    return c.app.state.shared.ledger.sent_since(NOW - timedelta(days=1))


def test_initialize_answers_with_a_known_revision(mk):
    c, h = mk(FakeNas())
    with c:
        r = rpc(c, h, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "claude-code", "version": "2"}}).json()
        assert r["id"] == 1 and r["result"]["protocolVersion"] == "2025-06-18"
        assert r["result"]["capabilities"] == {"tools": {"listChanged": False}}
        assert r["result"]["serverInfo"]["name"] == "steward" and "aliases" in r["result"]["instructions"]
        assert rpc(c, h, "initialize", {"protocolVersion": "2026-07-28"}).json()["result"]["protocolVersion"] == "2025-11-25"
        n = c.post("/mcp/steward-1", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
        assert n.status_code == 202 and n.content == b""
        assert rpc(c, h, "ping").json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
        assert rpc(c, h, "resources/list").json()["error"]["code"] == -32601


def test_malformed_requests(mk):
    c, h = mk(FakeNas())
    with c:
        assert c.post("/mcp/steward-1", content=b"{", headers={**h, "content-type": "application/json"}).json()["error"]["code"] == -32700
        assert c.post("/mcp/steward-1", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=h).json()["error"]["code"] == -32600
        assert c.post("/mcp/steward-1", json={"id": 1, "method": "ping"}, headers=h).json()["error"]["code"] == -32600
        assert c.get("/mcp/steward-1", headers=h).status_code == 405


def test_the_local_token_is_needed(mk):
    c, h = mk(FakeNas())
    with c:
        assert rpc(c, {}, "ping").status_code == 401
        assert rpc(c, {"Authorization": "Bearer nope"}, "ping").status_code == 401


def test_a_browser_origin_is_refused(mk):
    c, h = mk(FakeNas())
    with c:
        assert rpc(c, h, "ping", extra={"Origin": "https://evil.example"}).status_code == 403
        assert rpc(c, h, "ping", extra={"Origin": "http://localhost:3000"}).status_code == 200


def test_a_name_without_a_grant_here_is_404_and_the_books_address_is_never_a_path(mk):
    c, h = mk(FakeNas())
    with c:
        for alias in ("steward-2", "ours", "margaret-ellis"):
            r = rpc(c, h, "ping", alias=alias)
            assert (r.status_code, r.json()) == (404, {"error": S.NO_GRANT}), alias


def test_tools_list_is_the_books_tools_without_merchant_detail(mk):
    c, h = mk(FakeNas())
    with c:
        tools = rpc(c, h, "tools/list").json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "merchant_detail" not in names and "plan_result" in names and "accounts" in names
    accounts = next(t for t in tools if t["name"] == "accounts")
    assert accounts["inputSchema"]["properties"] == {"include_closed": {"type": "boolean"}}
    assert accounts["description"].startswith("Each account by alias")


def test_a_call_is_checked_recorded_and_returned(mk):
    nas = FakeNas(content=holdings("VTI"))
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "holdings", "arguments": {}}).json()["result"]
        rows = sent(c)
    assert r == {"content": [{"type": "text", "text": canonical(holdings("VTI")).decode()}], "isError": False}
    assert nas.calls == [("ours", GRANT, "holdings", {})]
    assert nas.finished == [(FakeNas.CALL_ID, "sent", None, None)]
    assert [(x["sha256"], x["book_id"], x["channel"]) for x in rows] == [(nas.part["sha256"], 1, "mcp")]


def test_a_stopped_result_is_logged_on_the_nas_and_never_returned(mk):
    nas = FakeNas(content=holdings("Tom Becker"))           # not a ticker: the symbol's schema refuses it
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "holdings", "arguments": {}}).json()["result"]
        rows = sent(c)
    assert r == {"content": [{"type": "text", "text": S.LINES["stopped_check"]}], "isError": True}
    (call_id, outcome, check, path), = nas.finished
    assert (call_id, outcome, check) == (FakeNas.CALL_ID, "stopped", "schema")
    assert path.startswith("parts[0].content") and "symbol" in path       # the path, never the value
    assert rows == [] and "Tom Becker" not in str(r)


def test_a_known_identifier_is_stopped_by_its_fingerprint(mk):
    nas = FakeNas(content=holdings("ASHBY"), hashes=sorted(hashes_for([("Ashby", True)], "4" * 32)))
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "holdings", "arguments": {}}).json()["result"]
    assert r["isError"] is True and nas.finished[0][1:3] == ("stopped", "fingerprint")


def test_a_refused_grant_is_an_error_result_not_a_crash(mk):
    nas = FakeNas(refuse=(401, "That grant isn't valid. A manager can issue a new one in Settings → Chat → Claude Code."))
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "debts", "arguments": {}}).json()["result"]
        assert r["isError"] is True and r["content"][0]["text"].startswith("That grant isn't valid.")
        assert rpc(c, h, "tools/list").json()["error"]["message"].startswith("That grant isn't valid.")
        assert sent(c) == []


def test_the_nas_away_says_so(mk):
    c, h = mk(FakeNas(away=True))
    with c:
        r = rpc(c, h, "tools/call", {"name": "debts", "arguments": {}}).json()["result"]
    assert r == {"content": [{"type": "text", "text": S.NAS_AWAY}], "isError": True}


def test_merchant_detail_and_unknown_tools_never_reach_the_nas(mk):
    nas = FakeNas()
    c, h = mk(nas)
    with c:
        for name in ("merchant_detail", "no_such_tool", 7):
            r = rpc(c, h, "tools/call", {"name": name, "arguments": {}}).json()["result"]
            assert r == {"content": [{"type": "text", "text": S.NOT_OFFERED}], "isError": True}
    assert nas.calls == []


def test_stop_chat_and_missing_models_refuse_before_the_nas(mk, gw_cfg):
    nas = FakeNas()
    c, h = mk(nas, detectors=[])
    with c:
        r = rpc(c, h, "tools/call", {"name": "debts", "arguments": {}}).json()["result"]
        assert r["content"][0]["text"] == name_in(S.LINES["privacy_not_ready"], THIS_MACHINE)
    gw_cfg.stop_flag_path.parent.mkdir(parents=True, exist_ok=True)
    gw_cfg.stop_flag_path.write_text("stopped\n")
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "debts", "arguments": {}}).json()["result"]
        assert r["content"][0]["text"] == name_in(S.LINES["stopped_by_gateway"], THIS_MACHINE)
    assert nas.calls == []


def test_a_result_that_doesnt_match_its_fingerprint_is_not_returned(mk):
    nas = FakeNas(bad_hash=True)
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "debts", "arguments": {}}).json()["result"]
    assert r["content"][0]["text"] == S.MISMATCH and nas.finished == []


def test_a_record_that_fails_returns_nothing(mk):
    nas = FakeNas(record=False)
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/call", {"name": "debts", "arguments": {}}).json()["result"]
        assert r["content"][0]["text"] == S.LINES["record_failed"] and sent(c) == []


def test_stop_chat_also_refuses_the_tool_list(mk, gw_cfg):
    nas = FakeNas()
    gw_cfg.stop_flag_path.parent.mkdir(parents=True, exist_ok=True)
    gw_cfg.stop_flag_path.write_text("stopped\n")
    c, h = mk(nas)
    with c:
        r = rpc(c, h, "tools/list").json()
        assert r["error"]["message"] == name_in(S.LINES["stopped_by_gateway"], THIS_MACHINE)
        assert rpc(c, h, "ping").json()["result"] == {}
