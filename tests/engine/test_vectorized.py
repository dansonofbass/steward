"""The plan's vectorized tax (spec 3.1, 3.5), driven from the dated tables."""
import numpy as np
import pytest

from steward.engine.inputs import Levers
from steward.engine.synthetic import synthetic_household
from steward.engine.tax import vectorized as v
from steward.engine.tax.state import module_for


def test_federal_schedules_reproduce_rev_proc_2025_32_cumulative_amounts():
    assert v.vec_rules(2026, "mfj").schedule.cum.tolist() == [0, 2480, 11600, 35932, 82048, 116896, 206583.5]
    assert v.vec_rules(2026, "single").schedule.cum.tolist() == [0, 1240, 5800, 17966, 41024, 58448, 192979.25]
    assert v.vec_rules(2040, "mfj").rules_year == 2026 and v.vec_rules(2040, "mfj").over_65 is None
    assert v.vec_rules(2026, "mfj").over_65 == (6000.0, 150000.0, 0.06)


def test_federal_tax_at_sample_incomes():
    mfj = v.vec_rules(2026, "mfj").schedule
    assert v.tax_on(mfj, 150_000) == pytest.approx(22_424)          # 11,600 + 22% of 49,200
    assert v.tax_on(v.vec_rules(2026, "single").schedule, 60_000) == pytest.approx(7_912)
    assert v.tax_on(mfj, 0) == 0 and v.tax_on(mfj, -5) == 0
    out = v.tax_on(mfj, np.array([[150_000.0, 0.0], [1_000_000.0, 24_800.0]]))
    assert out.shape == (2, 2) and out[1, 1] == pytest.approx(2_480)


def test_long_term_gains_stack_on_ordinary_income():
    r = v.vec_rules(2026, "mfj")
    assert v.ltcg_tax(50_000, 60_000, r) == pytest.approx(1_665)      # 48,900 at 0%, 11,100 at 15%
    assert v.ltcg_tax(600_000, 50_000, r) == pytest.approx(0.15 * 13_700 + 0.20 * 36_300)


def test_social_security_taxable_portion_follows_publication_915():
    r = v.vec_rules(2026, "mfj")
    assert v.taxable_social_security(20_000, 10_000, r) == 0
    assert v.taxable_social_security(20_000, 30_000, r) == pytest.approx(4_000)
    assert v.taxable_social_security(30_000, 40_000, r) == pytest.approx(15_350)
    assert v.taxable_social_security(24_000, 50_000, v.vec_rules(2026, "single")) == pytest.approx(20_400)


def test_self_employment_tax_respects_the_wage_base_already_used_by_salary():
    tax, half = v.se_tax(20_000, 160_000, 2026)
    assert tax == pytest.approx(0.124 * 18_470 + 0.029 * 18_470) and half == pytest.approx(tax / 2)
    assert v.se_tax(20_000, 190_000, 2026)[0] == pytest.approx(0.029 * 18_470)
    assert v.se_tax(0, 0, 2026) == (0.0, 0.0) and v.se_tax(400, 0, 2026) == (0.0, 0.0)   # under $400 of net earnings


def test_household_tax_combines_federal_state_and_the_rules_for_65_and_over():
    # MFJ, CA, both 65+: $80,000 ordinary, $20,000 gains, $30,000 Social Security. SS taxable 25,500; AGI 125,500.
    # 2026: deduction 32,200 + 2 x 1,650 + 2 x 6,000 = 47,500; taxable 78,000 (58,000 ordinary + 20,000 gains):
    # federal 2,480 + 12% x 33,200 = 6,464, gains in the 0% band. California on 100,000: 2,385.06 - 4 x 153 = 1,773.06
    assert v.household_tax(80_000, 20_000, 30_000, "mfj", "CA", 2, 2026) == pytest.approx(8_237.06)
    # 2029: the deduction for people 65 and over has ended: federal 7,904
    assert v.household_tax(80_000, 20_000, 30_000, "mfj", "CA", 2, 2029) == pytest.approx(9_677.06)
    assert v.household_tax(80_000, 20_000, 30_000, "mfj", "NY", 2, 2029) == pytest.approx(7_904)   # New York: not calculated
    assert v.household_tax(80_000, 20_000, 30_000, "mfj", "TX", 2, 2029) == pytest.approx(7_904)
    assert v.household_tax(0, 0, 0, "mfj", "CA", 0, 2026) == 0
    out = v.household_tax(np.full((4, 3), 80_000.0), np.full((4, 3), 20_000.0), np.full((4, 3), 30_000.0), "mfj", "CA", 2, 2026)
    assert out.shape == (4, 3) and np.allclose(out, 8_237.06)


def test_the_net_investment_income_tax_applies_to_gains_above_the_threshold():
    # single, TX, 2029: 190,000 ordinary + 40,000 gains -> AGI 230,000, 30,000 over $200,000: 3.8% x 30,000 = 1,140
    with_niit = v.household_tax(190_000, 40_000, 0, "single", "TX", 0, 2029)
    r = v.vec_rules(2029, "single")
    ordinary = 190_000 - 16_100
    expected = v.tax_on(r.schedule, ordinary) + v.ltcg_tax(ordinary, 40_000, r) + 0.038 * 30_000
    assert with_niit == pytest.approx(expected)


