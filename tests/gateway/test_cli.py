import json
import re
from datetime import datetime, timedelta, timezone

import anthropic
from typer.testing import CliRunner

from steward_gateway import cli
from steward_gateway.ledger import Ledger
from tests.gateway.fake_anthropic import FakeAnthropic, Reply
from tests.servers import serve_in_thread

runner = CliRunner()


def test_pair_arms_the_window(gw_cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    r = runner.invoke(cli.app, ["pair", "ABCD-EFGH-JKMN-PQRS"])
    assert r.exit_code == 0 and gw_cfg.pending_pair_path.exists()
    assert "10 minutes" in r.output


def test_pair_with_no_code_shows_one_and_arms_it(gw_cfg, monkeypatch):
    from steward_gateway.pairing import claim
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    r = runner.invoke(cli.app, ["pair"])
    m = re.search(r"Type this code in Steward: ([A-Z0-9]{3}-[A-Z0-9]{3})\nIt works for 10 minutes\.", r.output)
    assert r.exit_code == 0 and m
    expires = datetime.fromisoformat(json.loads(gw_cfg.pending_pair_path.read_text())["expires"])
    assert len(claim(gw_cfg, m[1].lower(), expires - timedelta(minutes=1))) == 64


def test_stop_and_start_chat(gw_cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    assert runner.invoke(cli.app, ["stop-chat"]).exit_code == 0 and gw_cfg.stop_flag_path.exists()
    assert runner.invoke(cli.app, ["start-chat"]).exit_code == 0 and not gw_cfg.stop_flag_path.exists()


def test_check_without_a_key_says_how_to_set_one(gw_cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    r = runner.invoke(cli.app, ["check"])
    assert r.exit_code == 1 and "docs/guides/gateway.md" in r.output


def test_check_key_sends_one_max_tokens_0_request_and_shows_the_cap(gw_cfg):
    fake = FakeAnthropic(lambda b, n: Reply([]))
    with serve_in_thread(fake.app()) as url:
        client = anthropic.Anthropic(api_key="test-key-not-real", base_url=url, max_retries=0)
        line = cli.check_key(gw_cfg, client, now=datetime(2026, 10, 20, 17, tzinfo=timezone.utc))
    assert line.startswith("The API key works. The fixed instructions are ")
    assert line.endswith("This month: $0 of $10 used.") or "of $10 used." in line
    assert [r["max_tokens"] for r in fake.requests] == [0]
    sent = Ledger(gw_cfg.ledger_path, gw_cfg.timezone, 1000, 10_000, "claude-opus-5-5").sent_since(
        datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert [s["channel"] for s in sent] == ["check"] and sent[0]["book_id"] is None


def _check_with(gw_cfg, monkeypatch, reply):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(cli, "api_key", lambda cfg: "test-key-not-real")
    fake = FakeAnthropic(lambda b, n: reply)
    with serve_in_thread(fake.app()) as url:
        real = anthropic.Anthropic
        monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: real(**{**kw, "base_url": url, "max_retries": 0}))
        return runner.invoke(cli.app, ["check"])


def test_check_says_what_anthropic_rejected(gw_cfg, monkeypatch):
    r = _check_with(gw_cfg, monkeypatch, Reply([], status=400, error_type="invalid_request_error",
                                              error_message="max_tokens: must be positive"))
    assert r.exit_code == 1
    assert "Anthropic didn't answer: BadRequestError: max_tokens: must be positive" in r.output, r.output


def test_check_without_a_message_keeps_the_old_wording(gw_cfg, monkeypatch):
    r = _check_with(gw_cfg, monkeypatch, Reply([], status=400, error_body="nope"))
    assert r.exit_code == 1 and "Anthropic didn't answer: BadRequestError.\n" in r.output, r.output


def test_bench_asks_before_spending(gw_cfg, monkeypatch):
    from steward_gateway.evals import rig as R
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(cli, "api_key", lambda cfg: "test-key-not-real")
    monkeypatch.setattr(R, "demo_rig", lambda *a, **k: (_ for _ in ()).throw(AssertionError("nothing may be sent")))
    r = runner.invoke(cli.app, ["bench"], input="n\n")
    assert r.exit_code == 1 and "about $2" in r.output
