"""Quarterly estimates (spec 7.1), part one: the dates. Form 1040-ES and Form 540-ES (2026); weekend and holiday
shifts (ruling 9); which tax year is current (ruling 2); return due dates (ruling 13)."""
from datetime import date

from steward.engine.tax import estimates as E
from steward.engine.tax import rules


def test_the_2026_dates_and_shares():
    fed = E.schedule(2026, "federal", "CA")
    assert [i.due for i in fed] == [date(2026, 4, 15), date(2026, 6, 15), date(2026, 9, 15), date(2027, 1, 15)]
    assert [i.share for i in fed] == [0.25, 0.25, 0.25, 0.25]
    ca = E.schedule(2026, "state", "CA")
    assert [(i.due, i.share) for i in ca] == [(date(2026, 4, 15), 0.30), (date(2026, 6, 15), 0.40),
                                              (date(2026, 9, 15), 0.0), (date(2027, 1, 15), 0.30)]


def test_due_dates_move_past_weekends_and_holidays():
    # 2028-01-15 is a Saturday and Monday the 17th is Martin Luther King Jr. Day
    assert E.schedule(2027, "federal", "CA")[-1].due == date(2028, 1, 18)
    assert E.schedule(2027, "state", "CA")[-1].due == date(2028, 1, 18)
    # 2028-04-15 is a Saturday; Emancipation Day (Sunday the 16th) is observed Monday the 17th in Washington, DC
    assert E.schedule(2028, "federal", "CA")[0].due == date(2028, 4, 18)
    assert E.schedule(2028, "state", "CA")[0].due == date(2028, 4, 17)
    # 2029-01-15 is Martin Luther King Jr. Day itself; 2029-04-15 is a Sunday and Monday the 16th is Emancipation Day
    assert E.schedule(2028, "federal", "CA")[-1].due == date(2029, 1, 16)
    assert E.schedule(2029, "federal", "CA")[0].due == date(2029, 4, 17)
    assert E.next_business_day(date(2026, 6, 15), "federal") == date(2026, 6, 15)


def test_states_without_a_schedule_have_none():
    assert E.schedule(2026, "state", "TX") == ()       # no wage tax
    assert E.schedule(2026, "state", "NY") == ()       # not calculated yet


def test_the_tax_year_stays_last_year_until_its_january_date():
    assert E.tax_year_for(date(2026, 10, 13)) == 2026
    assert E.tax_year_for(date(2027, 1, 1)) == 2026
    assert E.tax_year_for(date(2027, 1, 15)) == 2026
    assert E.tax_year_for(date(2027, 1, 16)) == 2027
    assert E.tax_year_for(date(2028, 1, 18)) == 2027   # the moved date still belongs to 2027
    assert E.last_federal_due(2025) == date(2026, 1, 15)


def test_return_due_dates():
    assert E.return_due(2025) == date(2026, 4, 15)
    assert E.return_due(2026) == date(2027, 4, 15) and E.extended_return_due(2026) == date(2027, 10, 15)
    assert E.return_due(2027) == date(2028, 4, 18)


def test_the_tables_carry_what_estimates_need():
    f = rules.table("federal", 2026)["estimates"]
    assert f["shares"] == [0.25, 0.25, 0.25, 0.25] and f["minimum_owed"] == 1000
    assert f["skip_fourth_if_filed_by"] == "02-01"
    c = rules.table("california", 2026)["estimates"]
    assert c["minimum_owed"] == 500 and c["skip_fourth_if_filed_by"] == "01-31"
    for year in (2025, 2026):
        assert rules.table("federal", year)["returns"] == {"due": "04-15", "extended_due": "10-15"}
    r = rules.table("retirement", 2026)
    assert r["solo_401k_after_year_end_from"] == 2023
    assert (r["sep_rate"], r["self_employed_employer_rate"], r["compensation_cap"]) == (0.25, 0.20, 360000)


def test_the_2025_federal_schedule_works_for_early_january_2026():
    fed = E.schedule(2025, "federal", "CA")
    assert [i.due for i in fed] == [date(2025, 4, 15), date(2025, 6, 16), date(2025, 9, 15), date(2026, 1, 15)]
    assert [i.share for i in fed] == [0.25, 0.25, 0.25, 0.25]
    f = rules.table("federal", 2025)["estimates"]
    assert f["minimum_owed"] == 1000 and f["skip_fourth_if_filed_by"] == "02-02"   # Form 1040-ES (2025)
    assert E.tax_year_for(date(2026, 1, 10)) == 2025
    assert E.schedule(E.tax_year_for(date(2026, 1, 10)), "federal", "CA")


