"""The statement reader's eval (PDF statements spec P47): the synthetic set's bank and card statements go through the
NAS's own extraction, proposal, retry, rules and check (imported lazily, as rig.py imports steward), with the layout
model on the gateway answering. Local only: nothing leaves the gateway, and the statements are built in memory. A missed
bar never stops a deploy; it is printed. PR 2 adds the scan bars, PR 3 the holdings bar."""
from __future__ import annotations

import asyncio
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from steward_gateway.evals.statement_set import BANK_CARD, HOLDINGS, LOANS, build  # noqa: F401 - the CLI passes HOLDINGS and LOANS
from steward_gateway.statements import StatementModel, StatementsAway  # noqa: F401 - the CLI builds the real one

FIRST, RETRY, ROWS, INVENTED, LAYOUT_P95_S = 0.90, 0.97, 0.995, 0, 90.0
HOLDINGS_TEXT, HOLDINGS_SCAN = 0.95, 0.85
EVAL_TODAY = date(2026, 10, 31)


@dataclass
class Result:
    statements: int = 0
    first_ok: int = 0
    retry_ok: int = 0
    rows_truth: int = 0
    rows_exact: int = 0
    invented_rows: int = 0
    holdings_ok: int = 0
    holdings_n: int = 0
    seconds: list[float] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @property
    def holdings(self) -> float:
        return self.holdings_ok / self.holdings_n if self.holdings_n else 0.0

    @property
    def first(self) -> float:
        return self.first_ok / self.statements if self.statements else 0.0

    @property
    def after_retry(self) -> float:
        return self.retry_ok / self.statements if self.statements else 0.0

    @property
    def rows_exact_share(self) -> float:
        return self.rows_exact / self.rows_truth if self.rows_truth else 0.0

    @property
    def invented(self) -> int:
        return self.invented_rows

    @property
    def p95(self) -> float:
        if len(self.seconds) < 2:
            return self.seconds[0] if self.seconds else 0.0
        return statistics.quantiles(self.seconds, n=20, method="inclusive")[-1]

    @property
    def passes(self) -> bool:
        return (self.first >= FIRST and self.after_retry >= RETRY
                and (not self.rows_truth or self.rows_exact_share >= ROWS)
                and self.invented == INVENTED and self.p95 < LAYOUT_P95_S
                and (not self.holdings_n or self.holdings >= HOLDINGS_TEXT))


def _key(r) -> tuple:
    from steward.services.transactions import tidy
    return (r["date"], r["amount_cents"], tidy(r["description"]))


def run_eval(model, loop: asyncio.AbstractEventLoop, ids=BANK_CARD, today: date = EVAL_TODAY) -> Result:
    from steward.services.statements.propose import propose
    from steward_pdf.sandbox import read_pdf
    out = Result()

    def ask(sent, hint):
        t0 = time.perf_counter()
        try:
            return loop.run_until_complete(model.layout(sent, hint))
        except StatementsAway:
            return None
        finally:
            out.seconds.append(time.perf_counter() - t0)

    for sid in ids:
        data, truth = build(sid)
        pages = read_pdf(data)["pages"]
        got = propose(ask, pages, today)
        out.statements += 1
        first_ok = got.gap == 0 and got.asked == 1
        out.first_ok += first_ok
        out.retry_ok += got.gap == 0
        if truth.holdings:
            out.holdings_n += 1
            out.holdings_ok += got.gap == 0
        if truth.kind not in ("bank", "card"):
            if got.gap != 0:
                out.misses.append(sid)
            continue
        want = Counter(_key(r) for r in truth.rows)
        read = Counter(_key({"date": r.date.isoformat(), "amount_cents": r.amount_cents, "description": r.description})
                       for x in got.readings for r in x.rows)
        if got.gap == 0:
            out.rows_truth += sum(want.values())
            out.rows_exact += sum((want & read).values())
        out.invented_rows += sum((read - want).values())
        if got.gap != 0:
            out.misses.append(sid)
    return out


def format_result(model: str, r: Result) -> str:
    def mark(ok: bool) -> str:
        return "ok" if ok else "MISS"
    lines = [f"Statement layouts eval, {model}, {r.statements} statements",
             f"  Add up on the first proposal: {r.first:.0%} (target {FIRST:.0%}) {mark(r.first >= FIRST)}",
             f"  Add up after the one retry: {r.after_retry:.0%} (target {RETRY:.0%}) {mark(r.after_retry >= RETRY)}",
             f"  Rows exactly right where they add up: {r.rows_exact_share:.1%} (target {ROWS:.1%}) "
             f"{mark(r.rows_exact_share >= ROWS)}",
             f"  Rows invented: {r.invented} (target {INVENTED}) {mark(r.invented == INVENTED)}",
             f"  A layout, p95: {r.p95:.1f} s (budget {LAYOUT_P95_S:.0f} s) {mark(r.p95 < LAYOUT_P95_S)}"]
    if r.holdings_n:
        lines.append(f"  Holdings totals within $1: {r.holdings:.0%} (target {HOLDINGS_TEXT:.0%}) "
                     f"{mark(r.holdings >= HOLDINGS_TEXT)}")
    if r.misses:
        lines.append("  Didn't add up: " + ", ".join(r.misses))
    return "\n".join(lines)


def format_comparison(results: list[tuple[str, Result]]) -> str:
    lines = ["Comparison (first, after retry, rows exact, invented, p95)"]
    for model, r in results:
        lines.append(f"  {model}: {r.first:.0%}, {r.after_retry:.0%}, {r.rows_exact_share:.1%}, {r.invented}, "
                     f"{r.p95:.1f} s {'ok' if r.passes else 'MISS'}")
    return "\n".join(lines)


