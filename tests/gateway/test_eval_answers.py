"""The answers eval (spec 11.4, rulings 14, 15) with the fake Anthropic server: the cases are well formed, the demo
books hold a figure for nearly every case, a figure counts when the answer states it, and a run counts its spending
as channel eval with no book or person."""
import json
from datetime import timedelta

import anthropic
import pytest

from steward_boundary import tools as T
from steward_gateway.evals import answers as A
from steward_gateway.evals.answers_set import CASES, SPARE, Case, Figure
from steward_gateway.evals.rig import EVAL_NOW, EVAL_TODAY, demo_rig
from steward_gateway.ledger import Ledger
from steward_gateway.redact.patterns import PatternDetector
from tests.gateway.fake_anthropic import FakeAnthropic, Reply, text, tool_use
from tests.gateway.fakes import NameListDetector
from tests.servers import serve_in_thread


def test_thirty_two_well_formed_cases():
    assert len(CASES) == 32 and len({c.id for c in CASES + SPARE}) == 37
    assert sum(c.book == "household" for c in CASES) == 20 and sum(c.book == "parent" for c in CASES) == 12
    for c in CASES + SPARE:
        for name, inp in c.tools(EVAL_TODAY):
            assert T.validate_input(name, inp) == [], (c.id, name)
            assert c.book in T.BY_NAME[name].books, (c.id, name)
        assert "her " not in c.question.lower() and "she " not in c.question.lower()


@pytest.mark.parametrize("answer,figure,ok", [
    ("Your net worth is $918,412.37.", Figure("money", 91_841_237), True),
    ("About $918,400.", Figure("money", 91_841_237), True),
    ("Roughly $918k.", Figure("money", 91_841_237), True),
    ("About $0.9 million.", Figure("money", 91_841_237), False),
    ("Dining came to $1,204 against $1,180.", Figure("money", -118_000), True),
    ("You could retire comfortably at 61.", Figure("number", 61), True),
    ("You could retire at 611.", Figure("number", 61), False),
    ("There are no open flags.", Figure("number", 0), True),
    ("The 401(k) rate is 6%.", Figure("percent", 600), True),
    ("The 401(k) rate is 6.5 percent.", Figure("percent", 600), False),
])
def test_mentions(answer, figure, ok):
    assert A.mentions(answer, figure) is ok


@pytest.fixture
def rig_with(gw_cfg, tmp_path):
    def make(script):
        fake = FakeAnthropic(script)
        ledger = Ledger(tmp_path / "ledger.db", gw_cfg.timezone, gw_cfg.default_cap_cents, gw_cfg.max_cap_cents,
                        gw_cfg.default_model)
        return fake, ledger
    return make


def test_the_demo_books_have_a_figure_for_almost_every_case(rig_with, gw_cfg):
    fake, ledger = rig_with(lambda body, n: Reply([text("unused")]))
    with serve_in_thread(fake.app()) as url:
        client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
        with demo_rig(gw_cfg, client=client, detectors=[PatternDetector(), NameListDetector()], ledger=ledger) as rig:
            missing = [c.id for c in CASES if A.figures_for(rig, c, EVAL_TODAY) is None]
            spare_ok = [c.id for c in SPARE if A.figures_for(rig, c, EVAL_TODAY) is not None]
    assert len(missing) <= 3, f"no figure in the demo books for {missing}; swap them for {spare_ok} (in order)"
    assert fake.requests == []                      # working out the figures sends nothing


