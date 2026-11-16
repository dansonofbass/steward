"""Scoring the answers eval (spec 11.4, ruling 15). A money figure is present when an amount in the answer is within
1% or $1 of it; a percentage within 0.05 points; a whole number when it appears on its own; a zero count also when the
answer says no or none. Each question is asked in a new conversation. The run passes at 29 of 32."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from steward_gateway.evals.answers_set import Case, Figure, Missing
from steward_gateway.evals.rig import EVAL_TODAY

PASS_MARK = 29
MONEY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(k|K|thousand|m|M|million)?(?![\w])")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent)")
NUM_RE = re.compile(r"(?<![\d.,$])(\d+)(?![\d,]|\.\d)")
SCALE = {"k": 1_000, "K": 1_000, "thousand": 1_000, "m": 1_000_000, "M": 1_000_000, "million": 1_000_000}


def amounts(text: str) -> list[int]:
    out = []
    for m in MONEY_RE.finditer(text):
        value = float(m.group(1).replace(",", "") + (m.group(2) or "")) * SCALE.get(m.group(3) or "", 1)
        out.append(round(value * 100))
    return out


def mentions(answer: str, f: Figure) -> bool:
    if f.kind == "money":
        target = abs(f.value)
        return any(abs(a - target) <= max(100, target // 100) for a in amounts(answer))
    if f.kind == "percent":
        return any(abs(float(m.group(1)) - f.value / 100) <= 0.05 for m in PCT_RE.finditer(answer))
    if f.value == 0 and re.search(r"\b(no|none|zero)\b", answer, re.IGNORECASE):
        return True
    return str(f.value) in NUM_RE.findall(answer)


def describe(f: Figure) -> str:
    if f.kind == "money":
        return f"${abs(f.value) / 100:,.2f}"
    if f.kind == "percent":
        return f"{f.value / 100:g}%"
    return str(f.value)


def figures_for(rig, case: Case, today: date) -> list[Figure] | None:
    slug = rig.slug_for(case.book)
    try:
        results = [rig.call(slug, name, inp) for name, inp in case.tools(today)]
        if any("error" in r for r in results):
            return None
        return case.figures(results, today) or None
    except (Missing, KeyError, TypeError, IndexError, StopIteration, ValueError):
        return None


@dataclass
class CaseResult:
    id: str
    question: str
    status: str                 # pass, miss or skipped
    missing: list[str] = field(default_factory=list)
    answer: str = ""
    cost_cents: int = 0


@dataclass
class AnswersResult:
    rows: list[CaseResult]

    @property
    def passed(self) -> int:
        return sum(r.status == "pass" for r in self.rows)

    @property
    def cost_cents(self) -> int:
        return sum(r.cost_cents for r in self.rows)

    @property
    def passes(self) -> bool:
        return self.passed >= min(PASS_MARK, len(self.rows))


def run_answers(rig, cases, today: date = EVAL_TODAY) -> AnswersResult:
    rows = []
    for case in cases:
        figs = figures_for(rig, case, today)
        if figs is None:
            rows.append(CaseResult(case.id, case.question, "skipped"))
            continue
        out = rig.ask(rig.slug_for(case.book), case.question)
        missing = [describe(f) for f in figs if not mentions(out.answer, f)]
        status = "pass" if out.stop == "end_turn" and not missing else "miss"
        rows.append(CaseResult(case.id, case.question, status, missing, out.answer, out.cost_cents))
    return AnswersResult(rows)


def format_answers(r: AnswersResult) -> str:
    lines = [f"Answers eval: {r.passed} of {len(r.rows)} right (pass mark {min(PASS_MARK, len(r.rows))}). "
             f"Cost ${r.cost_cents / 100:,.2f}."]
    for row in r.rows:
        if row.status == "skipped":
            lines.append(f"  {row.id} skipped: the demo books have no figure for \"{row.question}\"")
        elif row.status == "miss":
            lines.append(f"  {row.id} missed {', '.join(row.missing) or 'a full answer'}: \"{row.question}\"")
            lines.append(f"      answer: {row.answer[:300]}")
    return "\n".join(lines)
