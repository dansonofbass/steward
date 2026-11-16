"""What the gateway runs redaction on, for /v1/health (PR 13; PR 13b shows it in Get Steward ready)."""
from types import SimpleNamespace

import pytest

from steward_gateway import accelerator as A
from steward_gateway.redact.patterns import PatternDetector


@pytest.mark.parametrize("device, hip, want", [("cpu", None, "cpu"), ("cuda", None, "cuda"), ("cuda", "7.2", "rocm"),
                                               ("cpu", "7.2", "cpu"), (None, None, None)])
def test_the_name_says_cpu_cuda_or_rocm(device, hip, want):
    assert A.name(device, hip) == want


def test_the_loaded_detectors_say_what_redaction_runs_on():
    gliner = SimpleNamespace(device="cuda")
    assert A.of_detectors([gliner, PatternDetector()], hip=lambda: None) == "cuda"
    assert A.of_detectors([gliner], hip=lambda: "7.2") == "rocm"          # ROCm torch also calls its device "cuda"
    assert A.of_detectors([PatternDetector()], hip=lambda: None) == "cpu"  # no device: nothing on a GPU
    assert A.of_detectors([], hip=lambda: None) is None                    # the models didn't load


def _torch(monkeypatch, *, cuda, hip=None):
    import sys
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda), version=SimpleNamespace(hip=hip)))


def test_available_says_what_torch_can_use_right_now(monkeypatch):
    _torch(monkeypatch, cuda=True)
    assert A.available() == "cuda"
    _torch(monkeypatch, cuda=True, hip="7.2")
    assert A.available() == "rocm"
    _torch(monkeypatch, cuda=False)
    assert A.available() == "cpu"


def test_available_is_cpu_when_torch_does_not_import(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "torch", None)   # an import of None raises ImportError
    assert A.available() == "cpu"


def test_torch_is_only_asked_about_when_the_device_could_be_a_gpu():
    def boom():
        raise AssertionError("torch was imported for nothing")
    assert A.of_detectors([SimpleNamespace(device="cpu")], hip=boom) == "cpu"
    assert A.of_detectors([PatternDetector()], hip=boom) == "cpu"