def net_worth_script(body, n):
    msgs = body["messages"]
    question = next(b["text"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                    for b in m["content"] if b.get("type") == "text")
    results = [b for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_result"]
    if not results:
        return Reply([tool_use("toolu_eval_01", "book_summary", {})], stop_reason="tool_use")
    cents = json.loads(results[-1]["content"])["net_worth_cents"]
    if "roughly" in question:
        cents += 10_000_000                          # a wrong answer: $100,000 off
    return Reply([text(f"Your net worth is ${cents / 100:,.2f}.")])


def test_a_run_through_the_fake_server_scores_and_counts_as_eval(rig_with, gw_cfg):
    def figs(results, today):
        return [Figure("money", results[0]["net_worth_cents"])]
    good = Case("t1", "household", "What's our net worth?", lambda today: [("book_summary", {})], figs)
    bad = Case("t2", "household", "What's our net worth, roughly?", lambda today: [("book_summary", {})], figs)
    fake, ledger = rig_with(net_worth_script)
    with serve_in_thread(fake.app()) as url:
        client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
        with demo_rig(gw_cfg, client=client, detectors=[PatternDetector(), NameListDetector()], ledger=ledger) as rig:
            result = A.run_answers(rig, [good, bad])
    assert [r.status for r in result.rows] == ["pass", "miss"] and result.passed == 1
    assert result.rows[1].missing and result.rows[1].missing[0].startswith("$")
    text_out = A.format_answers(result)
    assert "1 of 2 right" in text_out and "t2" in text_out
    with ledger._conn() as c:
        spend = c.execute("SELECT DISTINCT channel, book_id, user_id FROM spend").fetchall()
    assert [tuple(r) for r in spend] == [("eval", None, None)]
    assert {(r["channel"], r["book_id"]) for r in ledger.sent_since(EVAL_NOW - timedelta(days=400))} == {("eval", None)}


def test_the_command_asks_before_spending_and_sends_nothing_on_no(gw_cfg, monkeypatch):
    from typer.testing import CliRunner

    from steward_gateway import cli
    from steward_gateway.evals import rig as R
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(cli, "api_key", lambda cfg: "test-key-not-real")
    monkeypatch.setattr(R, "demo_rig", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nothing may be sent")))
    r = CliRunner().invoke(cli.app, ["eval", "answers"], input="n\n")
    assert r.exit_code == 1 and "about $3" in r.output and "of $10 left" in r.output


def test_the_command_without_a_key_says_how_to_set_one(gw_cfg, monkeypatch):
    from typer.testing import CliRunner

    from steward_gateway import cli
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    r = CliRunner().invoke(cli.app, ["eval", "answers", "--yes"])
    assert r.exit_code == 1 and "docs/guides/gateway.md" in r.output


# The real-API evals stay opt-in (controller addition to Task 16).
ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
REAL_CLIENT_FILES = {"src/steward_gateway/cli.py", "tests/gateway/test_live_smoke.py"}   # check, the evals, the smoke test


def test_nothing_in_the_default_run_ci_or_scripts_can_call_the_real_api():
    import re
    import tomllib
    opts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]["addopts"]
    assert "not live" in opts and "not perf" in opts            # the default run never selects the live test
    # Only the CLI (check, eval answers, bench) and the opt-in smoke test build a client that reaches Anthropic.
    builds = re.compile(r"\banthropic\.(Async)?Anthropic\(")
    found = {str(p.relative_to(ROOT)) for d in ("src", "tests") for p in (ROOT / d).rglob("*.py")
             if builds.search(p.read_text()) and p.name != "test_eval_answers.py"}
    assert {f for f in found if "base_url" not in (ROOT / f).read_text()} <= REAL_CLIENT_FILES
    for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        if "api.anthropic.com" in p.read_text() and p.name != "test_eval_answers.py":
            raise AssertionError(f"{p.relative_to(ROOT)} names the real API host")
    # No workflow, hook or deploy script runs the evals or the live test.
    scripts = [p for d in (".github", "deploy", "scripts") if (ROOT / d).exists() for p in (ROOT / d).rglob("*")
               if p.is_file() and p.suffix in {".yml", ".yaml", ".sh", ".ps1", ".bat", ".toml", ""}]
    scripts += [p for p in (ROOT / "Makefile", ROOT / "package.json", ROOT / "web" / "package.json") if p.exists()]
    for p in scripts:
        body = p.read_text(errors="ignore")
        for banned in ("eval answers", "steward-gateway bench", "-m live", "STEWARD_LIVE_ANTHROPIC"):
            assert banned not in body, f"{p.relative_to(ROOT)} runs an opt-in real-API command ({banned})"


def test_the_demo_rig_never_looks_up_a_host_but_loopback(rig_with, gw_cfg, monkeypatch):
    import socket
    real = socket.getaddrinfo

    def only_local(host, *a, **k):
        assert host in {"127.0.0.1", "localhost", None}, f"a lookup of {host}"
        return real(host, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", only_local)
    fake, ledger = rig_with(net_worth_script)
    case = Case("t1", "household", "What's our net worth?", lambda today: [("book_summary", {})],
                lambda results, today: [Figure("money", results[0]["net_worth_cents"])])
    with serve_in_thread(fake.app()) as url:
        client = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
        with demo_rig(gw_cfg, client=client, detectors=[PatternDetector(), NameListDetector()], ledger=ledger) as rig:
            assert A.run_answers(rig, [case]).passed == 1
