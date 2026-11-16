"""The bench (spec 12): 20 fictional questions, 6 that need no tools and 14 from the answers eval, through the real
API when JR runs it. It measures the first answer token from the start of the turn, grouped by how many rounds of
tools came first, against "< 4 s p50, < 8 s p95" (no tools) and "< 8 s p50, < 15 s p95" (one round). Questions that
took two or more rounds are listed without a budget. The printed table is kept with the plan's notes."""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from steward_gateway.evals.answers_set import CASES

NO_TOOLS = ("In two sentences, what's the difference between a Roth IRA and a traditional IRA?",
            "What does an employer 401(k) match mean, in plain words?",
            "What is a required minimum distribution?",
            "Explain the difference between a pension and an annuity in two sentences.",
            "What is an emergency fund for?",
            "What does Medicare Part D cover, briefly?")
BENCH_IDS = ("h01", "h03", "h07", "h09", "h11", "h14", "h16", "h19", "p01", "p04", "p06", "p07", "p09", "p10")
BUDGETS = {"no_tools": (4000, 8000), "one_round": (8000, 15000)}
LABELS = {"no_tools": "No tools", "one_round": "One round of tools"}


@dataclass
class BenchRow:
    question: str
    rounds: int
    first_token_ms: float | None
    total_ms: float
    cost_cents: int
    stop: str


def _p(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]


@dataclass
class BenchResult:
    rows: list[BenchRow]

    def group(self, name: str) -> list[float]:
        rounds = 0 if name == "no_tools" else 1
        return [r.first_token_ms for r in self.rows if r.rounds == rounds and r.first_token_ms is not None]

    def p50(self, name: str) -> float:
        return _p(self.group(name), 0.50)

    def p95(self, name: str) -> float:
        return _p(self.group(name), 0.95)

    def ok(self, name: str) -> bool:
        p50, p95 = BUDGETS[name]
        return bool(self.group(name)) and self.p50(name) < p50 and self.p95(name) < p95

    @property
    def passes(self) -> bool:
        return all(self.ok(name) for name in BUDGETS)


def run_bench(rig) -> BenchResult:
    rows = []
    by_id = {c.id: c for c in CASES}
    asks = [("household", q) for q in NO_TOOLS] + [(by_id[i].book, by_id[i].question) for i in BENCH_IDS]
    for book, question in asks:
        out = rig.ask(rig.slug_for(book), question)
        rows.append(BenchRow(question, out.tool_rounds, out.first_token_ms, out.total_ms, out.cost_cents, out.stop))
    return BenchResult(rows)


def format_bench(r: BenchResult) -> str:
    lines = [f"Bench: {len(r.rows)} questions, ${sum(x.cost_cents for x in r.rows) / 100:,.2f}"]
    for name, (p50, p95) in BUDGETS.items():
        n = len(r.group(name))
        if not n:
            lines.append(f"  {LABELS[name]}: no samples MISS")
            continue
        lines.append(f"  {LABELS[name]}: p50 {r.p50(name) / 1000:.1f} s (budget {p50 / 1000:g} s), "
                     f"p95 {r.p95(name) / 1000:.1f} s (budget {p95 / 1000:g} s), {n} questions "
                     f"{'ok' if r.ok(name) else 'MISS'}")
    more = [x for x in r.rows if x.rounds >= 2]
    if more:
        lines.append(f"  Two or more rounds (no budget): {len(more)} questions")
    for x in r.rows:
        first = f"{x.first_token_ms / 1000:.1f} s" if x.first_token_ms is not None else "none"
        lines.append(f"    {first:>7}  {x.rounds} round(s)  {x.stop:<9} {x.question[:70]}")
    return "\n".join(lines)


def as_json(r: BenchResult) -> dict:
    return {"rows": [asdict(x) for x in r.rows],
            "groups": {name: {"n": len(r.group(name)), "p50_ms": r.p50(name) if r.group(name) else None,
                              "p95_ms": r.p95(name) if r.group(name) else None} for name in BUDGETS}}
