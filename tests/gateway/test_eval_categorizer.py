"""The eval's arithmetic and the command, with a fake categorizer (no Ollama)."""
import asyncio
import json

from typer.testing import CliRunner

from steward_gateway import cli
from steward_gateway.categorize import Answer
from steward_gateway.evals import categorizer as E
from tests.gateway.fakes import FakeCategorizer

ROWS = [{"id": "a", "description": "HARBOR CAFE", "amount_cents": -100, "category": "dining"},
        {"id": "b", "description": "BEAN CAFE 4417002918", "amount_cents": -100, "category": "dining"},
        {"id": "c", "description": "GLOW CAFE SPA", "amount_cents": -100, "category": "personal"},
        {"id": "d", "description": "POS PURCHASE", "amount_cents": -100, "category": "uncategorized"}]


def test_accuracy_counts_only_rows_it_categorized_and_coverage_counts_all():
    r = asyncio.run(E.run_eval(FakeCategorizer(), ROWS, singles=2, batch=2))
    assert (r.total, r.categorized, r.correct) == (4, 3, 2)
    assert round(r.accuracy, 3) == 0.667 and r.coverage == 0.75
    assert r.misses == [("c", "personal", "dining")]
    assert not r.passes


def test_descriptions_are_masked_as_the_nas_masks_them():
    fake = FakeCategorizer()
    asyncio.run(E.run_eval(fake, ROWS, singles=1, batch=4))
    sent = [row.description for call in fake.calls for row in call]
    assert any(s.startswith("BEAN CAFE ") and s.endswith("2918") for s in sent)
    assert not any("4417002918" in s for s in sent)


def test_it_passes_at_the_targets():
    good = FakeCategorizer(answers=lambda d: Answer("uncategorized", None) if d.startswith("POS")
                           else Answer("personal" if "GLOW" in d else "dining", None))
    r = asyncio.run(E.run_eval(good, ROWS, singles=1, batch=4))
    assert r.accuracy == 1.0 and r.coverage == 0.75 and r.passes
    text = E.format_result("qwen3.5:9b-q4_K_M", r)
    assert "qwen3.5:9b-q4_K_M" in text and "Correct when it chose a category: 100.0% (target 85%)" in text
    assert "Rows categorized: 75.0% (target 70%)" in text


def test_the_command_exits_1_on_a_miss(gw_cfg, monkeypatch, tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(E, "Categorizer", lambda *a, **k: FakeCategorizer())
    r = CliRunner().invoke(cli.app, ["eval", "categorizer", "--model", "llama3.1:8b", "--set", str(path)])
    assert r.exit_code == 1 and "llama3.1:8b" in r.output and "MISS" in r.output


def _set(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    return path


def _good():
    return FakeCategorizer(answers=lambda d: Answer("uncategorized", None) if d.startswith("POS")
                           else Answer("personal" if "GLOW" in d else "dining", None))


def test_several_models_unload_the_previous_one_and_print_a_comparison(gw_cfg, monkeypatch, tmp_path):
    made, unloaded = [], []
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(E, "Categorizer", lambda url, name, **k: made.append(name) or _good())

    async def fake_unload(url, model):
        unloaded.append(model)
    monkeypatch.setattr(E, "unload", fake_unload)
    r = CliRunner().invoke(cli.app, ["eval", "categorizer", "--model", "m1:a", "--model", "m2:b", "--model", "m3:c",
                                     "--set", str(_set(tmp_path))])
    assert r.exit_code == 0, r.output
    assert made == ["m1:a", "m2:b", "m3:c"] and unloaded == ["m1:a", "m2:b"]
    assert r.output.count("Categorizer eval,") == 3
    assert r.output.index("Comparison") > r.output.rindex("Categorizer eval,")
    assert "  m2:b: 100.0%, 75.0%," in r.output


def test_exit_code_follows_the_first_model(gw_cfg, monkeypatch, tmp_path):
    fakes = iter([FakeCategorizer(), _good()])
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(E, "Categorizer", lambda *a, **k: next(fakes))

    async def fake_unload(url, model):
        pass
    monkeypatch.setattr(E, "unload", fake_unload)
    r = CliRunner().invoke(cli.app, ["eval", "categorizer", "--model", "m1:a", "--model", "m2:b",
                                     "--set", str(_set(tmp_path))])
    assert r.exit_code == 1


def test_the_default_model_is_the_configured_one(gw_cfg, monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(E, "Categorizer", lambda url, name, **k: made.append(name) or _good())
    CliRunner().invoke(cli.app, ["eval", "categorizer", "--set", str(_set(tmp_path))])
    assert made == [gw_cfg.categorizer_model]


def test_unload_posts_keep_alive_zero(monkeypatch):
    import httpx2
    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx2.Response(200, json={})
    real = httpx2.AsyncClient
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **k: real(transport=httpx2.MockTransport(handler)))
    asyncio.run(E.unload("http://127.0.0.1:11434", "m1:a"))
    assert seen == [("/api/generate", {"model": "m1:a", "keep_alive": 0})]


def test_ollama_not_answering_prints_one_plain_line_and_exits_1(gw_cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: gw_cfg)
    monkeypatch.setattr(E, "Categorizer", lambda *a, **k: FakeCategorizer(ready=False))
    r = CliRunner().invoke(cli.app, ["eval", "categorizer", "--model", "m1:a", "--set", str(_set(tmp_path))])
    assert r.exit_code == 1 and r.output.strip() == "Ollama isn't answering with m1:a."
