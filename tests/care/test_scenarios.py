"""Care scenarios (spec 4.1, 9): projections with known answers. FLAT assumptions (no inflation, no growth) and no
income keep tax at zero, so every number is arithmetic. Fictional parent: Margaret Ellis, born 1944."""
from dataclasses import replace
from datetime import date

from steward.care import costs as C
from steward.care.book import CareBook, PolicyTerms
from steward.care.scenarios import (
    care_start, inputs_for, label, levers, projection_years, run, tax_line,
)
from steward.care.store import Scenario
from steward.engine.project import Assumptions, project

FLAT = Assumptions(inflation=0.0, real_return=0.0, care_inflation=0.0)
FIGS = C.figures({}, 2026, 0.0)          # assisted living $7,000 a month, as published


def book(**kw) -> CareBook:
    base = dict(this_year=2026, person_label="Margaret", birth_year=1944, spouse_birth_year=None, state="CA",
                care_inflation=0.0, cash_cents=30_000_000, taxable_cents=0, traditional_cents=0, roth_cents=0,
                home_value_cents=None, incomes=(), spending_yearly_cents=4_000_000, spending_months=12,
                spending_typed=False, policies=(), notes=())
    base.update(kw)
    return CareBook(**base)


def test_years_run_to_age_100_within_1_to_40():
    assert [projection_years(a) for a in (82, 66, 55, 100)] == [19, 35, 40, 1]


def test_a_parent_past_100_gets_one_year():
    r = run(book(birth_year=1925, cash_cents=10_000_000_000), Scenario(1, "at_home"), FIGS, FLAT)
    assert len(r.years) == 1 and r.headline == "Lasts past age 101" and r.lasts_until is None


def test_at_home_a_fixed_balance_runs_out_in_a_known_year():
    # $300,000 in cash, $40,000 a year: 2026-2032 are paid, 2033 is short
    r = run(book(), Scenario(1, "at_home"), FIGS, FLAT)
    assert len(r.years) == 19 and r.years[-1].age == 100
    assert (r.lasts_until, r.lasts_until_age, r.headline) == (2032, 88, "Money lasts until 2032 (age 88)")
    assert [y.balance_cents for y in r.years[:5]] == [26_000_000, 22_000_000, 18_000_000, 14_000_000, 10_000_000]
    assert r.years[7].short_cents == 2_000_000 and all(y.tax_cents == 0 for y in r.years)
    # the Medi-Cal line flips in the year assets cross the $130,000 limit
    assert [y.medi_cal.status for y in r.years[2:5]] == ["over_limit", "over_limit", "eligible"]
    assert r.years[3].medi_cal.over_cents == 1_000_000
    assert r.medi_cal_first_year == 2030 and r.medi_cal_when == "Meets the Medi-Cal limit in 2030 (age 86)."
    assert r.medi_cal_line == "Medi-Cal in 2026: Not yet: countable assets are $130,000 over the limit (2026 rules)."
    assert (r.label, r.care_monthly_cents, r.cost_lines, r.ltc_line) == ("At home as today", 0, (), None)


def test_assisted_living_from_2028():
    r = run(book(), Scenario(2, "assisted_living", start_year=2028), FIGS, FLAT)
    assert r.label == "Assisted living from 2028" and r.care_monthly_cents == 700_000
    assert r.years[2].balance_cents == 9_600_000 and r.years[2].care_cents == 8_400_000
    assert (r.lasts_until, r.headline) == (2028, "Money lasts until 2028 (age 84)")
    assert r.medi_cal_line == "Medi-Cal in 2028: Eligible (2026 rules)." and r.medi_cal_first_year == 2028
    assert r.cost_lines == ("Assisted living: $7,000 a month. Typical in California: CareScout Cost of Care Survey 2025.",)
    assert r.quote is False
    care = inputs_for(book(), Scenario(2, "assisted_living", start_year=2028), 700_000).expenses[1]
    assert (care.kind, care.medical, care.growth, care.start_year, care.amount_cents) == ("care", True, "care", 2028, 8_400_000)


