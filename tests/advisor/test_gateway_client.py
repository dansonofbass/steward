import json

import httpx2
import pytest

from steward.advisor.gateway import GatewayClient, GatewayRefused, GatewayUnavailable, new_code, pair
from steward_gateway.pairing import arm
from tests.advisor.rig import gateway_rig
from tests.gateway.fake_anthropic import Reply, text


def test_the_client_reads_health_redacts_and_changes_settings(tmp_path):
    with gateway_rig(tmp_path, lambda b, n: Reply([text("ok")])) as rig:
        h = rig.client.health()
        assert h["key_set"] and h["redaction_ready"] and h["budget"]["cap_cents"] == 1000
        r = rig.client.redact("Did Tom Becker call?")
        assert r["text"] == "Did [name] call?"
        rig.client.set_settings(cap_cents=2000)
        assert rig.client.settings()["cap_cents"] == 2000
        assert rig.client.usage()["cap_cents"] == 2000
        with pytest.raises(GatewayRefused) as e:
            rig.client.set_settings(cap_cents=50)
        assert e.value.message == "Choose a budget from $1 to $100."


def test_a_wrong_token_and_a_missing_gateway(tmp_path):
    with gateway_rig(tmp_path, lambda b, n: Reply([text("ok")])) as rig:
        with pytest.raises(GatewayRefused) as e:
            GatewayClient(rig.url, "f" * 64).health()
        assert e.value.status == 401
    with pytest.raises(GatewayUnavailable):
        GatewayClient("http://127.0.0.1:9", "f" * 64, timeout=0.5).health()
    with pytest.raises(GatewayUnavailable):
        GatewayClient("http://127.0.0.1:9", "f" * 64, timeout=0.5).connect(timeout=0.5)


def test_pairing_from_the_nas(tmp_path):
    from datetime import datetime, timezone
    code = new_code()
    assert len(code) == 19 and code.count("-") == 3
    with gateway_rig(tmp_path, lambda b, n: Reply([text("ok")])) as rig:
        rig.cfg.token_path.unlink()
        arm(rig.cfg, code, datetime.now(timezone.utc))
        token_file = tmp_path / "advisor.token"
        with httpx2.Client() as http:
            assert pair(token_file, rig.url, code, http=http, sleep=lambda s: None, wait_s=5) == "paired"
        assert oct(token_file.stat().st_mode & 0o777) == "0o600"
        assert GatewayClient(rig.url, token_file.read_text()).health()["key_set"] is True
        with httpx2.Client() as http:
            assert pair(token_file, rig.url, code, http=http, sleep=lambda s: None, wait_s=0) == "timeout"


def test_title_asks_the_gateway_and_returns_its_title():
    def handler(request):
        assert request.url.path == "/v1/title" and json.loads(request.content) == {"text": "Q"}
        return httpx2.Response(200, json={"title": "Savings this month"})
    c = GatewayClient("http://gw", "t" * 64, http=httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert c.title("Q") == "Savings this month"
