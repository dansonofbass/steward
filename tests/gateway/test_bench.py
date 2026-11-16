"""The bench (spec 12): first answer token for questions that need no tools and for one round of tools, against the
budgets, with the fake Anthropic server here (the real API only when JR runs steward-gateway bench)."""
import anthropic

from steward_gateway.evals import bench as B
from steward_gateway.evals.rig import demo_rig
from steward_gateway.ledger import Ledger
from steward_gateway.redact.patterns import PatternDetector
from tests.gateway.fake_anthropic import FakeAnthropic, Reply, text, tool_use
from tests.gateway.fakes import NameListDetector
from tests.servers import serve_in_thread


def script(body, n):
    msgs = body["messages"]
    question = next(b["text"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                    for b in m["content"] if b.get("type") == "text")
    answered = any(b.get("type") == "tool_result" for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                   for b in m["content"])
    if question in B.NO_TOOLS or answered:
        return Reply([text("Here is the answer.")])
    return Reply([tool_use("toolu_b_01", "book_summary", {})], stop_reason="tool_use")


def test_twenty_questions():
    assert len(B.NO_TOOLS) + len(B.BENCH_IDS) == 20


def test_a_bench_run_groups_by_rounds_and_meets_the_budgets_on_loopback(gw_cfg, tmp_path):
    fake = FakeAnthropic(script)
    ledger = Ledger(tmp_path / "ledger.db", gw_cfg.timezone, gw_cfg.default_cap_cents, gw_cfg.max_cap_cents,
                    gw_cfg.default_model)
    with serve_in_thread(fake.app()) as url:
        client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
        with demo_rig(gw_cfg, client=client, detectors=[PatternDetector(), NameListDetector()], ledger=ledger) as rig:
            result = B.run_bench(rig)
    assert len(result.rows) == 20
    assert len(result.group("no_tools")) == 6 and len(result.group("one_round")) == 14
    assert result.passes
    out = B.format_bench(result)
    assert "No tools: p50" in out and "One round of tools: p50" in out and "MISS" not in out
    assert B.as_json(result)["rows"][0]["question"] == B.NO_TOOLS[0]


def test_a_slow_group_or_an_empty_one_misses():
    fast = [B.BenchRow("q", 0, 900.0, 1200.0, 1, "end_turn")] * 5
    slow = [B.BenchRow("q", 1, 16_000.0, 20_000.0, 1, "end_turn")] * 5
    assert not B.BenchResult(fast + slow).passes
    assert not B.BenchResult(fast).passes                     # no sample for one round of tools
    assert "MISS" in B.format_bench(B.BenchResult(fast + slow))
