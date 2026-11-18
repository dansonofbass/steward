"""Ollama on the gateway (spec 6.3; plan C adds the categorizer). Loopback only: config.check refuses any other address,
except that network = "compose" inside the gateway's container also allows the ollama service.
A title is at most six words from the redacted first question, asked with a JSON schema so the answer is one field;
a slow or odd answer, or Ollama being away, gives no title, and the NAS keeps the first six words."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING

import httpx2

from steward_gateway import gpu

if TYPE_CHECKING:
    from steward_gateway.config import GatewayConfig

TITLE_WORDS = 6
TAGS_EVERY_S = 60.0
PROMPT = ("Write a title of at most six words for this question about a family's money. Keep any words like "
          "\"Person 1\" or \"Account 2\" exactly as written. Answer with JSON only.\n\nQuestion: {text}")
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
THINKING_FAMILIES = ("qwen3", "qwen3.5", "gemma4")
OPTIONS = {"temperature": 0, "num_ctx": 4096}


def thinks(model: str) -> bool:
    """True for a model family that thinks before it answers, so its requests must say `think: false` (a thinking
    model with `format` can spend its answer on thought). Decided by the family before the colon, not by a prefix.
    The fallback for ThinkCheck when Ollama can't say."""
    family = model.split(":", 1)[0].strip().casefold()
    return family in THINKING_FAMILIES or family.startswith("granite")


class ThinkCheck:
    """Whether a model thinks, by capability (final review M3): Ollama's /api/show lists "thinking" among a model's
    capabilities, which also covers a namespaced tag (hf.co/…) and families the list doesn't know. Asked once per
    model. An Ollama too old to list capabilities is answered by the family list for good; an error is answered by
    the list this time and asked again next time."""

    def __init__(self, url: str, model: str, http: httpx2.AsyncClient):
        self.url, self.model, self._http = url, model, http
        self._known: bool | None = None
        self._lock = asyncio.Lock()

    async def __call__(self) -> bool:
        if self._known is not None:
            return self._known
        async with self._lock:
            if self._known is not None:
                return self._known
            try:
                r = await self._http.post(self.url + "/api/show", json={"model": self.model}, timeout=2.0)
                if r.status_code != 200:
                    return thinks(self.model)
                caps = r.json().get("capabilities")
            except (httpx2.HTTPError, ValueError, AttributeError):
                return thinks(self.model)
            self._known = "thinking" in caps if isinstance(caps, list) else thinks(self.model)
            return self._known


class Ollama:
    def __init__(self, url: str, model: str, *, http: httpx2.AsyncClient | None = None, timeout: float = 3.0):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout
        self._http = http or httpx2.AsyncClient(timeout=timeout)
        self._up: tuple[float, bool] | None = None
        self._ps: tuple[float, bool | None] | None = None
        self._thinks = ThinkCheck(self.url, model, self._http)

    async def close(self) -> None:
        await self._http.aclose()

    async def answering(self) -> bool:
        if self._up and time.monotonic() - self._up[0] < TAGS_EVERY_S:
            return self._up[1]
        try:
            ok = (await self._http.get(self.url + "/api/tags", timeout=1.0)).status_code == 200
        except httpx2.HTTPError:
            ok = False
        self._up = (time.monotonic(), ok)
        return ok

    async def accelerated(self) -> bool | None:
        """Whether Ollama's loaded models sit on a GPU (/api/ps lists size_vram), remembered for a minute. None when
        no model is loaded, or Ollama can't say."""
        if self._ps and time.monotonic() - self._ps[0] < TAGS_EVERY_S:
            return self._ps[1]
        answer: bool | None = None
        try:
            r = await self._http.get(self.url + "/api/ps", timeout=1.0)
            models = r.json().get("models") if r.status_code == 200 else None
            if isinstance(models, list) and models:
                answer = any(isinstance(m, dict) and (m.get("size_vram") or 0) > 0 for m in models)
        except (httpx2.HTTPError, ValueError, AttributeError, TypeError):
            answer = None
        self._ps = (time.monotonic(), answer)
        return answer

    async def title(self, text: str) -> str | None:
        body = {"model": self.model, "prompt": PROMPT.format(text=text), "stream": False, "format": SCHEMA,
                "options": dict(OPTIONS)}
        if await self._thinks():
            body["think"] = False
        try:
            r = await self._http.post(self.url + "/api/generate", json=body, timeout=self.timeout)
            title = json.loads(r.json()["response"])["title"] if r.status_code == 200 else None
        except (httpx2.HTTPError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(title, str):
            return None
        out = " ".join(re.sub(r"[\"“”.!?]", "", title).split()[:TITLE_WORDS])[:80]
        return out if out and not re.search(r"\d{5,}", out.replace(" ", "")) else None


COMPOSE_PULL = "docker compose run --rm ollama-pull"   # deploy/compose.yml: the Ollama on gateway-egress, run once


def local_model_line(cfg: GatewayConfig, *, http: httpx2.Client | None = None,
                     environ: Mapping[str, str] | None = None) -> str:
    """The line `serve` prints at start-up: whether Ollama answers and which of the configured models still need
    pulling. One /api/tags request, at most two seconds. Names no model's content, only the settings' model names.
    A GPU image in compose (STEWARD_GATEWAY_GPU in `environ`, default os.environ) has its own Ollama service, which
    compose starts only once this gateway is healthy, so silence from it at start-up is expected, not a problem. In
    compose every model is pulled by the one-shot ollama-pull service, the only Ollama with a way out (issue #4)."""
    models = list(dict.fromkeys((cfg.title_model, cfg.categorizer_model, cfg.statement_layout_model,
                                 cfg.statement_vision_model)))
    service = gpu.ollama_service(os.environ if environ is None else environ, cfg.network)
    if service:
        away = (f"Local model: Ollama ({service}) starts once this gateway is healthy. To pull a model gateway.toml "
                "names:\n" + "\n".join(f"  {COMPOSE_PULL} {m}" for m in models))
    else:
        away = (f"Local model: none yet. Ollama isn't answering at {cfg.ollama_url}, so categorizing, chat titles, "
                "scanned pages and new statement layouts wait. Ask doesn't need it.")
    client = http or httpx2.Client()
    try:
        r = client.get(cfg.ollama_url.rstrip("/") + "/api/tags", timeout=2.0)
        if r.status_code != 200:
            return away
        names = {m.get("name") for m in r.json().get("models", [])}
    except (httpx2.HTTPError, ValueError, AttributeError, TypeError):
        return away
    finally:
        if http is None:
            client.close()
    missing = [m for m in models if m not in names and f"{m}:latest" not in names]
    if not missing:
        return f"Local model: Ollama answers at {cfg.ollama_url}, with every model gateway.toml names."
    pull = COMPOSE_PULL if cfg.network == "compose" else "ollama pull"
    return (f"Local model: Ollama answers at {cfg.ollama_url}. Not pulled yet:\n"
            + "\n".join(f"  {pull} {m}" for m in missing))
