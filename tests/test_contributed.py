"""Contributions per account this year (investment views spec, Contributions and limits): deposits by what they are,
JR's 401(k) and the HSA on the pay facts when they show none, rollovers never toward a limit, and on pace."""
from datetime import date

import pytest

from steward.services import contributed as C
from steward.services import limits as L
from tests.factories import add_fact, make_account, make_txn

TODAY = date(2026, 10, 13)


def pair(db, a, b):
    a.transfer_peer_id, b.transfer_peer_id = b.id, a.id
    db.commit()


def _pay(db, payroll_as_of: date | None = date(2026, 9, 30)):
    for k, v in (("jr.dob", "1982-05-01"), ("spouse.dob", "1984-08-01"), ("filing_status", "mfj"),
                 ("jr.salary_cents", "16000000"), ("jr.k401_pct_bp", "1000"), ("employer.match_rate_bp", "5000"),
                 ("employer.match_cap_bp", "600")):
        add_fact(db, k, v)
    if payroll_as_of is not None:
        add_fact(db, "jr.payroll_k401_cents", "1800000", payroll_as_of)


def test_deposits_are_yours_the_match_a_rollover_or_money_out(db):
    k = make_account(db, "401(k)", type="k401", owner="jr", source="simplefin", institution_name="Workplace")
    trad = make_account(db, "Traditional IRA", type="traditional_ira", owner="jr")
    chk = make_account(db, "Checking")
    make_txn(db, k, date(2026, 2, 1), 1_000_00, "EMPLOYEE DEFERRAL")
    make_txn(db, k, date(2026, 2, 1), 500_00, "EMPLOYER MATCH")
    make_txn(db, k, date(2026, 3, 1), 20_000_00, "ROLLOVER IN FROM OLD PLAN")
    make_txn(db, k, date(2026, 3, 2), 300_00, "CONTRIBUTION")
    make_txn(db, k, date(2026, 4, 1), 45_00, "DIVIDEND VTI", category="interest")
    make_txn(db, k, date(2026, 4, 2), -12_00, "FEE", category="fees")
    out_ = make_txn(db, k, date(2026, 5, 1), -2_000_00, "TRANSFER TO CHECKING", category="transfer", is_transfer=True)
    in_ = make_txn(db, chk, date(2026, 5, 1), 2_000_00, "TRANSFER FROM 401K", category="transfer", is_transfer=True)
    pair(db, out_, in_)
    x = make_txn(db, trad, date(2026, 6, 1), -5_000_00, "TRANSFER", category="transfer", is_transfer=True)
    y = make_txn(db, k, date(2026, 6, 1), 5_000_00, "TRANSFER FROM IRA", category="transfer", is_transfer=True)
    pair(db, x, y)
    assert [(d.day, d.cents, d.kind) for d in C.deposits(db, [k.id], date(2026, 1, 1), date(2026, 10, 14))] == [
        (date(2026, 2, 1), 1_000_00, "you"), (date(2026, 2, 1), 500_00, "match"), (date(2026, 3, 1), 20_000_00, "rollover"),
        (date(2026, 3, 2), 300_00, "you"), (date(2026, 5, 1), -2_000_00, "out"), (date(2026, 6, 1), 5_000_00, "rollover")]
    c = C.this_year(db, k, TODAY)
    assert (c.you_cents, c.match_cents, c.rollover_cents, c.out_cents, c.net_cents) == (1_300_00, 500_00, 25_000_00, 2_000_00, 24_800_00)


def test_this_years_deposits_come_before_the_pay_facts(db):
    _pay(db)
    k = make_account(db, "401(k)", type="k401", owner="jr")
    make_txn(db, k, date(2026, 2, 1), 1_000_00, "EMPLOYEE DEFERRAL")
    c = C.this_year(db, k, TODAY)
    assert (c.you_cents, c.you_from, c.match_cents, c.match_from, c.through) == (1_000_00, "deposits", 0, "none", TODAY)


def test_the_payroll_figure_counts_for_jrs_own_401k_with_an_estimated_match(db):
    _pay(db)
    k = make_account(db, "401(k)", type="k401", owner="jr")
    c = C.this_year(db, k, TODAY)
    assert (c.you_cents, c.you_from, c.through) == (1_800_000, "payroll", date(2026, 9, 30))
    # Salary to Sep 30: 16,000,000 x 273 // 365 = 11,967,123; the 6% cap: 718,027; min(1,800,000, 718,027) x 50%.
    assert (c.match_cents, c.match_from) == (359_013, "estimate") and c.estimated


