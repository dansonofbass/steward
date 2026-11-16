"""How long one redaction read takes on this machine: each bench and answers question once, and 1,000 characters
(about a long tool result) repeated. Local only: nothing leaves the gateway. The numbers go into
docs/guides/gateway.md."""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from steward_gateway.accelerator import of_detectors
from steward_gateway.evals.answers_set import CASES
from steward_gateway.evals.bench import NO_TOOLS, _p
from steward_gateway.redact import redact

SAMPLE: tuple[str, ...] = NO_TOOLS + tuple(c.question for c in CASES)
LONG_TEXT = " ".join(SAMPLE)[:1000]


@dataclass(frozen=True)
class RedactionTiming:
    device: str
    threads: int | None
    questions: int
    question_p50_ms: float
    question_p95_ms: float
    long_p50_ms: float
    long_p95_ms: float


def _torch_threads() -> int | None:
    try:
        import torch
        return torch.get_num_threads()
    except Exception:
        return None


def _time(text: str, detectors: Sequence, clock: Callable[[], float]) -> float:
    start = clock()
    redact(text, detectors)
    return (clock() - start) * 1000


def run_redaction(detectors: Sequence, *, clock: Callable[[], float] = time.perf_counter,
                  long_repeats: int = 20) -> RedactionTiming:
    redact(SAMPLE[0], detectors)        # the first read loads kernels and caches; it isn't counted
    questions = [_time(q, detectors, clock) for q in SAMPLE]
    longs = [_time(LONG_TEXT, detectors, clock) for _ in range(long_repeats)]
    return RedactionTiming(
        device=of_detectors(detectors) or "cpu", threads=_torch_threads(), questions=len(SAMPLE),
        question_p50_ms=round(_p(questions, 0.5), 1), question_p95_ms=round(_p(questions, 0.95), 1),
        long_p50_ms=round(_p(longs, 0.5), 1), long_p95_ms=round(_p(longs, 0.95), 1))


def format_redaction(t: RedactionTiming) -> str:
    on = f"{t.device} ({t.threads} threads)" if t.threads else t.device
    return (f"Redaction on {on}, one read:\n"
            f"  A question ({t.questions}): p50 {t.question_p50_ms:,.0f} ms, p95 {t.question_p95_ms:,.0f} ms\n"
            f"  1,000 characters: p50 {t.long_p50_ms:,.0f} ms, p95 {t.long_p95_ms:,.0f} ms\n"
            "A turn reads the question three times before it's sent (the preview, the turn and the check) and each "
            "tool result once.")
