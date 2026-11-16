"""Spec 7 and 11.3 for Claude Code: the real NAS app on a loopback port with both synthetic books and their full sets
of identifiers, the real gateway with the stand-in detectors, and an MCP client calling every offered tool as a
manager and as a viewer in both books. It fails if any returned result carries any identifier of either book, if any
returned result isn't in the book's log byte for byte with channel mcp, or if the gateway's sent list holds a hash no
book recorded."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.advisor import grants as NG
from steward.advisor.mcp import offered
from steward.advisor.monitor import crosscheck
from steward.app import create_app
from steward.db.models import AdvisorOutgoing
from steward_boundary.canonical import canonical, sha256_hex
from steward_gateway.app import create_gateway_app
from steward_gateway.config import GatewayConfig
from steward_gateway.ledger import Ledger
from steward_gateway.mcp import grants as GG
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.advisor.identities import all_identifiers
from tests.advisor.test_leak_e2e import FIRST, NOW, SECOND, leaks_whole, strings, world  # noqa: F401 - world is a fixture
from tests.gateway.fakes import NameListDetector
from tests.servers import serve_in_thread


class SentList:
    def __init__(self, ledger):
        self.ledger = ledger

    def sent_since(self, since):
        return {"sent": self.ledger.sent_since(since)}


def test_every_mcp_result_is_clean_and_in_the_log(world, settings, books, ddb, tmp_path, monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: NOW)
    calls = {name: inp for name, inp in FIRST + SECOND}           # one input per tool is enough here
    cfg = GatewayConfig(tmp_path / "gwc", tmp_path / "gws", mcp=True)
    write_private(cfg.token_path, "c" * 64)
    settings.advisor_token_path.write_text("c" * 64)              # the NAS's side of the pairing
    token = GG.mcp_token(cfg, create=True)
    ledger = Ledger(cfg.ledger_path, cfg.timezone, cfg.default_cap_cents, cfg.max_cap_cents, cfg.default_model)
    returned: list[tuple[int, str]] = []
    with serve_in_thread(create_app(settings, books)) as nas_url:
        from dataclasses import replace
        cfg = replace(cfg, nas_url=nas_url)
        gw = create_gateway_app(cfg, client=None, ledger=ledger, now=lambda: NOW,
                                detectors=[PatternDetector(), NameListDetector()])
        with TestClient(gw) as c:
            for kind, (book, users) in world.items():
                for uid in users:
                    _, text = NG.issue(ddb, book_id=book.id, slug=book.slug, user_id=uid, by=users[0], now=NOW)
                    ddb.commit()
                    alias = GG.add(cfg, text)
                    h = {"Authorization": f"Bearer {token}"}
                    listed = c.post(f"/mcp/{alias}", headers=h,
                                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
                    assert sorted(t["name"] for t in listed) == sorted(offered(book.kind))
                    for name in offered(book.kind):
                        r = c.post(f"/mcp/{alias}", headers=h, json={
                            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": name, "arguments": calls.get(name, {})}}).json()["result"]
                        assert r["isError"] is False or json.loads(r["content"][0]["text"]).get("error"), (name, r)
                        returned.append((book.id, r["content"][0]["text"]))
    assert len(returned) >= 2 * (len(offered("household")) + len(offered("parent")))
    found = [s for _, t in returned for s in strings(json.loads(t), [])]
    for kind, value in all_identifiers():
        hits = [s for s in found if leaks_whole(s, kind, value)]
        assert hits == [], (kind, value, hits[:3])
    for book_id, text in returned:
        book = next(b for b in books.books() if b.id == book_id)
        with Session(books.engine_for(book)) as db:
            logged = [json.loads(p) for p in db.scalars(select(AdvisorOutgoing.payload)
                                                        .where(AdvisorOutgoing.channel == "mcp"))]
        assert any(canonical(p["content"]).decode() == text for p in logged), text[:80]
    assert crosscheck(books, SentList(ledger), NOW + timedelta(minutes=1)) == 0
    assert all(r["channel"] == "mcp" for r in ledger.sent_since(NOW - timedelta(days=1)))
