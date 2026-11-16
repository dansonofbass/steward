"""The NAS reaches the gateway only through the steward-tailscale sidecar's outbound proxy (deploy/nas/README.md, "Chat
and the gateway"): HTTP_PROXY in .env sends plain-http requests there, and NO_PROXY keeps the container's own health
check direct. So the gateway and categorizer clients must keep honouring HTTP_PROXY."""
import http.server
import json
import threading
import urllib.request

import pytest

from steward.advisor.gateway import GatewayClient
from steward.services.categorizer_client import HttpModelClient

GATEWAY = "http://100.64.0.9:8430"   # a tailnet address nothing on this machine answers on


def _server(seen: list):
    class Answer(http.server.BaseHTTPRequestHandler):
        def _answer(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            seen.append((self.command, self.path))
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = _answer

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def proxy(monkeypatch):
    """A stand-in for tailscale:1055 that records what it was asked for, set the way the NAS's .env sets it."""
    seen: list = []
    srv = _server(seen)
    for k in ("http_proxy", "https_proxy", "no_proxy", "all_proxy", "ALL_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    yield seen
    srv.shutdown()


def test_the_gateway_client_goes_through_the_proxy(proxy):
    c = GatewayClient(GATEWAY, "token")
    try:
        assert c.health() == {"ok": True}
    finally:
        c.close()
    assert proxy == [("GET", f"{GATEWAY}/v1/health")]


def test_the_categorizer_goes_through_the_proxy(proxy):
    c = HttpModelClient(f"{GATEWAY}/v1/categorize", token="token")
    try:
        c.categorize("COFFEE SHOP", -450)
    finally:
        c.close()
    assert proxy == [("POST", f"{GATEWAY}/v1/categorize")]


def test_the_health_check_on_127_0_0_1_stays_direct(proxy):
    direct: list = []
    srv = _server(direct)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/api/health", timeout=5).read()
    finally:
        srv.shutdown()
    assert direct == [("GET", "/api/health")] and proxy == []
