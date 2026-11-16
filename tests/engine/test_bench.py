from typer.testing import CliRunner

from steward.cli import app
from steward.engine.bench import format_bench, run_bench

runner = CliRunner()


def test_run_bench_times_the_synthetic_household():
    res = run_bench(runs=2, histories=200)
    assert len(res.solve_ms) == 2 and all(t > 0 for t in res.solve_ms) and res.impacts_ms > 0 and res.impacts_worst_ms > 0
    assert res.histories == 200 and res.ages == 27 and res.cpu
    text = format_bench(res)
    assert "solve" in text and "impacts" in text and "budget 400 ms" in text and "budget 3000 ms" in text
    assert "Lever impacts, worst case (not comfortable by 70)" in text


def test_worst_case_impacts_count_toward_the_budget():
    from dataclasses import replace
    res = run_bench(runs=1, histories=100)
    fast = replace(res, solve_ms=(1.0,), impacts_ms=1.0, impacts_worst_ms=1.0)
    assert fast.within_budget
    assert not replace(fast, impacts_worst_ms=fast.impacts_budget_ms + 1).within_budget
    assert "OVER BUDGET" in format_bench(replace(fast, impacts_worst_ms=fast.impacts_budget_ms + 1))


def test_bench_command_runs_without_a_database(monkeypatch):
    monkeypatch.delenv("STEWARD_DATA_DIR", raising=False)   # the command must not need the vault or its settings
    r = runner.invoke(app, ["bench", "--runs", "1", "--histories", "200"])
    assert r.exit_code in (0, 1), r.output                   # 1 only when a budget is exceeded on this machine
    assert "steward bench" in r.output and "solve" in r.output and "impacts" in r.output


def test_bench_needs_at_least_one_run():
    r = runner.invoke(app, ["bench", "--runs", "0", "--histories", "100"])
    assert r.exit_code == 2, r.output                       # a usage error, not a StatisticsError traceback
    assert "StatisticsError" not in r.output
