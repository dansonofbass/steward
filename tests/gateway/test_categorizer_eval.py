"""The hard gate the gateway's deploy script runs before it restarts the gateway (final review ruling I2): Ollama answers
with the configured categorizer model, a one-token answer included. Needs Ollama, so it runs on the gateway, where
STEWARD_REQUIRE_OLLAMA=1 turns a missing Ollama or model into a failure. Anywhere else it skips. The accuracy and speed
targets are `steward-gateway eval categorizer`, which deploy.sh runs report-only."""
import asyncio
import os

import pytest

from steward_gateway.categorize import Categorizer
from steward_gateway.config import load_config

pytestmark = [pytest.mark.models, pytest.mark.timeout(900)]     # minutes of real model work (about 2 on CPU)


def test_ollama_answers_with_the_configured_model():
    cfg = load_config()
    cat = Categorizer(cfg.ollama_url, cfg.categorizer_model, parallel=cfg.categorizer_parallel)

    async def go():
        try:
            return await cat.ready()
        finally:
            await cat.close()
    if not asyncio.run(go()):
        if os.environ.get("STEWARD_REQUIRE_OLLAMA") == "1":
            pytest.fail(f"Ollama isn't answering with {cfg.categorizer_model}. Run: ollama pull {cfg.categorizer_model}")
        pytest.skip("Ollama isn't answering here; this runs on the gateway")
