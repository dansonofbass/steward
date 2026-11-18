"""Titles from Ollama (spec 6.3): local only, JSON out, at most six words, nothing when Ollama is busy or away."""
import asyncio
import json

import httpx2
import pytest

from steward_gateway.config import ConfigError, GatewayConfig, check
from steward_gateway.ollama import Ollama, local_model_line


def ollama(handler):
    return Ollama("http://127.0.0.1:11434", "qwen3.5:9b-q4_K_M", http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_a_title_is_at_most_six_words_from_the_json_answer():
    seen = {}

    def handler(request):
        if request.url.path == "/api/show":
            return httpx2.Response(200, json={"capabilities": ["completion", "thinking"]})
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json={"response": json.dumps({"title": "Dining spending this year against last year"})})
    assert asyncio.run(ollama(handler).title("Are we spending more on dining than last year?")) == \
        "Dining spending this year against last"
    assert seen["model"] == "qwen3.5:9b-q4_K_M" and seen["stream"] is False and seen["format"]["required"] == ["title"]
    assert "Are we spending more on dining" in seen["prompt"]
    assert seen["think"] is False and seen["options"] == {"temperature": 0, "num_ctx": 4096}


@pytest.mark.parametrize("reply", [httpx2.Response(500), httpx2.Response(200, json={"response": "not json"}),
                                   httpx2.Response(200, json={"response": json.dumps({"title": ""})}),
                                   httpx2.Response(200, json={"response": json.dumps({"title": "Call 7145550102"})})])
def test_no_title_when_ollama_fails_or_answers_badly(reply):
    assert asyncio.run(ollama(lambda r: reply).title("How much is in savings?")) is None


def test_no_title_and_not_answering_when_ollama_is_away():
    def handler(request):
        raise httpx2.ConnectError("refused")
    o = ollama(handler)
    assert asyncio.run(o.title("How much is in savings?")) is None
    assert asyncio.run(o.answering()) is False


def test_answering_asks_the_tag_list_and_remembers_for_a_minute():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx2.Response(200, json={"models": []})
    o = ollama(handler)

    async def twice():
        return await o.answering(), await o.answering()
    assert asyncio.run(twice()) == (True, True)
    assert calls == ["/api/tags"]


def test_ollama_must_be_on_this_machine(tmp_path):
    with pytest.raises(ConfigError):
        check(GatewayConfig(tmp_path, tmp_path, ollama_url="http://192.0.2.20:11434"))
    check(GatewayConfig(tmp_path, tmp_path, ollama_url="http://localhost:11434"))
    with pytest.raises(ConfigError, match="ollama_url in gateway.toml must be on this machine \\(127.0.0.1\\)\\."):
        check(GatewayConfig(tmp_path, tmp_path, ollama_url="http://ollama:11434"))     # the service only in compose


AWAY = ("Local model: none yet. Ollama isn't answering at {url}, so categorizing, chat titles, scanned pages and new "
        "statement layouts wait. Ask doesn't need it.")


def sync(handler):
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def tags(*names):
    return lambda request: httpx2.Response(200, json={"models": [{"name": n} for n in names]})


def _raise(exc):
    def handler(request):
        raise exc
    return handler


@pytest.mark.parametrize("handler", [_raise(httpx2.ConnectError("refused")), _raise(httpx2.ReadTimeout("slow")),
                                     lambda request: httpx2.Response(500)])
def test_the_start_line_says_when_ollama_isnt_answering(tmp_path, handler):
    cfg = GatewayConfig(tmp_path, tmp_path)
    assert local_model_line(cfg, http=sync(handler)) == AWAY.format(url="http://127.0.0.1:11434")


def test_the_start_line_names_each_model_to_pull(tmp_path):
    compose = GatewayConfig(tmp_path, tmp_path, network="compose", host="0.0.0.0", ollama_url="http://ollama:11434")
    assert local_model_line(compose, http=sync(tags("qwen3.5:9b-q4_K_M"))) == (
        "Local model: Ollama answers at http://ollama:11434. Not pulled yet:\n"
        "  docker compose run --rm ollama-pull gemma4:12b-it-qat")
    assert local_model_line(GatewayConfig(tmp_path, tmp_path), http=sync(tags())) == (
        "Local model: Ollama answers at http://127.0.0.1:11434. Not pulled yet:\n"
        "  ollama pull qwen3.5:9b-q4_K_M\n"
        "  ollama pull gemma4:12b-it-qat")


