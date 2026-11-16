"""Claude Code over MCP (spec 7, rulings 1, 4-7, 20). JSON-RPC 2.0 over streamable HTTP with plain JSON replies (no
event stream, no sessions) at /mcp/<name> (steward-1, …: the name the gateway gave the grant, never the book's
address; ruling C1), on 127.0.0.1:8431 only (serving.PortSplit). Every request needs Claude
Code's local token; a request with a browser Origin that isn't this machine is refused. tools/list gives the book's
tools without merchant_detail; tools/call asks the NAS with the book's grant, runs the outgoing checks on the result,
has the NAS record its own copy (channel mcp), adds the hash to the sent list, and only then returns the result.
Claude Code's own model usage costs the gateway nothing. Logs carry the tool, timings and sizes only."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from contextlib import suppress
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from steward_boundary import tools as T
from steward_boundary.naming import THIS_MACHINE, name_in
from steward_boundary.canonical import canonical
from steward_boundary.protocol import LINES
from steward_gateway.checks import Part, Stopped, check_parts
from steward_gateway.logs import log_event
from steward_gateway.mcp import grants
from steward_gateway.mcp.nas import NasAway, NasRefused
from steward_gateway.secrets import read_private

log = logging.getLogger("steward_gateway.mcp")
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")
SERVER_INFO = {"name": "steward", "version": "3"}
INSTRUCTIONS = ("Steward's tools look up one family book's money: balances, cash flow, spending by category, holdings, "
                "debts, and the retirement plan or a parent's inventory, depending on the book. People, accounts and "
                "payees appear as aliases such as \"Person 1\" and \"Account 3\"; the real names stay in Steward. "
                "Amounts are in cents. Start with book_summary. Every tool is read-only.")
NOT_OFFERED = "Claude Code can't use that tool."
NAS_AWAY = "Steward isn't answering."
NO_NAS = "nas_url isn't set in gateway.toml on this machine."
MISMATCH = "Steward's answer didn't match its fingerprint, so nothing was returned."
NO_GRANT = "No grant by that name on this machine. Run steward-gateway mcp-grant list."
STARTING = "The gateway on this machine is still starting."
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _ok(rid, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})


def _err(rid, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _definition(spec: T.ToolSpec) -> dict:
    return {"name": spec.name, "description": spec.description, "inputSchema": spec.input_schema}


def mount_mcp(app, cfg, st, *, stopped, now) -> None:
    def token_ok(header: str | None) -> bool:
        token = read_private(cfg.mcp_token_path)
        return token is not None and hmac.compare_digest((header or "").encode("utf-8"),
                                                         f"Bearer {token}".encode("utf-8"))

    async def call_tool(slug: str, grant: str, params: dict) -> dict:
        name, args = params.get("name"), params.get("arguments") or {}
        if stopped():
            return _tool_error(name_in(LINES["stopped_by_gateway"], THIS_MACHINE))
        if st.ledger is None:
            return _tool_error(STARTING)
        if not st.detectors:
            return _tool_error(name_in(LINES["privacy_not_ready"], THIS_MACHINE))
        if not isinstance(name, str) or name == T.MERCHANT or name not in T.BY_NAME or not isinstance(args, dict):
            return _tool_error(NOT_OFFERED)
        if st.nas is None:
            return _tool_error(NO_NAS)
        t0 = time.monotonic()
        try:
            r = await st.nas.call(slug, grant, name, args)
        except NasAway:
            return _tool_error(NAS_AWAY)
        except NasRefused as e:
            return _tool_error(e.message)
        try:
            part = Part(r["part"]["part"], r["part"]["payload"])
            call_id, book_id = r["call_id"], r["book_id"]
            salt, hashes = r["fingerprints"]["salt"], frozenset(r["fingerprints"]["hashes"])
            ok = (part.part == "tool_result" and isinstance(part.payload, dict)
                  and part.payload.get("name") == name and part.payload.get("tool_use_id") == call_id
                  and isinstance(book_id, int) and not isinstance(book_id, bool) and isinstance(salt, str)
                  and part.sha256() == r["part"]["sha256"] and part.size() == r["part"]["bytes"])
        except (KeyError, TypeError, AttributeError):
            ok = False
        if not ok:
            log_event(log, "mcp.mismatch", level=logging.WARNING, tool=name)
            return _tool_error(MISMATCH)
        try:
            await asyncio.to_thread(check_parts, [part], detectors=st.detectors, salt=salt, hashes=hashes)
        except Stopped as e:
            with suppress(NasAway, NasRefused):
                await st.nas.finish(slug, grant, call_id, "stopped", e.check, e.path)
            log_event(log, "mcp.stopped", level=logging.WARNING, tool=name, check=e.check)
            return _tool_error(LINES["stopped_check"])
        try:
            rec = await st.nas.finish(slug, grant, call_id, "sent")
        except (NasAway, NasRefused):
            return _tool_error(LINES["record_failed"])
        if rec.get("recorded") is not True or rec.get("sha256") != part.sha256():
            return _tool_error(LINES["record_failed"])
        st.ledger.record_sent(now(), [(part.sha256(), part.size())], book_id, "mcp")
        log_event(log, "mcp.call", tool=name, bytes=part.size(), ms=int((time.monotonic() - t0) * 1000))
        return {"content": [{"type": "text", "text": canonical(part.payload["content"]).decode()}],
                "isError": bool(part.payload["is_error"])}

    @app.api_route("/mcp/{alias}", methods=["GET", "DELETE"])
    async def mcp_other(alias: str):
        return JSONResponse({"error": "Use POST."}, status_code=405, headers={"Allow": "POST"})

    @app.post("/mcp/{alias}")
    async def mcp(alias: str, request: Request):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in LOCAL_HOSTS:
            return JSONResponse({"error": "Not allowed."}, status_code=403)
        if not token_ok(request.headers.get("authorization")):
            return JSONResponse({"error": "Not allowed."}, status_code=401)
        grant = grants.load(cfg).get(alias)
        if grant is None:
            return JSONResponse({"error": NO_GRANT}, status_code=404)
        slug = grants.slug_of(grant)                      # only for the gateway's call to the NAS
        try:
            body = json.loads(await request.body())
        except ValueError:
            return _err(None, -32700, "Parse error")
        if isinstance(body, list):
            return _err(None, -32600, "Batches aren't supported.")
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return _err(body.get("id") if isinstance(body, dict) else None, -32600, "Invalid request")
        if "id" not in body:
            return Response(status_code=202)               # a notification
        rid, method = body["id"], body["method"]
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _ok(rid, {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                             "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                             "instructions": INSTRUCTIONS})
        if method == "ping":
            return _ok(rid, {})
        if method == "tools/list":
            if stopped():                                  # spec 5.4: stop-chat refuses all MCP
                return _err(rid, -32000, name_in(LINES["stopped_by_gateway"], THIS_MACHINE))
            if st.nas is None:
                return _err(rid, -32000, NO_NAS)
            try:
                info = await st.nas.tools(slug, grant)
            except NasAway:
                return _err(rid, -32000, NAS_AWAY)
            except NasRefused as e:
                return _err(rid, -32000, e.message)
            names = [n for n in info.get("tools", []) if n in T.BY_NAME and n != T.MERCHANT]
            return _ok(rid, {"tools": [_definition(T.BY_NAME[n]) for n in names]})
        if method == "tools/call":
            return _ok(rid, await call_tool(slug, grant, params))
        return _err(rid, -32601, "Method not found")
