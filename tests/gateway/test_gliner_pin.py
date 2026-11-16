"""A5: the GLiNER-PII download and its base encoder are each pinned to one commit, so a changed upstream model can't
arrive unseen. Everything is fetched by revision first and then loaded from those local snapshots only."""
from __future__ import annotations

import fnmatch
import json
import re
import sys
import types
from pathlib import Path

import pytest

from steward_gateway.redact import gliner_detector as gd

SHA = "0123456789abcdef0123456789abcdef01234567"


class _Model:
    config = types.SimpleNamespace(max_len=384)
    data_processor = types.SimpleNamespace(
        words_splitter=lambda t: [], transformer_tokenizer=types.SimpleNamespace(model_max_length=512),
        prepare_inputs=lambda *a: ([], None))

    def to(self, device):
        return self

    def eval(self):
        return self


def _stub(monkeypatch, tmp_path, model_name="microsoft/mdeberta-v3-base"):
    """A stub hub (snapshot_download and hf_hub_download record every call) and a stub gliner that records how it was
    asked to load, plus the config it found in the folder it was given."""
    hub_calls, loads = [], []
    snapshots = {gd.GLINER_MODEL: tmp_path / "gliner", gd.GLINER_ENCODER: tmp_path / "encoder"}
    snapshots[gd.GLINER_MODEL].mkdir()
    (snapshots[gd.GLINER_MODEL] / "gliner_config.json").write_text(json.dumps({"model_name": model_name, "max_len": 384}))
    (snapshots[gd.GLINER_MODEL] / "pytorch_model.bin").write_bytes(b"weights")
    snapshots[gd.GLINER_ENCODER].mkdir()
    (snapshots[gd.GLINER_ENCODER] / "spm.model").write_bytes(b"sp")

    def snapshot_download(repo_id, **kwargs):
        hub_calls.append(("snapshot_download", repo_id, kwargs))
        return str(snapshots[repo_id])

    def hf_hub_download(repo_id, filename, **kwargs):
        hub_calls.append(("hf_hub_download", repo_id, kwargs))
        raise AssertionError("no single-file download is expected")

    class GLiNER:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            folder = Path(model_id)
            loads.append((model_id, kwargs, json.loads((folder / "gliner_config.json").read_text()),
                          (folder / "pytorch_model.bin").read_bytes()))
            return _Model()

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(
        snapshot_download=snapshot_download, hf_hub_download=hf_hub_download))
    monkeypatch.setitem(sys.modules, "gliner", types.SimpleNamespace(GLiNER=GLiNER))
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False)))
    return hub_calls, loads, snapshots


def test_both_revisions_are_full_commit_hashes():
    assert gd.GLINER_MODEL == "urchade/gliner_multi_pii-v1"
    assert gd.GLINER_ENCODER == "microsoft/mdeberta-v3-base"
    assert gd.GLINER_REVISION == "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d"
    assert gd.GLINER_ENCODER_REVISION == "a0484667b22365f84929a935b5e50a51f71f159d"
    for rev in (gd.GLINER_REVISION, gd.GLINER_ENCODER_REVISION):
        assert re.fullmatch(r"[0-9a-f]{40}", rev), rev


def test_every_download_while_loading_carries_a_pinned_revision(monkeypatch, tmp_path):
    hub_calls, loads, _ = _stub(monkeypatch, tmp_path)
    gd.GlinerDetector(model=None)
    pinned = {gd.GLINER_MODEL: gd.GLINER_REVISION, gd.GLINER_ENCODER: gd.GLINER_ENCODER_REVISION}
    assert {repo for _, repo, _ in hub_calls} == set(pinned)
    for _, repo, kwargs in hub_calls:
        assert kwargs.get("revision") == pinned[repo], (repo, kwargs)


