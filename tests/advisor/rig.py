"""A real gateway (with stand-in detectors) in front of the fake Anthropic server, both on loopback threads, for NAS
tests that drive whole turns. Nothing reaches Anthropic."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import anthropic

from steward.advisor.gateway import GatewayClient
from steward_gateway.app import create_gateway_app
from steward_gateway.config import GatewayConfig
from steward_gateway.redact.patterns import PatternDetector
from steward_gateway.secrets import write_private
from tests.gateway.fake_anthropic import FakeAnthropic
from tests.gateway.fakes import NameListDetector
from tests.servers import serve_in_thread

TOKEN = "e" * 64


@contextmanager
def gateway_rig(tmp_path, script, detectors=None):
    fake = FakeAnthropic(script)
    cfg = GatewayConfig(tmp_path / "gw-config", tmp_path / "gw-state")
    write_private(cfg.token_path, TOKEN)
    with serve_in_thread(fake.app()) as anthropic_url:
        api = anthropic.AsyncAnthropic(api_key="test-key-not-real", base_url=anthropic_url, max_retries=0)
        app = create_gateway_app(cfg, client=api,
                                 detectors=detectors if detectors is not None else [PatternDetector(), NameListDetector()])
        with serve_in_thread(app) as url:
            client = GatewayClient(url, TOKEN)
            try:
                yield SimpleNamespace(fake=fake, cfg=cfg, url=url, client=client)
            finally:
                client.close()