SCAN_FIRST, SCAN_ROWS, SCAN_INVENTED, PAGE_P95_S = 0.70, 0.97, 0.005, 30.0
ONE_ACCOUNT = ("chase_checking", "boa_checking", "wells_checking", "chase_card", "amex_card", "citi_card", "capone_card")


@dataclass
class ScanResult:
    statements: int = 0
    first_ok: int = 0
    rows_truth: int = 0
    rows_right: int = 0              # date and amount (P47's scan bar)
    descriptions_right: int = 0      # reported, not gated
    invented_rows: int = 0
    read_rows: int = 0
    holdings_ok: int = 0
    holdings_n: int = 0
    seconds: list[float] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @property
    def first(self) -> float:
        return self.first_ok / self.statements if self.statements else 0.0

    @property
    def rows(self) -> float:
        return self.rows_right / self.rows_truth if self.rows_truth else 0.0

    @property
    def holdings(self) -> float:
        return self.holdings_ok / self.holdings_n if self.holdings_n else 0.0

    @property
    def descriptions(self) -> float:
        return self.descriptions_right / self.rows_truth if self.rows_truth else 0.0

    @property
    def invented(self) -> float:
        return self.invented_rows / self.read_rows if self.read_rows else 0.0

    @property
    def p95(self) -> float:
        if len(self.seconds) < 2:
            return self.seconds[0] if self.seconds else 0.0
        return statistics.quantiles(self.seconds, n=20, method="inclusive")[-1]

    @property
    def passes(self) -> bool:
        return (self.first >= SCAN_FIRST and self.rows >= SCAN_ROWS and self.invented <= SCAN_INVENTED
                and self.p95 < PAGE_P95_S and (not self.holdings_n or self.holdings >= HOLDINGS_SCAN))


def run_scan_eval(model, loop: asyncio.AbstractEventLoop, ids=ONE_ACCOUNT, today: date = EVAL_TODAY) -> ScanResult:
    """The synthetic scans through the NAS's own render, assembly and check (P47's scan column). Rendering here runs
    in this process: the files are the synthetic set, never a person's."""
    from steward.services.statements import check
    from steward_pdf.sandbox import read_pdf, render_page
    from steward.services.statements.scan import assemble
    from steward.services.transactions import tidy
    out = ScanResult()
    for sid in ids:
        data, truth = build(sid, variant="scan")
        pages = read_pdf(data)["pages"]
        answers = []
        for n in range(1, len(pages) + 1):
            pic = render_page(data, n)
            request = {"page": n, "of": len(pages), "image": pic["png"], "width_px": pic["width_px"],
                       "height_px": pic["height_px"],
                       "want": "holdings" if truth.holdings else "rows"}
            t0 = time.perf_counter()
            try:
                answers.append({"n": n, **loop.run_until_complete(model.page(request))})
            except StatementsAway:
                answers.append({"n": n, "page_kind": "other", "institution": None, "account_last4": None, "period": None,
                                "opening": None, "closing": None, "rows": [], "holdings": [], "total": None})
            out.seconds.append(time.perf_counter() - t0)
        reading, facts = assemble(answers, truth.kind, today)
        out.statements += 1
        if truth.holdings:
            ok = reading.error is None and check.holdings_gap(
                facts["total_cents"], [h["value_cents"] for h in facts["holdings"]]) == 0
            out.holdings_n += 1
            out.holdings_ok += ok
            out.first_ok += ok
            if not ok:
                out.misses.append(sid)
            continue
        adds = reading.error is None and check.gap(truth.kind, reading.opening, reading.closing,
                                                   [r.amount_cents for r in reading.rows]) == 0
        out.first_ok += adds
        want = Counter((r["date"], r["amount_cents"]) for r in truth.rows)
        want_d = Counter((r["date"], r["amount_cents"], tidy(r["description"])) for r in truth.rows)
        got = Counter((r.date.isoformat(), r.amount_cents) for r in reading.rows)
        got_d = Counter((r.date.isoformat(), r.amount_cents, tidy(r.description)) for r in reading.rows)
        out.read_rows += sum(got.values())
        out.invented_rows += sum((got - want).values())
        if adds:
            out.rows_truth += sum(want.values())
            out.rows_right += sum((want & got).values())
            out.descriptions_right += sum((want_d & got_d).values())
        else:
            out.misses.append(sid)
    return out


def format_scan_result(model: str, r: ScanResult) -> str:
    def mark(ok: bool) -> str:
        return "ok" if ok else "MISS"
    lines = [f"Scanned statements eval, {model}, {r.statements} statements",
             f"  Add up on the first reading: {r.first:.0%} (target {SCAN_FIRST:.0%}) {mark(r.first >= SCAN_FIRST)}",
             f"  Rows right on date and amount where they add up: {r.rows:.1%} (target {SCAN_ROWS:.0%}) "
             f"{mark(r.rows >= SCAN_ROWS)}",
             f"  Scan descriptions exactly right: {r.descriptions:.0%} (reported, not a target)",
             f"  Rows invented: {r.invented:.1%} (target at most {SCAN_INVENTED:.1%}) {mark(r.invented <= SCAN_INVENTED)}",
             f"  A page, p95: {r.p95:.1f} s (budget {PAGE_P95_S:.0f} s) {mark(r.p95 < PAGE_P95_S)}"]
    if r.holdings_n:
        lines.append(f"  Holdings totals within $1: {r.holdings:.0%} (target {HOLDINGS_SCAN:.0%}) "
                     f"{mark(r.holdings >= HOLDINGS_SCAN)}")
    if r.misses:
        lines.append("  Didn't add up: " + ", ".join(r.misses))
    return "\n".join(lines)
