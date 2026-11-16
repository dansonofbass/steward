"""Spec 12, the gateway's share: outgoing checks on a 20 KB request < 80 ms, and recording a part, round trip,
< 50 ms (a WebSocket echo on loopback plus the book write is timed in test_advisor_budgets.py). Stand-in detectors;
the model's own time is the GPU budget in tests/gateway/test_models_eval.py."""
import os
import statistics
import time

import pytest

from steward_boundary.canonical import canonical
from steward_boundary.fingerprint import hashes_for
from steward_gateway.checks import Part, check_parts
from steward_gateway.redact.patterns import PatternDetector
from tests.gateway.fakes import NameListDetector

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


def test_outgoing_checks_on_a_20_kb_request_under_80_ms():
    account = {"account": "Account 1", "account_type": "checking", "tax_treatment": "none", "owner": "Joint",
               "balance_cents": 1_450_000, "as_of": "2026-10-12", "arrives": "feed", "sync_behind": False, "active": True}
    rows = [{**account, "account": f"Account {i}"} for i in range(1, 300)]
    parts = [Part("question", {"text": "How are our accounts doing compared with last year, and which is lowest?"}),
             Part("system", {"text": "Today is Tuesday, October 20, 2026. This is a household book. The person asking is Person 1."})]
    while sum(p.size() for p in parts) < 20_000:
        parts.append(Part("tool_result", {"tool_use_id": f"toolu_{len(parts):03d}", "name": "accounts", "is_error": False,
                                          "content": {"accounts": rows[:60]}}))
    assert sum(len(canonical(p.payload)) for p in parts) >= 20_000
    hashes = hashes_for([(f"Alder{i} Ashgrove{i}", True) for i in range(300)], "4" * 32)
    det = [PatternDetector(), NameListDetector()]
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        check_parts(parts, detectors=det, salt="4" * 32, hashes=hashes)
        times.append((time.perf_counter() - t0) * 1000)
    _check("outgoing_checks_20kb", statistics.median(times) * FACTOR, 80)


def _instant_ollama():
    import json as _json

    import httpx2

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx2.Response(200, json={"models": [{"name": "qwen3.5:9b-q4_K_M"}]})
        if request.url.path == "/api/show":
            return httpx2.Response(200, json={"capabilities": ["completion", "thinking"]})
        prompt = _json.loads(request.content)["prompt"]
        n = sum(1 for line in prompt.splitlines() if line[:1].isdigit() and '. "' in line)
        rows = [{"i": i, "category": "dining", "merchant": "", "confidence": 0.9} for i in range(1, n + 1)]
        return httpx2.Response(200, json={"response": _json.dumps({"rows": rows})})
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def test_the_gateways_share_of_categorizing_one_row_and_fifty(tmp_path):
    """Ruling 16: with an instant Ollama, the gateway adds < 20 ms to one row and < 100 ms to a batch of 50."""
    from fastapi.testclient import TestClient

    from steward_gateway.app import create_gateway_app
    from steward_gateway.categorize import Categorizer
    from steward_gateway.config import GatewayConfig
    from steward_gateway.secrets import write_private
    cfg = GatewayConfig(tmp_path / "c", tmp_path / "s")
    write_private(cfg.token_path, "c" * 64)
    cat = Categorizer("http://127.0.0.1:11434", "qwen3.5:9b-q4_K_M", http=_instant_ollama())
    app = create_gateway_app(cfg, detectors=[PatternDetector()], client=None, categorizer=cat)
    auth = {"Authorization": "Bearer " + "c" * 64}
    one = {"description": "SQ *MAPLE LEAF CAFE", "amount_cents": -1840}
    with TestClient(app) as c:
        c.post("/v1/categorize", json=one, headers=auth)
        singles, batches = [], []
        for _ in range(20):
            t0 = time.perf_counter()
            assert c.post("/v1/categorize", json=one, headers=auth).status_code == 200
            singles.append((time.perf_counter() - t0) * 1000)
        for _ in range(10):
            t0 = time.perf_counter()
            assert c.post("/v1/categorize/batch", json={"rows": [one] * 50}, headers=auth).status_code == 200
            batches.append((time.perf_counter() - t0) * 1000)
    _check("categorize_one_gateway_share", statistics.median(singles) * FACTOR, 20)
    _check("categorize_batch_gateway_share", statistics.median(batches) * FACTOR, 100)
