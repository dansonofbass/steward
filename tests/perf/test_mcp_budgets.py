"""Ruling 16: an MCP tools/call through the gateway (stand-in detectors) and the real NAS on loopback, for the
non-plan tools over the demo household, < 300 ms p95."""
from steward import clock
import os
import statistics
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from steward.advisor import grants as NG
from steward.advisor.state import set_chat_on
from steward.app import create_app
from steward.demo import seed, seed_people
from steward_gateway.app import create_gateway_app
from steward_gateway.config import GatewayConfig
from steward_gateway.mcp import grants as GG
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.gateway.fakes import NameListDetector
from tests.servers import serve_in_thread

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
TOOLS = [("book_summary", {}), ("accounts", {"include_closed": False}), ("cash_flow", {"months": 12, "by": "category"}),
         ("spending_by_category", {"start": "2026-07-01", "end": "2026-09-30", "compare_previous": True}),
         ("recurring", {}), ("holdings", {}), ("debts", {})]


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


def test_mcp_tool_call_under_300_ms_p95(settings, books, ddb, ours, tmp_path):
    from steward.auth.users import find_user
    now = clock.now()
    with Session(books.engine_for(ours)) as db:
        seed(db, years=5, seed=7)
        db.commit()
    seed_people(ddb, ours.id)
    jr = find_user(ddb, "alex")
    with Session(books.engine_for(ours)) as db:
        set_chat_on(db, True, jr.id, now)
        db.commit()
    _, text = NG.issue(ddb, book_id=ours.id, slug="ours", user_id=jr.id, by=jr.id, now=now)
    ddb.commit()
    cfg = GatewayConfig(tmp_path / "gwc", tmp_path / "gws", mcp=True)
    write_private(cfg.token_path, "c" * 64)
    settings.advisor_token_path.write_text("c" * 64)              # the NAS's side of the pairing
    token = GG.mcp_token(cfg, create=True)
    alias = GG.add(cfg, text)
    times = []
    with serve_in_thread(create_app(settings, books)) as nas_url:
        gw = create_gateway_app(replace(cfg, nas_url=nas_url), client=None,
                                detectors=[PatternDetector(), NameListDetector()])
        with TestClient(gw) as c:
            h = {"Authorization": f"Bearer {token}"}
            for round_ in range(6):
                for name, args in TOOLS:
                    t0 = time.perf_counter()
                    r = c.post(f"/mcp/{alias}", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                             "params": {"name": name, "arguments": args}})
                    ms = (time.perf_counter() - t0) * 1000
                    assert r.json()["result"]["isError"] is False, r.text
                    if round_:                       # the first round warms the caches
                        times.append(ms)
    p95 = statistics.quantiles(times, n=20, method="inclusive")[-1]
    _check("mcp_tool_call_p95", p95 * FACTOR, 300)