# Part two: the worksheets (rulings 3, 5, 7, 8). Amounts are cents.


def test_the_safe_harbor_wins_when_it_is_lower_and_payments_carry_forward():
    # This year's federal tax $20,000 (90%: $18,000); 2025's $15,000 at an AGI of $160,000, so 110%: $16,500.
    # Withholding $10,000 leaves $6,500: $1,625 a date. $2,000 paid April 10 and $1,250 on July 1.
    p = E.agency_plan("federal", year=2026, state="CA", current_tax_cents=2_000_000, current_agi_cents=20_000_000,
                      prior=E.PriorYear(1_500_000, 16_000_000), withholding_cents=1_000_000,
                      payments=[(date(2026, 4, 10), 200_000), (date(2026, 7, 1), 125_000)])
    assert (p.method, p.prior_share, p.prior_required_cents, p.current_required_cents) == ("prior_year", 1.10, 1_650_000, 1_800_000)
    assert (p.required_cents, p.balance_cents, p.paid_cents, p.minimum_cents) == (1_650_000, 650_000, 325_000, 100_000)
    assert [d.installment_cents for d in p.dues] == [162_500] * 4
    assert [d.by_then_cents for d in p.dues] == [162_500, 325_000, 487_500, 650_000]
    assert [d.paid_cents for d in p.dues] == [200_000, 200_000, 325_000, 325_000]
    assert [d.still_due_cents for d in p.dues] == [0, 125_000, 162_500, 325_000]
    assert p.skip_fourth_if_filed_by == date(2027, 2, 1) and p.rules_year == 2026


def test_california_pays_30_40_0_30_of_what_withholding_leaves():
    # This year's $6,000 (90%: $5,400); 2025's $5,000 at a California AGI of exactly $150,000, so 100%: $5,000.
    p = E.agency_plan("state", year=2026, state="CA", current_tax_cents=600_000, current_agi_cents=19_000_000,
                      prior=E.PriorYear(500_000, 15_000_000), withholding_cents=300_000, payments=[])
    assert (p.method, p.prior_share, p.required_cents, p.balance_cents) == ("prior_year", 1.00, 500_000, 200_000)
    assert [d.installment_cents for d in p.dues] == [60_000, 80_000, 0, 60_000]
    assert [d.by_then_cents for d in p.dues] == [60_000, 140_000, 140_000, 200_000]
    assert (p.minimum_cents, p.rules_year, p.skip_fourth_if_filed_by) == (50_000, 2025, date(2027, 1, 31))


def test_california_needs_this_years_tax_at_a_million():
    p = E.agency_plan("state", year=2026, state="CA", current_tax_cents=9_000_000, current_agi_cents=100_000_000,
                      prior=E.PriorYear(1_000_000, 50_000_000), withholding_cents=0, payments=[])
    assert (p.method, p.prior_not_allowed, p.prior_required_cents, p.required_cents) == ("current_year", True, None, 8_100_000)


def test_without_last_years_figures_only_the_current_year_method():
    p = E.agency_plan("federal", year=2026, state="CA", current_tax_cents=2_000_000, current_agi_cents=20_000_000,
                      prior=None, withholding_cents=0, payments=[])
    assert (p.method, p.prior_required_cents, p.required_cents, p.balance_cents) == ("current_year", None, 1_800_000, 1_800_000)


def test_under_the_minimum_no_estimates_are_needed():
    p = E.agency_plan("federal", year=2026, state="CA", current_tax_cents=1_000_000, current_agi_cents=9_000_000,
                      prior=None, withholding_cents=950_000, payments=[])
    assert (p.method, p.required_cents, p.balance_cents) == ("none_needed", 0, 0)
    assert all(d.by_then_cents == 0 and d.still_due_cents == 0 for d in p.dues)


def test_no_tax_last_year_means_nothing_is_required():
    p = E.agency_plan("federal", year=2026, state="CA", current_tax_cents=500_000, current_agi_cents=4_000_000,
                      prior=E.PriorYear(0, 0), withholding_cents=0, payments=[])
    assert (p.method, p.required_cents, p.balance_cents) == ("prior_year", 0, 0)


def test_a_state_without_a_schedule_has_no_plan():
    for state in ("TX", "NY"):
        assert E.agency_plan("state", year=2026, state=state, current_tax_cents=0, current_agi_cents=0, prior=None,
                             withholding_cents=0, payments=[]) is None


def test_a_negative_tax_counts_as_none():
    p = E.agency_plan("federal", year=2026, state="CA", current_tax_cents=-300_000, current_agi_cents=3_000_000,
                      prior=None, withholding_cents=0, payments=[])
    assert (p.current_tax_cents, p.method) == (0, "none_needed")
