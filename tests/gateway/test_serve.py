"""One uvicorn server over the Tailscale socket and the loopback MCP socket (ruling 6): /mcp only on the loopback
port, everything else only on the gateway's port."""
import socket
from dataclasses import replace

import httpx2

from steward_gateway.app import create_gateway_app
from steward_gateway.serving import PortSplit, serve_in_thread
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private


def _bound():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    return s


def test_mcp_answers_only_on_the_loopback_port(gw_cfg):
    write_private(gw_cfg.token_path, "c" * 64)
    main, side = _bound(), _bound()
    mcp_port = side.getsockname()[1]
    app = PortSplit(create_gateway_app(replace(gw_cfg, mcp=True), client=None, detectors=[PatternDetector()]), mcp_port)
    with serve_in_thread(app, sockets=[main, side]):
        main_url = f"http://127.0.0.1:{main.getsockname()[1]}"
        mcp_url = f"http://127.0.0.1:{mcp_port}"
        assert httpx2.get(main_url + "/v1/health").status_code == 401           # the route is there; no token
        r = httpx2.post(main_url + "/mcp/ours", json={})
        assert (r.status_code, r.json()) == (404, {"error": "Not here."})
        assert httpx2.post(mcp_url + "/mcp/ours", json={}).status_code == 401   # the route is there; no token
        assert httpx2.get(mcp_url + "/v1/health").status_code == 404


def test_serve_binds_both_addresses(monkeypatch, gw_cfg):
    from steward_gateway import cli, serving
    seen = {}
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(serving, "run", lambda cfg, app: seen.update(cfg=cfg, app=app))
    monkeypatch.setattr("steward_gateway.cli.api_key", lambda cfg: None)
    from typer.testing import CliRunner
    assert CliRunner().invoke(cli.app, ["serve"]).exit_code == 0
    assert seen["cfg"] is gw_cfg


def test_serve_says_whether_the_local_model_answers_before_it_serves(monkeypatch, gw_cfg):
    from typer.testing import CliRunner
    from steward_gateway import cli, serving
    order = []
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(cli, "local_model_line", lambda cfg: order.append("line") or "Local model: (a test)")
    monkeypatch.setattr(serving, "run", lambda cfg, app: order.append("run"))
    monkeypatch.setattr("steward_gateway.cli.api_key", lambda cfg: None)
    r = CliRunner().invoke(cli.app, ["serve"])
    assert r.exit_code == 0 and "Local model: (a test)" in r.output and order == ["line", "run"]
