"""The redaction timing (release spec 2026-11-05, section 7, "Speed"): local only, with the real models when someone
runs it; here with the stand-in detectors and a ticking clock."""
from typer.testing import CliRunner

from steward_gateway import cli
from steward_gateway.evals import redaction as R
from steward_gateway.redact.patterns import PatternDetector
from tests.gateway.fakes import NameListDetector

TICK = 2 ** -7          # exact in binary, so each read measures 7.8125 ms


def ticking():
    now = [0.0]

    def clock():
        now[0] += TICK
        return now[0]
    return clock


def test_the_sample_is_the_bench_and_answers_questions():
    from steward_gateway.evals.answers_set import CASES
    from steward_gateway.evals.bench import NO_TOOLS
    assert R.SAMPLE == NO_TOOLS + tuple(c.question for c in CASES) and len(R.SAMPLE) == 38
    assert len(R.LONG_TEXT) == 1000


def test_each_question_is_read_once_after_a_warm_up_and_the_long_text_repeats(monkeypatch):
    seen, real = [], R.redact
    monkeypatch.setattr(R, "redact", lambda text, detectors: (seen.append(text), real(text, detectors))[1])
    monkeypatch.setattr(R, "_torch_threads", lambda: 4)
    t = R.run_redaction([PatternDetector(), NameListDetector()], clock=ticking(), long_repeats=4)
    assert seen == [R.SAMPLE[0], *R.SAMPLE, *[R.LONG_TEXT] * 4]
    assert t == R.RedactionTiming(device="cpu", threads=4, questions=38, question_p50_ms=7.8, question_p95_ms=7.8,
                                  long_p50_ms=7.8, long_p95_ms=7.8)


def test_the_timing_reads_plainly():
    t = R.RedactionTiming(device="cpu", threads=4, questions=38, question_p50_ms=118.4, question_p95_ms=203.0,
                          long_p50_ms=611.2, long_p95_ms=702.6)
    assert R.format_redaction(t) == (
        "Redaction on cpu (4 threads), one read:\n"
        "  A question (38): p50 118 ms, p95 203 ms\n"
        "  1,000 characters: p50 611 ms, p95 703 ms\n"
        "A turn reads the question three times before it's sent (the preview, the turn and the check) and each tool "
        "result once.")
    assert R.format_redaction(R.RedactionTiming("cuda", None, 38, 9.0, 12.0, 40.0, 55.0)).startswith(
        "Redaction on cuda, one read:\n")


def test_the_command_needs_the_models_and_prints_the_timing(monkeypatch):
    monkeypatch.setattr("steward_gateway.redact.load_real_detectors",
                        lambda: ([], "The redaction models didn't load (ImportError)."))
    r = CliRunner().invoke(cli.app, ["eval", "redaction"])
    assert r.exit_code == 1 and r.output.strip() == "The redaction models didn't load (ImportError)."
    monkeypatch.setattr("steward_gateway.redact.load_real_detectors",
                        lambda: ([PatternDetector(), NameListDetector()], None))
    monkeypatch.setattr(R, "_torch_threads", lambda: None)
    r = CliRunner().invoke(cli.app, ["eval", "redaction"])
    assert r.exit_code == 0 and r.output.startswith("Redaction on cpu, one read:\n  A question (38): p50 ")