def test_long_term_care_insurance_pays_after_the_wait_until_the_pool_is_used():
    # $200 a day after 90 days from 2028, a $219,000 pool: $55,000, then $73,000 twice, then the last $18,000
    pol = PolicyTerms(7, 20_000, None, 90, 21_900_000, None, 0.0)
    r = run(book(policies=(pol,)), Scenario(2, "assisted_living", start_year=2028), FIGS, FLAT)
    assert [y.ltc_cents for y in r.years[:6]] == [0, 0, 5_500_000, 7_300_000, 7_300_000, 1_800_000]
    assert (r.ltc_pays_from, r.ltc_runs_out) == (2028, 2031)
    assert r.ltc_line == "Long-term care insurance pays from 2028 and runs out in 2031."
    assert [y.balance_cents for y in r.years[2:5]] == [15_100_000, 10_000_000, 4_900_000]
    assert (r.lasts_until, r.lasts_until_age) == (2030, 86)
    assert r.medi_cal_line == "Medi-Cal in 2028: Eligible after spending down $21,000 (2026 rules)."
    assert r.medi_cal_first_year == 2029


def test_a_home_sale_lands_in_its_year_and_its_proceeds_count_for_medi_cal():
    s = Scenario(1, "at_home", sell_home_year=2028, home_basis_cents=80_000_000)
    r = run(book(home_value_cents=80_000_000), s, FIGS, FLAT)
    assert [y.home_sale_cents for y in r.years[:4]] == [0, 0, 75_200_000, 0]
    assert r.years[2].balance_cents == 93_200_000 and r.years[2].tax_cents == 0
    assert r.years[2].medi_cal.status == "over_limit" and r.years[2].medi_cal.countable_cents == 93_200_000
    assert levers(book(home_value_cents=80_000_000), s) == ("Home sold in 2028 for $800,000, less 6% selling costs",)
    blank = replace(s, home_basis_cents=None)
    assert inputs_for(book(home_value_cents=80_000_000), blank, 0).home_sale.basis_cents == 0
    assert levers(book(home_value_cents=80_000_000), blank) == (
        "Home sold in 2028 for $800,000, less 6% selling costs; no purchase price entered, so everything over the "
        "$250,000 exclusion counts as gain (2026 rules)",)


def test_family_help_and_spending_change():
    s = Scenario(1, "at_home", family_monthly_cents=50_000, spending_change_monthly_cents=-100_000)
    p = inputs_for(book(), s, 0)
    assert p.expenses[0].amount_cents == 2_800_000
    fam = p.incomes[-1]
    assert (fam.label, fam.amount_cents, fam.kind) == ("Family", 600_000, "nontaxable")
    assert levers(book(), s) == ("Family adds $500 a month from now", "Spending $1,000 a month less")
    assert inputs_for(book(), replace(s, spending_change_monthly_cents=-1_000_000), 0).expenses[0].amount_cents == 0
    assert levers(book(), replace(s, family_monthly_cents=0, spending_change_monthly_cents=25_000)) == (
        "Spending $250 a month more",)


def test_a_married_parent_files_jointly_with_the_two_person_limit():
    r = run(book(spouse_birth_year=1946), Scenario(1, "at_home"), FIGS, FLAT)
    p = inputs_for(book(spouse_birth_year=1946), Scenario(1, "at_home"), 0)
    assert (p.filing, p.birth_years) == ("mfj", (1944, 1946))
    assert r.years[0].medi_cal.limit.cents == 19_500_000