def test_the_start_line_when_every_model_is_pulled_asks_once_within_two_seconds(tmp_path):
    seen = []

    def handler(request):
        seen.append((request.url.path, request.extensions["timeout"]["read"]))
        return tags("qwen3.5:9b-q4_K_M", "gemma4:12b-it-qat")(request)
    assert local_model_line(GatewayConfig(tmp_path, tmp_path), http=sync(handler)) == (
        "Local model: Ollama answers at http://127.0.0.1:11434, with every model gateway.toml names.")
    assert seen == [("/api/tags", 2.0)]


@pytest.mark.parametrize("reply, want", [
    (httpx2.Response(200, json={"models": [{"name": "qwen3.5:9b-q4_K_M", "size_vram": 6_000_000_000}]}), True),
    (httpx2.Response(200, json={"models": [{"name": "qwen3.5:9b-q4_K_M", "size_vram": 0}]}), False),
    (httpx2.Response(200, json={"models": []}), None),
    (httpx2.Response(500), None)])
def test_ollama_says_whether_its_loaded_models_are_on_a_gpu(reply, want):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return reply
    o = ollama(handler)

    async def twice():
        return await o.accelerated(), await o.accelerated()
    assert asyncio.run(twice()) == (want, want) and calls == ["/api/ps"]       # remembered for a minute


GPU_START = ("Local model: Ollama ({service}) starts once this gateway is healthy. To pull a model gateway.toml names:\n"
             "  docker compose run --rm ollama-pull qwen3.5:9b-q4_K_M\n"
             "  docker compose run --rm ollama-pull gemma4:12b-it-qat")


@pytest.mark.parametrize("vendor, service", [("nvidia", "ollama-nvidia"), ("amd", "ollama-amd")])
def test_a_gpu_compose_gateway_says_its_ollama_starts_after_it_and_names_that_service(tmp_path, vendor, service):
    """deploy/compose.yml starts ollama-nvidia and ollama-amd only once their gateway is healthy, so at start-up they
    never answer: the line says so plainly and names the service that is actually running."""
    compose = GatewayConfig(tmp_path, tmp_path, network="compose", host="0.0.0.0", ollama_url="http://ollama:11434")
    env = {"STEWARD_GATEWAY_GPU": vendor}
    line = local_model_line(compose, http=sync(_raise(httpx2.ConnectError("refused"))), environ=env)
    assert line == GPU_START.format(service=service) and "isn't answering" not in line
    assert local_model_line(compose, http=sync(tags("qwen3.5:9b-q4_K_M")), environ=env) == (   # a gateway-only restart
        "Local model: Ollama answers at http://ollama:11434. Not pulled yet:\n"
        "  docker compose run --rm ollama-pull gemma4:12b-it-qat")


def test_the_cpu_compose_gateway_and_the_systemd_gateway_keep_their_lines(tmp_path):
    compose = GatewayConfig(tmp_path, tmp_path, network="compose", host="0.0.0.0", ollama_url="http://ollama:11434")
    assert local_model_line(compose, http=sync(tags("qwen3.5:9b-q4_K_M")), environ={}) == (
        "Local model: Ollama answers at http://ollama:11434. Not pulled yet:\n"
        "  docker compose run --rm ollama-pull gemma4:12b-it-qat")
    assert local_model_line(compose, http=sync(_raise(httpx2.ConnectError("refused"))), environ={}) == \
        AWAY.format(url="http://ollama:11434")
    systemd = GatewayConfig(tmp_path, tmp_path)                     # outside compose a GPU variable changes nothing
    assert local_model_line(systemd, http=sync(_raise(httpx2.ConnectError("refused"))),
                            environ={"STEWARD_GATEWAY_GPU": "nvidia"}) == AWAY.format(url="http://127.0.0.1:11434")
    assert local_model_line(systemd, http=sync(tags()), environ={"STEWARD_GATEWAY_GPU": "nvidia"}).endswith(
        "\n  ollama pull qwen3.5:9b-q4_K_M\n  ollama pull gemma4:12b-it-qat")
