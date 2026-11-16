"""Release spec 2026-11-05, section 6: Claude Code over MCP is off unless gateway.toml says mcp = true. Off, nothing
listens on mcp_port (not a refusing route: no socket at all), there are no /mcp routes, mcp-grant add refuses, and
/v1/health says so for Settings → Chat."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from steward_gateway import cli
from steward_gateway.app import create_gateway_app
from steward_gateway.config import ConfigError, GatewayConfig, load_config
from steward_gateway.mcp import grants as G
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from steward_gateway.serving import bind_sockets

TOKEN = "c" * 64
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _from_toml(tmp_path, text):
    (tmp_path / "c").mkdir(exist_ok=True)
    (tmp_path / "c" / "gateway.toml").write_text(text)
    return load_config(tmp_path / "c", tmp_path / "s")


def test_claude_code_is_off_unless_gateway_toml_says_mcp_true(tmp_path):
    assert GatewayConfig(tmp_path, tmp_path).mcp is False
    assert _from_toml(tmp_path, "").mcp is False
    assert _from_toml(tmp_path, "mcp = false\n").mcp is False
    assert _from_toml(tmp_path, "mcp = true\n").mcp is True


@pytest.mark.parametrize("value", ['"true"', "1", '"yes"', "0"])
def test_mcp_must_be_true_or_false(tmp_path, value):
    with pytest.raises(ConfigError, match="mcp in gateway.toml must be true or false."):
        _from_toml(tmp_path, f"mcp = {value}\n")


def test_off_only_the_gateways_own_address_is_bound(gw_cfg):
    socks = bind_sockets(replace(gw_cfg, port=0, mcp_port=0))
    try:
        assert [s.getsockname()[0] for s in socks] == ["127.0.0.1"] and len(socks) == 1
    finally:
        for s in socks:
            s.close()


def test_on_the_loopback_mcp_port_is_bound_too(gw_cfg):
    socks = bind_sockets(replace(gw_cfg, port=0, mcp_port=0, mcp=True))
    try:
        assert len(socks) == 2 and socks[1].getsockname()[0] == "127.0.0.1"
    finally:
        for s in socks:
            s.close()


def _client(cfg):
    write_private(cfg.token_path, TOKEN)
    return TestClient(create_gateway_app(cfg, client=None, detectors=[PatternDetector()]))


def test_off_there_is_no_mcp_route_and_health_says_so(gw_cfg):
    with _client(gw_cfg) as c:
        assert c.get("/v1/health", headers=AUTH).json()["mcp"] is False
        assert c.post("/mcp/steward-1", json={}).status_code == 404
    with _client(replace(gw_cfg, mcp=True)) as c:
        assert c.get("/v1/health", headers=AUTH).json()["mcp"] is True
        assert c.post("/mcp/steward-1", json={}).status_code == 401      # there, and wants Claude Code's token


def test_mcp_grant_add_refuses_while_claude_code_is_off(gw_cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: replace(gw_cfg, nas_url="https://steward.tail1234.ts.net"))
    r = CliRunner().invoke(cli.app, ["mcp-grant", "add"], input="stg1.ours." + "A" * 43 + "\n")
    assert r.exit_code == 1
    assert r.output.startswith("Claude Code is off on this machine. To turn it on, set mcp = true in gateway.toml")
    assert "Paste the grant" not in r.output and G.load(gw_cfg) == {}