def test_labels_and_cost_lines():
    assert label(Scenario(1, "in_home_help", hours_week=20, adult_day_days=2), 2026) == (
        "In-home help, 20 hours a week, adult day 2 days a week, starting now")
    assert label(Scenario(1, "in_home_help", hours_week=1, start_year=2030), 2026) == "In-home help, 1 hour a week, from 2030"
    assert label(Scenario(1, "nursing_home", room="private", start_year=2026), 2026) == "Nursing home, private room, starting now"
    assert label(Scenario(1, "memory_care", start_year=2029), 2026) == "Memory care from 2029"
    figs = C.figures({"memory_care_monthly": C.Quote("memory_care_monthly", 900_000, date(2026, 9, 1))}, 2026, 0.0)
    r = run(book(), Scenario(1, "in_home_help", hours_week=20, adult_day_days=2), figs, FLAT)
    assert r.care_monthly_cents == 346_667 + 81_467
    assert r.cost_lines == ("In-home help: $40 an hour. Typical in California: CareScout Cost of Care Survey 2025.",
                            "Adult day: $94 a day. Typical in California: CareScout Cost of Care Survey 2025.")
    q = run(book(), Scenario(1, "memory_care"), figs, FLAT)
    assert q.quote is True and q.cost_lines == ("Memory care: $9,000 a month. Your quote, September 1, 2026.",)


def test_a_start_year_already_past_starts_now():
    # Review Focus 2: a scenario saved "from 2026" opened in 2027
    s = Scenario(1, "assisted_living", start_year=2026, sell_home_year=2026)
    assert care_start(s, 2027) == 2027 and label(s, 2027) == "Assisted living starting now"
    assert inputs_for(book(this_year=2027, home_value_cents=1), s, 700_000).home_sale.year == 2027


def test_money_that_runs_short_this_year_and_money_that_lasts():
    short = run(book(cash_cents=1_000_000), Scenario(1, "at_home"), FIGS, FLAT)
    assert short.headline == "Money runs short in 2026 (age 82)" and short.lasts_until == 2025
    rich = run(book(cash_cents=10_000_000_000), Scenario(1, "at_home"), FIGS, FLAT)
    assert rich.headline == "Lasts past age 100" and rich.last_age == 100
    assert rich.medi_cal_when == "Doesn't meet the Medi-Cal limit by age 100."


def test_the_tax_line_names_the_rules_year():
    r = run(book(), Scenario(1, "at_home"), FIGS, FLAT)
    assert r.tax_line.startswith("Tax uses 2026 federal rules") and "California" in r.tax_line
    ny = run(book(state="NY"), Scenario(1, "at_home"), FIGS, FLAT)
    assert ny.tax_line == "Tax uses 2026 federal rules. State tax isn't calculated for New York yet."
    first = project(inputs_for(book(state="NY"), Scenario(1, "at_home"), 0), FLAT, 1)[0]
    assert tax_line(first.tax) == ny.tax_line


def test_the_policy_premium_stops_once_it_pays():
    # M5: $200 a day after 90 days from 2028; the $2,544 a year premium (in spending) stops for the 275 days
    # paid ($1,916.71), then all year
    pol = PolicyTerms(7, 20_000, None, 90, 21_900_000, None, 0.0, premium_yearly_cents=254_400)
    s = Scenario(2, "assisted_living", start_year=2028)
    assert inputs_for(book(policies=(pol,)), s, 700_000).ltc_policies[0].premium_yearly_cents == 254_400
    rows = project(inputs_for(book(policies=(pol,)), s, 700_000), FLAT, 4)
    assert [r.expenses_cents for r in rows] == [4_000_000, 4_000_000, 12_208_329, 12_145_600]


def test_family_help_starts_when_care_starts():
    # M6: from the scenario's start year, not before; at home (or care starting now) it starts now
    later = Scenario(2, "assisted_living", start_year=2028, family_monthly_cents=50_000)
    fam = inputs_for(book(), later, 700_000).incomes[-1]
    assert (fam.label, fam.start_year) == ("Family", 2028)
    assert levers(book(), later) == ("Family adds $500 a month from 2028",)
    now = replace(later, start_year=None)
    assert inputs_for(book(), now, 700_000).incomes[-1].start_year == 2026
    assert levers(book(), now) == ("Family adds $500 a month from now",)
    assert levers(book(), replace(later, start_year=2020)) == ("Family adds $500 a month from now",)
