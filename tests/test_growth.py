"""This year's three figures and the chart's series (investment views spec, The investment account page)."""
from datetime import date, timedelta

from steward.services import contributed as C
from steward.services import growth as G
from steward.services.accounts import record_balance
from tests.factories import add_fact, make_account, make_txn

TODAY = date(2026, 10, 13)


def _year(db, a, today=TODAY):
    return G.year_figures(db, a, today, C.this_year(db, a, today))


def test_this_year_runs_from_jan_1_when_a_balance_from_before_it_exists(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    for d, c in ((date(2025, 12, 31), 100_000_00), (date(2026, 6, 1), 110_000_00), (date(2026, 10, 13), 130_000_00)):
        record_balance(db, a.id, d, c)
    make_txn(db, a, date(2026, 3, 1), 10_000_00, "TRANSFER FROM CHECKING", category="transfer", is_transfer=True)
    make_txn(db, a, date(2026, 5, 1), 2_000_00, "EMPLOYER MATCH")
    make_txn(db, a, date(2026, 7, 1), -1_000_00, "TRANSFER TO CHECKING", category="transfer", is_transfer=True)
    make_txn(db, a, date(2026, 8, 1), 300_00, "DIVIDEND", category="interest")
    assert _year(db, a) == G.YearFigures(date(2026, 1, 1), True, 100_000_00, 130_000_00, 30_000_00, 30.0,
                                         11_000_00, 19_000_00, False)


def test_without_a_balance_from_before_jan_1_it_runs_from_the_first_one(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    record_balance(db, a.id, date(2026, 3, 15), 50_000_00)
    record_balance(db, a.id, date(2026, 10, 13), 55_000_00)
    make_txn(db, a, date(2026, 3, 15), 1_000_00, "TRANSFER", category="transfer", is_transfer=True)   # already in the start
    make_txn(db, a, date(2026, 4, 1), 2_000_00, "TRANSFER", category="transfer", is_transfer=True)
    assert _year(db, a) == G.YearFigures(date(2026, 3, 15), False, 50_000_00, 55_000_00, 5_000_00, 10.0,
                                         2_000_00, 3_000_00, False)


def test_a_zero_start_has_no_percent(db):
    """Review Focus 4."""
    a = make_account(db, "Roth IRA", type="roth_ira", owner="jr")
    record_balance(db, a.id, date(2026, 2, 1), 0)
    record_balance(db, a.id, date(2026, 10, 1), 5_000_00)
    make_txn(db, a, date(2026, 3, 1), 5_000_00, "CONTRIBUTION", category="transfer", is_transfer=True)
    y = _year(db, a)
    assert (y.change_cents, y.change_pct, y.put_in_cents, y.growth_cents) == (5_000_00, None, 5_000_00, 0)


def test_no_balance_this_year_means_no_figures(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    assert _year(db, a) is None
    record_balance(db, a.id, date(2025, 11, 1), 1_000_00)
    assert _year(db, a) is None


def test_jrs_401k_on_the_pay_facts_counts_them_prorated_to_the_window(db):
    add_fact(db, "jr.payroll_k401_cents", "1800000", date(2026, 9, 30))
    k = make_account(db, "401(k)", type="k401", owner="jr")
    record_balance(db, k.id, date(2025, 12, 31), 400_000_00)
    record_balance(db, k.id, date(2026, 10, 13), 450_000_00)
    y = _year(db, k)
    assert (y.put_in_cents, y.growth_cents, y.estimated) == (18_000_00, 32_000_00, False)


def test_a_window_that_starts_in_july_counts_only_its_share_of_the_payroll_figure(db):
    add_fact(db, "jr.payroll_k401_cents", "1800000", date(2026, 9, 30))
    k = make_account(db, "401(k)", type="k401", owner="jr")
    record_balance(db, k.id, date(2026, 7, 1), 400_000_00)
    record_balance(db, k.id, date(2026, 10, 13), 410_000_00)
    # Counted from Jul 2 to Sep 30, 91 of the figure's 273 days: 1,800,000 x 91 / 273 = 600,000.
    assert _year(db, k).put_in_cents == 6_000_00


def test_the_series_runs_from_the_first_snapshot_with_the_running_total_put_in(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    for d, c in ((date(2026, 1, 10), 1_000_00), (date(2026, 2, 10), 1_200_00), (date(2026, 3, 10), 1_500_00)):
        record_balance(db, a.id, d, c)
    make_txn(db, a, date(2026, 1, 10), 50_00, "TRANSFER", category="transfer", is_transfer=True)   # in the first balance
    make_txn(db, a, date(2026, 1, 20), 100_00, "TRANSFER", category="transfer", is_transfer=True)
    make_txn(db, a, date(2026, 3, 1), 200_00, "TRANSFER", category="transfer", is_transfer=True)
    first, pts = G.series(db, a, TODAY, C.this_year(db, a, TODAY))
    assert first == date(2026, 1, 10)
    assert pts == [{"date": "2026-01-10", "balance_cents": 1_000_00, "put_in_cents": 0},
                   {"date": "2026-02-10", "balance_cents": 1_200_00, "put_in_cents": 100_00},
                   {"date": "2026-03-10", "balance_cents": 1_500_00, "put_in_cents": 300_00}]


def test_a_long_series_is_thinned_and_keeps_its_first_and_last_days(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    start = date(2025, 9, 8)
    for i in range(400):
        record_balance(db, a.id, start + timedelta(days=i), 1_000_00 + i)
    _, pts = G.series(db, a, TODAY, C.this_year(db, a, TODAY))
    assert len(pts) <= G.MAX_POINTS + 1
    assert pts[0]["date"] == "2025-09-08" and pts[-1]["date"] == (start + timedelta(days=399)).isoformat()
