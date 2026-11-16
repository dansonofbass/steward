"""Opt-in smoke test against the real Anthropic API (marked live). JR runs it by hand on the gateway after setting up the
key: STEWARD_LIVE_ANTHROPIC=1 uv run pytest -q -m live tests/gateway/test_live_smoke.py
It is skipped unless that variable is set and the gateway's env file exists; agents never run it, and no release check
does. It costs about a cent: one free token count and two max_tokens 0 requests."""
import os
from datetime import datetime, timezone

from pathlib import Path

import pytest

from steward_gateway.config import ConfigError, default_dirs

pytestmark = pytest.mark.live
try:
    ENV_FILE = default_dirs()[0] / "gateway.env"     # only its existence is checked here, never its contents
except ConfigError:                                  # run as the wrong user: skip, don't break collection
    ENV_FILE = Path("/nonexistent/gateway.env")


@pytest.mark.skipif(os.environ.get("STEWARD_LIVE_ANTHROPIC") != "1" or not ENV_FILE.exists(),
                    reason="opt-in: set STEWARD_LIVE_ANTHROPIC=1 on the gateway with the key in gateway.env")
def test_the_key_works_and_the_prefix_caches():
    import anthropic

    from steward_boundary.canonical import canonical, sha256_hex
    from steward_gateway.config import load_config
    from steward_gateway.ledger import Ledger
    from steward_gateway.prices import cost_nd, settle_price
    from steward_gateway.prompt import prewarm_body, prewarm_payload
    from steward_gateway.secrets import api_key
    CFG = load_config()
    client = anthropic.Anthropic(api_key=api_key(CFG), max_retries=2)
    body = prewarm_body("claude-opus-5-5")
    payload = prewarm_payload()
    tokens = client.messages.count_tokens(model=body["model"], tools=body["tools"], system=body["system"],
                                          messages=body["messages"]).input_tokens
    assert tokens >= 512, "the prefix is too short to cache on Opus 5.5"
    ledger = Ledger(CFG.ledger_path, CFG.timezone, CFG.default_cap_cents, CFG.max_cap_cents, CFG.default_model)
    reads = []
    for _ in range(2):
        rid = ledger.reserve(now=datetime.now(timezone.utc), book_id=None, user_id=None, turn_id=None, channel="check",
                             model=body["model"], estimate_nd=tokens * 6250)
        msg = client.messages.create(**body)
        usage = msg.usage.to_dict(mode="json")
        ledger.settle(rid, cost_nd(usage, settle_price(CFG, msg.model, usage)))
        ledger.record_sent(datetime.now(timezone.utc), [(sha256_hex(payload), len(canonical(payload)))], None, "check")
        reads.append(usage.get("cache_read_input_tokens") or 0)
    print(f"\nLIVE prefix tokens {tokens}; cache reads {reads}")
    assert reads[1] > 0, "the second request should read the cached prefix"
