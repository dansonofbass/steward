"""steward-gateway eval statements (spec P47): the NAS's own extraction, rules and check over the synthetic set, with
the bars. Here with a stand-in model only; JR runs the real one on the gateway."""
import asyncio

from steward_gateway.evals import statements as E
from steward_gateway.evals.statement_set import BANK_CARD, HOLDINGS, LOANS, build
from tests.gateway.fakes import FakeStatementModel


def _truthful(pages, hint):
    for sid in BANK_CARD:
        truth = build(sid)[1]
        if any(truth.institution in c["text"] for p in pages for ln in p["lines"] for c in ln["cells"]):
            return truth.layout
    raise AssertionError("unknown statement")


def _truthful_all(pages, hint):
    for sid in BANK_CARD + HOLDINGS + LOANS:
        truth = build(sid)[1]
        if any(truth.institution in c["text"] for p in pages for ln in p["lines"] for c in ln["cells"]):
            return truth.layout
    raise AssertionError("unknown statement")


def test_the_holdings_bar_counts_totals_within_a_dollar():
    loop = asyncio.new_event_loop()
    try:
        r = E.run_eval(FakeStatementModel(_truthful_all), loop, ids=HOLDINGS)
    finally:
        loop.close()
    assert (r.holdings_n, r.holdings_ok) == (len(HOLDINGS), len(HOLDINGS))
    assert "Holdings totals within $1: 100% (target 95%) ok" in E.format_result("stand-in", r)


def test_loans_and_holdings_run_without_row_counts():
    loop = asyncio.new_event_loop()
    try:
        r = E.run_eval(FakeStatementModel(_truthful_all), loop, ids=HOLDINGS + LOANS)
    finally:
        loop.close()
    assert r.statements == 5 and r.first == 1.0 and r.after_retry == 1.0 and r.holdings_n == 3 and r.passes


def test_a_vision_model_that_reads_holdings_meets_the_holdings_scan_bar():
    from tests.statement_helpers import truth_answers
    queue = [a for sid in HOLDINGS for a in truth_answers(build(sid)[1])]
    wants = []

    def page(request):
        wants.append(request["want"])
        return queue.pop(0)
    loop = asyncio.new_event_loop()
    try:
        r = E.run_scan_eval(FakeStatementModel(page=page), loop, ids=HOLDINGS)
    finally:
        loop.close()
    assert (r.holdings_n, r.holdings_ok) == (3, 3) and set(wants) == {"holdings"}
    assert "Holdings totals within $1: 100% (target 85%) ok" in E.format_scan_result("stand-in", r)


def test_a_model_that_answers_the_truth_meets_every_bar():
    loop = asyncio.new_event_loop()
    try:
        r = E.run_eval(FakeStatementModel(_truthful), loop)
    finally:
        loop.close()
    assert r.statements == len(BANK_CARD) and r.first == 1.0 and r.after_retry == 1.0 and r.rows_exact_share == 1.0
    assert r.invented == 0 and r.passes
    assert "ok" in E.format_result("stand-in", r) and "MISS" not in E.format_result("stand-in", r)


def test_a_model_that_never_answers_misses_and_says_so():
    loop = asyncio.new_event_loop()
    try:
        r = E.run_eval(FakeStatementModel(away=True), loop)
    finally:
        loop.close()
    assert r.first == 0.0 and not r.passes and "MISS" in E.format_result("stand-in", r)


def test_a_vision_model_that_reads_the_truth_meets_the_scan_bars():
    from steward_gateway.evals.statement_set import build
    from tests.statement_helpers import truth_answers
    queue = [a for sid in E.ONE_ACCOUNT for a in truth_answers(build(sid)[1])]
    fake = FakeStatementModel(page=lambda request: queue.pop(0))
    loop = asyncio.new_event_loop()
    try:
        r = E.run_scan_eval(fake, loop)
    finally:
        loop.close()
    assert (r.statements, r.first, r.rows, r.invented) == (len(E.ONE_ACCOUNT), 1.0, 1.0, 0.0) and r.passes
    text = E.format_scan_result("stand-in", r)
    assert "Scan descriptions exactly right: 100%" in text and "MISS" not in text


def test_a_vision_model_that_slips_digits_misses_and_says_so():
    from steward_gateway.evals.statement_set import build
    from tests.statement_helpers import truth_answers
    queue = [a for sid in E.ONE_ACCOUNT for a in truth_answers(build(sid)[1], slip_cents=100)]
    fake = FakeStatementModel(page=lambda request: queue.pop(0))
    loop = asyncio.new_event_loop()
    try:
        r = E.run_scan_eval(fake, loop)
    finally:
        loop.close()
    assert r.first == 0.0 and not r.passes and "MISS" in E.format_scan_result("stand-in", r)