def _composed(o, g, b, filing, state, n_aged, year):
    """household_tax written as plain composition of the public helpers."""
    r = v.vec_rules(year, filing)
    agi = o + g + v.taxable_social_security(b, o + g, r)
    total = np.maximum(agi - v.over_65_deduction(agi, n_aged, r) - (r.standard + n_aged * r.aged), 0.0)
    gains = np.minimum(g, total)
    ordinary = total - gains
    federal = v.tax_on(r.schedule, ordinary) + v.ltcg_tax(ordinary, gains, r)
    federal = federal + np.where(gains > 0, r.niit_rate * np.minimum(g, np.maximum(agi - r.niit_threshold, 0.0)), 0.0)
    mod = module_for(state)
    return federal + (mod.vector_tax(o + g, agi, filing, n_aged, year) if mod else 0.0)


@pytest.mark.parametrize("year", [2026, 2029])
@pytest.mark.parametrize("state", ["CA", "TX", "NY"])
@pytest.mark.parametrize("filing", ["mfj", "single"])
def test_household_tax_hot_path_is_bit_for_bit_the_composed_helpers(year, state, filing):
    rng = np.random.default_rng(7)
    shape = (30, 400)
    scale = rng.choice([0.0, 20_000.0, 150_000.0, 900_000.0, 3_000_000.0], size=shape)
    o = rng.random(shape) * scale
    g = np.where(rng.random(shape) < 0.3, 0.0, rng.random(shape) * scale)
    b = np.where(rng.random(shape) < 0.3, 0.0, rng.random(shape) * 60_000.0)
    for n_aged in (0, 2):
        for args in ((o, g, b), (o, np.zeros(shape), b), (o, g, np.zeros(shape)), (o[:1, :1], np.zeros((1, 1)), np.zeros((1, 1)))):
            fast = v.household_tax(*args, filing, state, n_aged, year)
            ref = _composed(*(np.asarray(a, dtype=float) for a in args), filing, state, n_aged, year)
            assert np.shape(fast) == np.shape(ref)
            assert np.array_equal(fast, ref)
    for x in (0.0, 80_000.0, 2_000_000.0):
        fast = v.household_tax(x, x / 4, x / 3, filing, state, 2, year)
        assert np.ndim(fast) == 0
        assert fast == _composed(np.array([x]), np.array([x / 4]), np.array([x / 3]), filing, state, 2, year)[0]


def test_lever_income_after_tax_while_working():
    hh = synthetic_household().household
    base_wages = 144_000.0   # $160,000 salary less the 10% pre-tax 401(k) deferral
    assert v.lever_income_after_tax(hh, Levers(gift_cents=1_000_000, gift_until_year=2030), 2027, 45, 43, base_wages) == 10_000.0
    assert v.lever_income_after_tax(hh, Levers(gift_cents=1_000_000, gift_until_year=2030), 2031, 49, 47, base_wages) == 0.0
    consulting = Levers(consulting_cents=2_000_000, consulting_until_age=60)
    # SE tax 2,825.91 (half deductible); 22% federal and California 8% -> 9.3% on the rest
    assert v.lever_income_after_tax(hh, consulting, 2027, 45, 43, base_wages) == pytest.approx(11_523.52, abs=0.05)
    assert v.lever_income_after_tax(hh, consulting, 2042, 60, 58, base_wages) == 0.0
    spouse = Levers(spouse_earnings_cents=6_000_000, spouse_start_year=2028, spouse_stop_age=65)
    assert v.lever_income_after_tax(hh, spouse, 2027, 45, 43, base_wages) == 0.0
    assert 60_000 * 0.55 < v.lever_income_after_tax(hh, spouse, 2028, 46, 44, base_wages) < 60_000 * (1 - 0.0765)


def test_lever_income_parts_for_the_retirement_return():
    hh = synthetic_household().household
    li = v.lever_income(hh, Levers(consulting_cents=2_000_000, consulting_until_age=70, gift_cents=500_000, gift_until_year=2050),
                        2045, 63, 61, 0.0)
    se, half = v.se_tax(20_000, 0.0, 2045)
    assert li.cash == pytest.approx(20_000 + 5_000 - se) and li.ordinary == pytest.approx(20_000 - half)
    spouse = v.lever_income(hh, Levers(spouse_earnings_cents=4_000_000, spouse_start_year=2040, spouse_stop_age=70), 2045, 63, 61, 0.0)
    assert spouse.cash == pytest.approx(40_000 * (1 - 0.0765)) and spouse.ordinary == 40_000


def test_the_se_wage_base_counts_the_business_owners_wages_not_jrs():
    # JR earns above the wage base; when the spouse runs the business the spouse has no wages, so the full
    # 12.4% Social Security part applies to the consulting profit (tax decisions carried item 1).
    from dataclasses import replace
    hh = replace(synthetic_household().household, salary_cents=25_000_000)
    consulting = Levers(consulting_cents=2_000_000, consulting_until_age=60)
    jr_runs = v.lever_income_after_tax(hh, consulting, 2027, 45, 43, 200_000.0)
    spouse_runs = v.lever_income_after_tax(replace(hh, business_owner=1), consulting, 2027, 45, 43, 200_000.0)
    assert spouse_runs < jr_runs - 1_500          # about $2,300 more Social Security tax, less the half that comes off income
    assert replace(hh, business_owner=0) == hh
