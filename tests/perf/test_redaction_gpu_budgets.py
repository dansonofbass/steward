"""Redaction's GPU budget (spec 12): 1000 characters under 60 ms at p95, 120 ms when look-alikes make a second view.
Moved from tests/gateway/test_models_eval.py so a busy GPU can't fail a deploy (flaky-test audit S7).
the gateway's deploy script runs it with the gateway stopped and prints it. Anywhere with the models group and a GPU:
uv run --group models pytest -q -m perf tests/perf/test_redaction_gpu_budgets.py"""
import os
import statistics
import time

import pytest

pytest.importorskip("gliner")       # the models group (the gateway); elsewhere a perf run skips this file

from steward_gateway.redact import detection_views, load_real_detectors, redact  # noqa: E402
from tests.advisor.pii_set.make_sets import HERE, read_jsonl  # noqa: E402

pytestmark = [pytest.mark.perf, pytest.mark.models, pytest.mark.timeout(900)]
PII = read_jsonl(HERE / "questions.jsonl")
KEEP = read_jsonl(HERE / "keep.jsonl")
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


@pytest.fixture(scope="module")
def detectors():
    found, problem = load_real_detectors()
    assert found, problem
    return found


def _p95_ms(text, detectors):
    redact(text, detectors)
    times = []
    for _ in range(30):
        t0 = time.perf_counter()
        redact(text, detectors)
        times.append((time.perf_counter() - t0) * 1000)
    return sorted(times)[int(len(times) * 0.95) - 1] * FACTOR, statistics.median(times)


def _gpu():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("the 60 ms budget is for the RTX 3080 Ti")


def _plain_question(n=1000):
    """A typed question as people write it: plain set rows and keep rows, none that makes a second view (a look-alike,
    a zero-width character, or a letter against a digit such as "$12k" or "Unit 4B")."""
    def one_view(t):
        return len(detection_views(t)) == 1
    rows = [r["text"] for r in PII if r["variant"] in ("plain", "lowercase") and one_view(r["text"])]
    keep = [r["text"] for r in KEEP if one_view(r["text"])]
    return " ".join(x for pair in zip(rows, keep) for x in pair)[:n]


def test_1000_characters_under_60_ms_p95_on_the_gpu(detectors):
    """The budget (spec 12) is for a realistic question: one view, so GLiNER reads it once."""
    _gpu()
    text = _plain_question()
    assert len(text) == 1000 and len(detection_views(text)) == 1
    p95, median = _p95_ms(text, detectors)
    print(f"\nPERF gliner_presidio_1000: {p95:.1f} ms p95 (median {median:.1f})")
    assert p95 < 60


def test_1000_characters_of_look_alikes_under_120_ms_p95_on_the_gpu(detectors):
    """The worst case: look-alike letters and zero-width characters make a second (split) view, so GLiNER and Presidio
    read the text twice. Its own line, twice the budget (privacy approach review, 2026-10-24)."""
    _gpu()
    text = (" ".join(r["text"] for r in PII[:40]))[:1000]
    assert len(detection_views(text)) == 2
    p95, median = _p95_ms(text, detectors)
    print(f"\nPERF gliner_presidio_1000_two_views: {p95:.1f} ms p95 (median {median:.1f})")
    assert p95 < 120