def test_gliner_loads_from_the_pinned_snapshots_with_no_fetch_by_name(monkeypatch, tmp_path):
    _, loads, snapshots = _stub(monkeypatch, tmp_path)
    gd.GlinerDetector(model=None)
    [(model_id, kwargs, config, weights)] = loads
    # a local folder, never the hub name, and nothing GLiNER fetches on its own
    assert model_id != gd.GLINER_MODEL and Path(model_id).is_absolute()
    assert kwargs.get("local_files_only") is True and "revision" not in kwargs
    # the encoder and tokenizer GLiNER reads by config.model_name come from the pinned encoder snapshot
    assert config["model_name"] == str(snapshots[gd.GLINER_ENCODER])
    assert config["max_len"] == 384 and weights == b"weights"


def test_the_encoder_download_skips_its_weights(monkeypatch, tmp_path):
    hub_calls, _, _ = _stub(monkeypatch, tmp_path)
    gd.GlinerDetector(model=None)
    [enc] = [kw for _, repo, kw in hub_calls if repo == gd.GLINER_ENCODER]
    def fetched(name):
        return any(fnmatch.fnmatch(name, p) for p in enc["allow_patterns"])
    assert all(fetched(f) for f in ("config.json", "spm.model", "tokenizer_config.json", "special_tokens_map.json"))
    assert not any(fetched(f) for f in ("pytorch_model.bin", "model.safetensors", "tf_model.h5"))


def test_a_model_built_on_another_encoder_refuses_to_start(monkeypatch, tmp_path):
    _, loads, _ = _stub(monkeypatch, tmp_path, model_name="microsoft/deberta-v3-large")
    with pytest.raises(RuntimeError, match="GLINER_ENCODER"):
        gd.GlinerDetector(model=None)
    assert loads == []


# Gate finding PRIV-14: transformers' "incorrect regex pattern ... set fix_mistral_regex=True" line is a false alarm for
# the pinned mDeBERTa tokenizer, and following it would change how GLiNER's words are cut.

def test_gliner_loads_with_no_tokenizer_option_beyond_local_files(monkeypatch, tmp_path):
    """The loader passes local_files_only and nothing else, so the tokenizer is the one the models eval scored."""
    _, loads, _ = _stub(monkeypatch, tmp_path)
    gd.GlinerDetector(model=None)
    [(_, kwargs, _, _)] = loads
    assert kwargs == {"local_files_only": True}


def test_nothing_in_src_sets_fix_mistral_regex():
    """No keyword argument, attribute, setattr or dict key named fix_mistral_regex anywhere in src: setting it would
    replace mDeBERTa's pre-tokenizer with Mistral's under a model the eval scored without it."""
    import ast
    root = Path(__file__).resolve().parents[2] / "src"
    hits = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            named = (isinstance(node, ast.keyword) and node.arg == "fix_mistral_regex") or \
                (isinstance(node, ast.Attribute) and node.attr == "fix_mistral_regex") or \
                (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setattr" and len(node.args) > 1
                 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "fix_mistral_regex") or \
                (isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "fix_mistral_regex"
                                                    for k in node.keys))
            if named:
                hits.append(f"{path.relative_to(root)}:{node.lineno}")
    assert hits == []
    assert "fix_mistral_regex" in (root / "steward_gateway/redact/gliner_detector.py").read_text()   # the walk read it
    docs = (root.parent / "docs/guides/gateway.md").read_text(encoding="utf-8")
    assert "fix_mistral_regex" in docs and "expected" in docs                   # the reader is told it's expected


@pytest.mark.parametrize("which", ["GLINER_REVISION", "GLINER_ENCODER_REVISION"])
@pytest.mark.parametrize("bad", ["FILL-ME", "main", SHA[:39], SHA.upper(), ""])
def test_a_revision_that_is_not_40_hex_stops_startup_before_any_download(monkeypatch, tmp_path, which, bad):
    hub_calls, loads, _ = _stub(monkeypatch, tmp_path)
    monkeypatch.setattr(gd, which, bad)
    with pytest.raises(RuntimeError, match=which):
        gd.GlinerDetector(model=None)
    assert hub_calls == [] and loads == []