def test_a_payroll_figure_from_last_year_is_ignored_and_the_estimate_says_so(db):
    """Review Focus 3."""
    _pay(db, payroll_as_of=date(2025, 12, 20))
    k = make_account(db, "401(k)", type="k401", owner="jr")
    c = C.this_year(db, k, TODAY)
    # $160,000 x 10% = $16,000 a year; January to September is 9 months: $12,000, through Sep 30.
    assert (c.you_cents, c.you_from, c.through) == (1_200_000, "estimate", date(2026, 9, 30)) and c.estimated
    [line] = [x for x in C.limit_lines(db, TODAY) if x.kind == "k401"]
    assert line.in_cents == 1_200_000 and line.estimated


def test_only_jrs_first_401k_takes_the_pay_facts(db):
    _pay(db)
    make_account(db, "401(k)", type="k401", owner="jr")
    old = make_account(db, "Old 401(k)", type="k401", owner="jr")
    sam = make_account(db, "Sam's 401(k)", type="k401", owner="spouse")
    assert C.this_year(db, old, TODAY).you_from == "none" and C.this_year(db, sam, TODAY).you_from == "none"


def test_without_pay_facts_or_deposits_nothing_is_counted(db):
    k = make_account(db, "401(k)", type="k401", owner="jr")
    c = C.this_year(db, k, TODAY)
    assert (c.you_cents, c.you_from, c.match_cents, c.estimated) == (0, "none", 0, False)


def test_on_pace_and_the_raise_for_jrs_401k(db):
    _pay(db)
    make_account(db, "401(k)", type="k401", owner="jr")
    [line] = [x for x in C.limit_lines(db, TODAY) if x.kind == "k401"]
    # 1,800,000 x 365 / 273 = 2,406,593.4; 24,500 - that = 434.07; the 92 days left pay 4,032,876.7 of salary;
    # 43,407 x 100 / 4,032,876.7 = 1.08, so 2%.
    assert (line.owner, line.limit_cents, line.in_cents, line.on_pace_cents, line.short_cents, line.raise_pct) == (
        "jr", 2_450_000, 1_800_000, 2_406_593, 43_407, 2)
    assert not line.maxed and not line.estimated


def test_an_ira_at_its_limit_is_maxed_and_a_rollover_doesnt_count(db):
    _pay(db)
    roth = make_account(db, "Roth IRA", type="roth_ira", owner="jr")
    make_txn(db, roth, date(2026, 1, 5), 7_500_00, "CONTRIBUTION", category="transfer", is_transfer=True)
    make_txn(db, roth, date(2026, 2, 5), 50_000_00, "ROLLOVER IN")
    [line] = [x for x in C.limit_lines(db, TODAY) if x.kind == "ira"]
    assert (line.in_cents, line.limit_cents, line.maxed, line.short_cents, line.raise_pct) == (750_000, 750_000, True, 0, None)


def test_the_hsa_is_the_households_and_counts_the_employers_deposits(db):
    _pay(db, payroll_as_of=None)
    add_fact(db, "jr.payroll_hsa_cents", "300000", date(2026, 9, 30))
    h = make_account(db, "HSA", type="hsa", owner="jr")
    h2 = make_account(db, "HSA 2", type="hsa", owner="spouse")
    make_txn(db, h2, date(2026, 3, 1), 100_000, "EMPLOYER CONTRIBUTION")
    assert (C.this_year(db, h, TODAY).you_cents, C.this_year(db, h, TODAY).you_from) == (300_000, "payroll")
    [line] = [x for x in C.limit_lines(db, TODAY) if x.kind == "hsa"]
    assert (line.owner, line.limit_cents, line.in_cents, line.account_ids) == ("household", 875_000, 400_000, (h.id, h2.id))


def test_a_business_or_joint_401k_has_no_limit_line(db):
    make_account(db, "Solo 401(k)", type="k401", owner="business")
    make_account(db, "Joint 401(k)", type="k401", owner="joint")
    assert C.limit_lines(db, TODAY) == []


def test_without_this_years_limits_the_lines_have_none(db, monkeypatch):
    monkeypatch.setattr(L, "have_year", lambda year: False)
    _pay(db)
    make_account(db, "401(k)", type="k401", owner="jr")
    [line] = C.limit_lines(db, TODAY)
    assert (line.limit_cents, line.short_cents, line.raise_pct, line.maxed) == (None, 0, None, False)
    assert C.limits_out(db, TODAY)["missing"] is True


def test_no_raise_on_the_last_day(db):
    _pay(db, payroll_as_of=date(2026, 12, 31))
    make_account(db, "401(k)", type="k401", owner="jr")
    [line] = [x for x in C.limit_lines(db, date(2026, 12, 31)) if x.kind == "k401"]
    assert line.short_cents == 650_000 and line.raise_pct is None
