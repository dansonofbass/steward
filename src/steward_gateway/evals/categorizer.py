"""The categorizer's accuracy eval (spec 6.1) and its latency (spec 12): the labelled set's descriptions, masked as the
NAS masks them, go through the categorizer in batches of 50; then 20 single rows are timed. Accuracy counts only rows
it chose a category for; coverage counts every row. Local only: nothing leaves the gateway."""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx2

from steward_boundary.text import mask_numbers
from steward_gateway.categorize import Categorizer, Row  # noqa: F401 - Categorizer is looked up here so tests can patch it

DEFAULT_SET = Path(__file__).resolve().parents[3] / "tests" / "gateway" / "categorizer_set" / "set.jsonl"
ACCURACY, COVERAGE, SINGLE_MS, BATCH_MS = 0.85, 0.70, 400, 5000


def read_set(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=20, method="inclusive")[-1]


@dataclass
class EvalResult:
    total: int
    categorized: int
    correct: int
    single_p95_ms: float
    batch_p95_ms: float
    misses: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.categorized if self.categorized else 0.0

    @property
    def coverage(self) -> float:
        return self.categorized / self.total if self.total else 0.0

    @property
    def passes(self) -> bool:
        return (self.accuracy >= ACCURACY and self.coverage >= COVERAGE and self.single_p95_ms < SINGLE_MS
                and self.batch_p95_ms < BATCH_MS)


async def run_eval(categorizer, rows: list[dict], *, singles: int = 20, batch: int = 50) -> EvalResult:
    asked = [Row(mask_numbers(r["description"]), r["amount_cents"]) for r in rows]
    answers, batch_ms = [], []
    for i in range(0, len(asked), batch):
        t0 = time.perf_counter()
        answers += await categorizer.categorize(asked[i:i + batch])
        batch_ms.append((time.perf_counter() - t0) * 1000)
    single_ms = []
    for row in asked[:singles]:
        t0 = time.perf_counter()
        await categorizer.categorize([row])
        single_ms.append((time.perf_counter() - t0) * 1000)
    categorized = correct = 0
    misses = []
    for r, a in zip(rows, answers):
        if a.category == "uncategorized":
            continue
        categorized += 1
        if a.category == r["category"]:
            correct += 1
        else:
            misses.append((r["id"], r["category"], a.category))
    return EvalResult(len(rows), categorized, correct, _p95(single_ms), _p95(batch_ms), misses)


def format_result(model: str, r: EvalResult) -> str:
    def mark(ok: bool) -> str:
        return "ok" if ok else "MISS"
    lines = [f"Categorizer eval, {model}, {r.total} rows",
             f"  Correct when it chose a category: {r.accuracy:.1%} (target {ACCURACY:.0%}) {mark(r.accuracy >= ACCURACY)}",
             f"  Rows categorized: {r.coverage:.1%} (target {COVERAGE:.0%}) {mark(r.coverage >= COVERAGE)}",
             f"  One row, p95: {r.single_p95_ms:.0f} ms (budget {SINGLE_MS} ms) {mark(r.single_p95_ms < SINGLE_MS)}",
             f"  Batch of 50, p95: {r.batch_p95_ms:.0f} ms (budget {BATCH_MS} ms) {mark(r.batch_p95_ms < BATCH_MS)}"]
    if r.misses:
        lines.append("  Wrong categories (id, expected, given): " +
                     ", ".join(f"{i} {want}→{got}" for i, want, got in r.misses[:20]))
    return "\n".join(lines)


def format_comparison(results: list[tuple[str, EvalResult]]) -> str:
    lines = ["Comparison (accuracy, coverage, p95 one row, p95 batch of 50)"]
    for model, r in results:
        lines.append(f"  {model}: {r.accuracy:.1%}, {r.coverage:.1%}, {r.single_p95_ms:.0f} ms, {r.batch_p95_ms:.0f} ms"
                     f" {'ok' if r.passes else 'MISS'}")
    return "\n".join(lines)


async def unload(url: str, model: str) -> None:
    """Ask Ollama to drop a model from memory (keep_alive 0) so the next model's speed isn't shared with it."""
    try:
        async with httpx2.AsyncClient(timeout=10.0) as http:
            await http.post(url.rstrip("/") + "/api/generate", json={"model": model, "keep_alive": 0})
    except httpx2.HTTPError:
        pass
