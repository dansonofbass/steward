from dataclasses import replace

import numpy as np
import pytest

from steward.engine import datafiles, simulate as sim
from steward.engine.inputs import Bucket, Child, Levers, Mix, Person
from steward.engine.market import Histories
from steward.engine.synthetic import synthetic_household
from steward.engine.tax import rules
from steward.engine.tax.vectorized import household_tax, se_tax

CASH = Mix(0.0, 0.0, 1.0)


def flat(hh, n_hist=4, seed=1):
    """A Prepared bundle whose markets return exactly zero in real terms."""
    prep = sim.prepare(hh, n_hist=n_hist, seed=seed)
    zeros = np.zeros((n_hist, prep.n_years))
    return replace(prep, hist=Histories(stock=zeros, bond=zeros, cash=zeros, source_index=zeros.astype(np.int64)))


def bare(**overrides):
    """A household with nothing but what the test sets: no salary, no Social Security, no mortgage, no children."""
    base = dict(
        jr=Person(1966, "male"), spouse=Person(1966, "female"), salary_cents=0, k401_pct_bp=0, match_rate_bp=0, match_cap_bp=0,
        spending_basis_cents=5_000_000, surplus_cents=0, mortgage_payment_cents=0, mortgage_payoff_year=None,
        health_premium_cents=0, cash=Bucket(0, CASH), taxable=Bucket(0, CASH), traditional=Bucket(0, CASH),
        roth=Bucket(0, CASH), hsa=Bucket(0, CASH), children=(),
    )
    base.update(overrides)
    return synthetic_household(**base)


def test_horizon_runs_until_the_younger_spouse_is_95():
    hh = synthetic_household().household          # born 1982 and 1984, plan year 2026
    assert sim.horizon_years(hh) == 95 - 42
    assert sim.horizon_years(synthetic_household(spouse=Person(1970, "female")).household) == 95 - 44


def test_prepare_is_deterministic_and_draws_deaths_after_markets():
    hh = synthetic_household().household
    a = sim.prepare(hh, n_hist=50)
    b = sim.prepare(hh, n_hist=50)
    assert np.array_equal(a.hist.stock, b.hist.stock) and np.array_equal(a.deaths.jr, b.deaths.jr)
    assert a.hist.stock.shape == (50, a.n_years) and a.deaths.spouse.shape == (50,)


def test_rmd_rules():
    assert sim.rmd_start_age(1982) == 75 and sim.rmd_start_age(1960) == 75
    assert sim.rmd_start_age(1955) == 73 and sim.rmd_start_age(1950) == 72
    assert sim.rmd_divisor(75) == 24.6 and sim.rmd_divisor(90) == 12.2 and sim.rmd_divisor(125) == 2.0


def test_college_cost_grows_one_percent_a_year_above_inflation():
    assert sim.college_cost("in_state_public", 2026, 2026) == pytest.approx(30_990)
    assert sim.college_cost("private", 2033, 2026) == pytest.approx(65_470 * 1.01 ** 7)


def test_flat_market_retirement_drawdown_matches_a_hand_loop():
    # retire now at 60, $50,000 a year, $1,000,000 in cash, Medicare for two from 65, nothing else
    inputs = bare(cash=Bucket(100_000_000, CASH))
    hh = inputs.household
    prep = flat(hh)
    out = sim.simulate(inputs, inputs.levers, [60], prep)
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    cash, path = 1_000_000.0, [1_000_000.0]
    for t in range(prep.n_years):
        age = 60 + t
        cash -= 50_000 + (2 * part_b if age >= 65 else 0)
        path.append(max(cash, 0.0))
    assert np.allclose(out.investable[:, 0, 0], path, atol=0.01)
    assert out.success[:, 0].tolist() == [False] * 4     # $1.0M does not last 35 years at $50k+


def test_flat_market_working_years_accumulate_contributions_and_surplus():
    # works to 70 (plan year 2026, age 60): 10 years of 401(k) 10% of $100k + 50% match on 6%, $12k surplus, no 529s
    inputs = bare(salary_cents=10_000_000, k401_pct_bp=1_000, match_rate_bp=5_000, match_cap_bp=600, surplus_cents=1_200_000,
                  cash=Bucket(1_000_000, CASH), taxable=Bucket(2_000_000, CASH))
    late = Levers(jr_claim_age=70, spouse_claim_age=70)    # nobody claims Social Security before the last working year
    out = sim.simulate(inputs, late, [70], flat(inputs.household))
    assert out.investable[10, 0, 0] == pytest.approx(10_000 + 20_000 + 10 * (10_000 + 3_000 + 12_000))


def test_benefits_claimed_while_still_working_add_to_savings():
    inputs = bare(salary_cents=10_000_000, k401_pct_bp=1_000, surplus_cents=1_200_000, cash=Bucket(1_000_000, CASH))
    prep = flat(inputs.household)
    late = sim.simulate(inputs, Levers(jr_claim_age=70, spouse_claim_age=70), [70], prep)
    early = sim.simulate(inputs, Levers(jr_claim_age=62, spouse_claim_age=62), [70], prep)
    assert early.investable[10, 0, 0] > late.investable[10, 0, 0] + 100_000


def test_negative_surplus_draws_cash_then_taxable():
    inputs = bare(surplus_cents=-1_000_000, cash=Bucket(1_500_000, CASH), taxable=Bucket(10_000_000, CASH))
    out = sim.simulate(inputs, inputs.levers, [70], flat(inputs.household))
    assert out.investable[1, 0, 0] == pytest.approx(105_000)     # cash 5,000 + taxable 100,000
    assert out.investable[2, 0, 0] == pytest.approx(95_000)      # cash 0 + taxable 95,000
    assert not out.success[0, 0]                                 # $115,000 cannot carry a $10,000 yearly shortfall plus 25 years of retirement


def test_buffer_is_spent_last_not_never():
    # retired at 60 with $60,000 cash (buffer is one year = $50,000) and $30,000 taxable
    inputs = bare(cash=Bucket(6_000_000, CASH), taxable=Bucket(3_000_000, CASH))
    out = sim.simulate(inputs, inputs.levers, [60], flat(inputs.household))
    # year 1: $10,000 above the buffer, then all $30,000 taxable, then $10,000 from the buffer
    assert out.investable[1, 0, 0] == pytest.approx(40_000)
    # year 2: only the buffer is left; it is spent and the household still comes up short
    assert out.investable[2, 0, 0] == pytest.approx(0)
    assert not out.success[0, 0]


def test_paid_off_mortgage_and_grown_child_add_nothing():
    base = bare(cash=Bucket(100_000_000, CASH))
    paid = replace(base, household=replace(base.household, mortgage_payment_cents=3_600_000, mortgage_payoff_year=2020))
    grown = replace(base, household=replace(base.household, children=(
        Child("Grown", 1990, "private", Bucket(0, CASH), 0),)))
    prep = flat(base.household)
    ref = sim.simulate(base, base.levers, [60, 65], prep)
    for other in (paid, grown):
        out = sim.simulate(other, other.levers, [60, 65], prep)
        assert np.array_equal(out.investable, ref.investable) and np.array_equal(out.success, ref.success)


def test_529_surplus_stays_in_the_529():
    base = bare(cash=Bucket(100_000_000, CASH))
    rich_529 = replace(base, household=replace(base.household, children=(
        Child("Teen", 2010, "private", Bucket(50_000_000, CASH), 0),)))   # 16 now; $500k covers four years of private
    prep = flat(base.household)
    ref = sim.simulate(base, base.levers, [60], prep)
    out = sim.simulate(rich_529, rich_529.levers, [60], prep)
    assert np.array_equal(out.investable, ref.investable)   # the 529 paid for everything and its leftover is not investable


def test_college_shortfall_comes_from_investable_money_in_order():
    # child turns 18 in 2027: in-state cost 30,990 * 1.01 a year for four years, 529 holds $20,000 and gets nothing more
    inputs = bare(cash=Bucket(100_000_000, CASH), children=(Child("Kid", 2009, "in_state_public", Bucket(2_000_000, CASH), 0),))
    out = sim.simulate(inputs, inputs.levers, [70], flat(inputs.household))   # still working: cash is untouched otherwise
    cost = [sim.college_cost("in_state_public", y, 2026) for y in (2027, 2028, 2029, 2030)]
    expected_cash = 1_000_000 - (sum(cost) - 20_000)
    assert out.investable[1, 0, 0] == pytest.approx(1_000_000)                                   # 2026: the child is 17
    assert out.investable[2, 0, 0] == pytest.approx(1_000_000 - (cost[0] - 20_000), abs=1.0)    # 2027: the 529 pays $20,000 first
    assert out.investable[5, 0, 0] == pytest.approx(expected_cash, abs=1.0)                      # after the four college years


def test_mortgage_and_health_premium_follow_the_rules():
    inputs = bare(cash=Bucket(300_000_000, CASH), mortgage_payment_cents=2_400_000, mortgage_payoff_year=2028,
                  health_premium_cents=1_200_000)
    out = sim.simulate(inputs, inputs.levers, [60], flat(inputs.household))
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    # 2026 and 2027: spending + mortgage + full premium; 2028-2030: no mortgage, full premium; 2031 (both 65): Medicare x2
    assert out.investable[1, 0, 0] == pytest.approx(3_000_000 - 50_000 - 24_000 - 12_000)
    assert out.investable[3, 0, 0] == pytest.approx(3_000_000 - 3 * (50_000 + 12_000) - 2 * 24_000)
    assert out.investable[6, 0, 0] == pytest.approx(3_000_000 - 5 * (50_000 + 12_000) - 2 * 24_000 - (50_000 + 2 * part_b))


def test_half_premium_once_the_older_spouse_is_on_medicare():
    inputs = bare(spouse=Person(1970, "female"), cash=Bucket(300_000_000, CASH), health_premium_cents=1_200_000)
    out = sim.simulate(inputs, inputs.levers, [60], flat(inputs.household))
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    # 2031: JR 65 (Medicare), spouse 61 (half the premium)
    year6 = out.investable[6, 0, 0] - out.investable[5, 0, 0]
    assert -year6 == pytest.approx(50_000 + 6_000 + part_b)


def test_rmds_start_at_75_and_the_excess_moves_to_taxable():
    inputs = bare(jr=Person(1951, "male"), spouse=Person(1951, "female"), spending_basis_cents=1_000_000,
                  traditional=Bucket(100_000_000, CASH), cash=Bucket(5_000_000, CASH))
    out = sim.simulate(inputs, inputs.levers, [75], flat(inputs.household))
    # age 75 in 2026: RMD = 1,000,000 / 24.6 = 40,650.41 taken from traditional; spending is only $10,000
    trad_after = 1_000_000 - 1_000_000 / 24.6
    assert out.investable[1, 0, 0] < 1_050_000                    # taxes on the RMD left the household
    assert out.investable[1, 0, 0] > trad_after + 50_000          # the excess landed in taxable, not vanished


@pytest.mark.parametrize("taxable_cents", [0, 50_000_000])
def test_rmd_counts_toward_the_years_need(taxable_cents):
    inputs = bare(jr=Person(1951, "male"), spouse=Person(1951, "female"), spending_basis_cents=1_000_000,
                  traditional=Bucket(100_000_000, CASH), cash=Bucket(1_000_000, CASH), taxable=Bucket(taxable_cents, CASH))
    out = sim.simulate(inputs, inputs.levers, [75], flat(inputs.household))
    hh = inputs.household
    rmd = 1_000_000 / 24.6
    tax = float(np.ravel(household_tax(np.array([[rmd]]), np.zeros((1, 1)), 0.0, hh.filing_status, hh.state, 2, 2026))[0])
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12     # both spouses are on Medicare at 75
    drop = out.investable[0, 0, 0] - out.investable[1, 0, 0]
    assert drop == pytest.approx(10_000 + 2 * part_b + tax, abs=5)


def test_social_security_reduces_the_need():
    with_ss = bare(jr=Person(1964, "male", tuple((y, 7_000_000) for y in range(1990, 2026))), cash=Bucket(100_000_000, CASH))
    without = bare(jr=Person(1964, "male"), cash=Bucket(100_000_000, CASH))
    prep = flat(with_ss.household)
    a = sim.simulate(with_ss, Levers(jr_claim_age=62), [62], prep)
    b = sim.simulate(without, Levers(jr_claim_age=62), [62], prep)
    assert np.all(a.investable[1:] >= b.investable[1:]) and a.investable[2, 0, 0] > b.investable[2, 0, 0]


def test_full_household_runs_at_scale_and_reports_sane_success_rates():
    inputs = synthetic_household()
    prep = sim.prepare(inputs.household, n_hist=400)
    ages = list(range(44, 71))
    out = sim.simulate(inputs, inputs.levers, ages, prep)
    assert out.investable.shape == (prep.n_years + 1, 400, 27) and out.success.shape == (400, 27)
    rates = out.success.mean(axis=0)
    assert rates[-1] >= rates[0]                 # working longer never hurts on average
    assert np.all(out.investable >= 0)


def test_retirement_income_above_the_need_is_saved_after_tax_on_one_return():
    # retired at 62 on $30,000 a year with consulting of $120,000 until 70: what the year does not need is saved, after
    # self-employment tax and the income tax on the household's one return (D11). From 65 the return has the extra
    # standard deduction for two people over 65. A year's tax is paid at the estimate carried from the year before
    # (one pass, TAX_GROSS_UP_PASSES); the first retired year runs two passes from zero.
    inputs = bare(jr=Person(1964, "male"), spouse=Person(1964, "female"), spending_basis_cents=3_000_000, cash=Bucket(1_000_000, CASH))
    levers = Levers(consulting_cents=12_000_000, consulting_until_age=70)
    out = sim.simulate(inputs, levers, [62], flat(inputs.household))
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    se, se_half = se_tax(120_000.0, 0.0, 2026)
    balance, carried = 10_000.0, None
    for k in range(8):
        n_aged = 2 if 62 + k >= 65 else 0
        tax = _tax(120_000.0 - se_half, 0.0, n_aged, 2026 + k)
        paid = tax if carried is None else carried
        balance += 120_000.0 - se - paid - 30_000.0 - (2 * part_b if n_aged else 0.0)
        carried = tax
        assert out.investable[k + 1, 0, 0] == pytest.approx(balance, abs=2.0), k


def test_lever_income_and_an_rmd_are_taxed_together():
    # 75 in 2026 with a $1,000,000 IRA (RMD $40,650.41) and $60,000 of consulting: the tax is on both at once, so the
    # consulting is taxed at the bracket the RMD leaves it in, not on its own from zero (D11).
    inputs = bare(jr=Person(1951, "male"), spouse=Person(1951, "female"), spending_basis_cents=1_000_000,
                  traditional=Bucket(100_000_000, CASH), cash=Bucket(1_000_000, CASH))
    levers = Levers(consulting_cents=6_000_000, consulting_until_age=90)
    out = sim.simulate(inputs, levers, [75], flat(inputs.household))
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    se, se_half = se_tax(60_000.0, 0.0, 2026)
    rmd = 1_000_000 / 24.6
    together = _tax(rmd + 60_000.0 - se_half, 0.0, 2, 2026)
    apart = _tax(rmd, 0.0, 2, 2026) + _tax(60_000.0 - se_half, 0.0, 2, 2026)
    assert together > apart + 1_000                                   # the old way under-taxed it
    drop = out.investable[0, 0, 0] - out.investable[1, 0, 0]
    assert drop == pytest.approx(10_000 + 2 * part_b - (60_000.0 - se) + together, abs=2.0)


STOCK = Mix(1.0, 0.0, 0.0)


def steady(hh, stock=0.10, n_hist=4, seed=1):
    """Like flat(), but stocks return `stock` every year; bonds and cash return zero."""
    prep = flat(hh, n_hist=n_hist, seed=seed)
    zeros = prep.hist.bond
    return replace(prep, hist=Histories(stock=np.full_like(zeros, stock), bond=zeros, cash=zeros, source_index=prep.hist.source_index))


def _tax(ordinary, gains, n_aged, year=2026):
    return float(np.ravel(household_tax(ordinary, gains, 0.0, "mfj", "CA", n_aged, year))[0])


def test_retirement_order_and_half_gain_match_a_hand_loop():
    # retired at 60 on $120,000 a year: taxable, then traditional, then HSA, then Roth, each grossed up for tax.
    # Roth earns 10% a year and everything else nothing, so drawing Roth before HSA would leave less behind.
    inputs = bare(spending_basis_cents=12_000_000, taxable=Bucket(30_000_000, CASH), traditional=Bucket(30_000_000, CASH),
                  hsa=Bucket(2_000_000, CASH), roth=Bucket(10_000_000, STOCK))
    prep = steady(inputs.household)
    out = sim.simulate(inputs, inputs.levers, [60], prep)
    part_b = rules.table("medicare", 2026)["part_b_monthly"] * 12
    tx, td, hs, ro, tax = 300_000.0, 300_000.0, 20_000.0, 100_000.0, 0.0
    path, hsa_empty_year, roth_first_year = [], None, None
    for t in range(8):
        age = 60 + t
        n_aged = 2 if age >= 65 else 0
        gross = 120_000 + (2 * part_b if age >= 65 else 0)
        for _ in range(2 if t == 0 else 1):        # two passes from zero in the first year, then one seeded with last year's tax
            need = gross + tax
            w_tax = min(tx, need); need -= w_tax
            w_trad = min(td, need); need -= w_trad
            w_hsa = min(hs, need); need -= w_hsa
            w_roth = min(ro, need); need -= w_roth
            tax = _tax(w_trad, 0.5 * w_tax, n_aged, 2026 + t)
        tx -= w_tax; td -= w_trad; hs -= w_hsa; ro -= w_roth
        if hs == 0 and hsa_empty_year is None:
            hsa_empty_year = t
        if w_roth > 0 and roth_first_year is None:
            roth_first_year = t
        ro *= 1.10
        path.append(tx + td + hs + ro)
    assert hsa_empty_year is not None and roth_first_year is not None and hsa_empty_year <= roth_first_year
    assert path[5] > 0                               # years 5 on live on the Roth alone
    for k in range(1, 9):
        assert out.investable[k, 0, 0] == pytest.approx(path[k - 1], abs=1.0), k


def test_taxable_withdrawals_count_half_as_gain():
    inputs = bare(spending_basis_cents=12_000_000, taxable=Bucket(200_000_000, CASH))
    out = sim.simulate(inputs, inputs.levers, [60], flat(inputs.household))
    drop = out.investable[0, 0, 0] - out.investable[1, 0, 0]
    assert drop == pytest.approx(120_000 + _tax(0.0, 60_000.0, 0), abs=1.0)


def test_negative_surplus_draws_cash_before_a_growing_taxable_account():
    # taxable earns 10% a year, so drawing it before cash would show
    inputs = bare(surplus_cents=-1_000_000, cash=Bucket(1_500_000, CASH), taxable=Bucket(10_000_000, STOCK))
    out = sim.simulate(inputs, inputs.levers, [70], steady(inputs.household))
    assert out.investable[1, 0, 0] == pytest.approx(5_000 + 110_000)                 # taxable-first would give 15,000 + 99,000
    assert out.investable[2, 0, 0] == pytest.approx(0 + (110_000 - 5_000) * 1.1)


def test_buffer_is_left_alone_while_other_buckets_have_money():
    # retired at 60 on $50,000: $10,000 from cash above the one-year buffer, then $40,000 from a taxable account earning 10%
    assert _tax(0.0, 20_000.0, 0) == 0.0                                            # $20,000 of gain is under the deduction
    inputs = bare(cash=Bucket(6_000_000, CASH), taxable=Bucket(10_000_000, STOCK))
    out = sim.simulate(inputs, inputs.levers, [60], steady(inputs.household))
    assert out.investable[1, 0, 0] == pytest.approx(50_000 + 60_000 * 1.1)          # no buffer would give 10,000 + 100,000 * 1.1


def test_working_years_save_the_mortgage_payment_once_it_is_paid_off():
    # still working, no surplus: the $24,000 payment stops in 2028 and from then on is saved
    late = Levers(jr_claim_age=70, spouse_claim_age=70)
    inputs = bare(cash=Bucket(1_000_000, CASH), mortgage_payment_cents=2_400_000, mortgage_payoff_year=2028)
    out = sim.simulate(inputs, late, [70], flat(inputs.household))
    assert out.investable[2, 0, 0] == pytest.approx(10_000)                    # 2026 and 2027: the payment is in the surplus
    assert out.investable[3, 0, 0] == pytest.approx(10_000 + 24_000)           # 2028: paid off
    assert out.investable[5, 0, 0] == pytest.approx(10_000 + 3 * 24_000)
    # a mortgage paid off before the plan year is already out of the observed surplus: nothing extra
    past = bare(cash=Bucket(1_000_000, CASH), mortgage_payment_cents=2_400_000, mortgage_payoff_year=2020)
    assert sim.simulate(past, late, [70], flat(past.household)).investable[5, 0, 0] == pytest.approx(10_000)


def inflating(hh, rate, n_hist=4):
    """flat(), with prices rising `rate` a year in every history."""
    prep = flat(hh, n_hist=n_hist)
    return replace(prep, hist=replace(prep.hist, cpi=np.full((n_hist, prep.n_years), rate)))


def test_fixed_dollars_by_year_divides_by_the_prices_so_far():
    cpi = np.array([[0.10, 0.10, -0.05], [0.0, 0.0, 0.0]])
    got = sim.fixed_dollars_by_year(1_000.0, cpi, 3)
    assert got.shape == (3, 2) and got.dtype == np.float32
    assert got[:, 0].tolist() == pytest.approx([1_000.0, 1_000 / 1.1, 1_000 / 1.21])
    assert got[:, 1].tolist() == pytest.approx([1_000.0] * 3)
    assert sim.fixed_dollars_by_year(1_000.0, None, 3) is None and sim.fixed_dollars_by_year(0.0, cpi, 3) is None
    # Review Focus 5: a deflation year makes the fixed payment cost more in today's dollars
    assert sim.fixed_dollars_by_year(1_000.0, np.array([[-0.05, 0.0]]), 2)[1, 0] == pytest.approx(1_000 / 0.95)


def test_the_mortgage_payment_shrinks_with_inflation_in_retirement():
    # retired at 60 on $50,000, a $24,000 payment until 2030, prices up 3% a year: the payment costs 24,000 / 1.03^t (D10)
    inputs = bare(cash=Bucket(300_000_000, CASH), mortgage_payment_cents=2_400_000, mortgage_payoff_year=2030)
    out = sim.simulate(inputs, inputs.levers, [60], inflating(inputs.household, 0.03))
    for t in range(5):                                     # both turn 65 (Medicare) in 2031, year 5
        drop = out.investable[t, 0, 0] - out.investable[t + 1, 0, 0]
        assert drop == pytest.approx(50_000 + (24_000 / 1.03 ** t if t < 4 else 0.0), abs=0.5), t


def test_while_working_the_shrinking_payment_is_saved_and_all_of_it_once_paid_off():
    # no surplus, a $24,000 payment until 2028, prices up 2% a year: 2027 saves what inflation took off the payment;
    # from 2028 the whole of today's payment is saved, because today's surplus already paid it (D10)
    late = Levers(jr_claim_age=70, spouse_claim_age=70)
    inputs = bare(cash=Bucket(1_000_000, CASH), mortgage_payment_cents=2_400_000, mortgage_payoff_year=2028)
    out = sim.simulate(inputs, late, [70], inflating(inputs.household, 0.02))
    assert out.investable[1, 0, 0] == pytest.approx(10_000)
    assert out.investable[2, 0, 0] == pytest.approx(10_000 + 24_000 - 24_000 / 1.02, abs=0.05)
    assert out.investable[3, 0, 0] == pytest.approx(10_000 + 24_000 - 24_000 / 1.02 + 24_000, abs=0.05)


def test_sampled_histories_carry_their_own_inflation():
    hh = synthetic_household().household
    prep = sim.prepare(hh, n_hist=50)
    md = datafiles.market()
    assert prep.hist.cpi.shape == prep.hist.stock.shape
    assert np.array_equal(prep.hist.cpi, md.cpi[prep.hist.source_index])


def test_401k_deferral_is_capped_at_the_yearly_limit():
    # 10% of $400,000 would be $40,000; the 2026 elective-deferral limit is $24,500
    late = Levers(jr_claim_age=70, spouse_claim_age=70)
    inputs = bare(salary_cents=40_000_000, k401_pct_bp=1_000)
    out = sim.simulate(inputs, late, [70], flat(inputs.household))
    assert out.investable[10, 0, 0] == pytest.approx(10 * 24_500)
    under = bare(salary_cents=10_000_000, k401_pct_bp=1_000)                 # under the limit: unchanged
    assert sim.simulate(under, late, [70], flat(under.household)).investable[10, 0, 0] == pytest.approx(10 * 10_000)


@pytest.mark.parametrize("levers", [Levers(), Levers(jr_claim_age=62, spouse_claim_age=62, spending_pct=80, consulting_cents=4_000_000)])
def test_each_age_column_is_the_same_bits_run_alone_or_together(levers):
    # Columns still working share one row until they retire or someone claims; forking it must not change a bit.
    inputs = synthetic_household(spending_basis_cents=11_000_000)
    prep = sim.prepare(inputs.household, n_hist=200)
    ages = [70, 44, 52, 61, 62, 63, 66, 52]                 # unsorted, with a repeat
    together = sim.simulate(inputs, levers, ages, prep)
    for j, age in enumerate(ages):
        alone = sim.simulate(inputs, levers, [age], prep)
        assert np.array_equal(together.success[:, j], alone.success[:, 0]), age
        assert np.array_equal(together.investable[:, :, j], alone.investable[:, :, 0]), age


def test_mortgage_paid_off_in_the_plan_year_is_saved_from_the_first_year():
    late = Levers(jr_claim_age=70, spouse_claim_age=70)
    inputs = bare(cash=Bucket(1_000_000, CASH), mortgage_payment_cents=2_400_000, mortgage_payoff_year=2026)
    out = sim.simulate(inputs, late, [70], flat(inputs.household))
    assert out.investable[1, 0, 0] == pytest.approx(10_000 + 24_000)          # 2026 itself is freed
    assert out.investable[3, 0, 0] == pytest.approx(10_000 + 3 * 24_000)


def test_a_one_off_cost_comes_out_in_its_year_while_working_and_in_retirement():
    """Phase 11c, decision D: paid as a college shortfall is, cash first; in today's dollars, not grown."""
    from steward.engine.inputs import OneOffCost
    late = Levers(jr_claim_age=70, spouse_claim_age=70)
    working = bare(cash=Bucket(1_000_000, CASH), one_off_costs=(OneOffCost(2028, 500_000),))
    out = sim.simulate(working, late, [70], flat(working.household))
    assert out.investable[2, 0, 0] == pytest.approx(10_000)                     # 2027: nothing yet
    assert out.investable[3, 0, 0] == pytest.approx(10_000 - 5_000)             # 2028: the roof, from cash
    assert out.investable[5, 0, 0] == pytest.approx(5_000)                      # and never again
    retired = bare(cash=Bucket(300_000_000, CASH), one_off_costs=(OneOffCost(2027, 2_000_000),))
    out = sim.simulate(retired, retired.levers, [60], flat(retired.household))
    assert out.investable[1, 0, 0] == pytest.approx(3_000_000 - 50_000)
    assert out.investable[2, 0, 0] == pytest.approx(3_000_000 - 2 * 50_000 - 20_000)
    two = bare(cash=Bucket(1_000_000, CASH), one_off_costs=(OneOffCost(2028, 500_000), OneOffCost(2028, 300_000)))
    assert sim.simulate(two, late, [70], flat(two.household)).investable[3, 0, 0] == pytest.approx(2_000)
    past = bare(cash=Bucket(1_000_000, CASH), one_off_costs=(OneOffCost(2020, 500_000),))    # before the plan year: nothing
    assert sim.simulate(past, late, [70], flat(past.household)).investable[3, 0, 0] == pytest.approx(10_000)
    grown = bare(cash=Bucket(1_000_000, CASH), one_off_costs=(OneOffCost(2030, 500_000),))
    out = sim.simulate(grown, late, [70], inflating(grown.household, 0.05))
    assert out.investable[4, 0, 0] - out.investable[5, 0, 0] == pytest.approx(5_000)   # not grown with inflation or college costs


def test_college_cost_scales_by_the_share_and_can_leave_out_living_costs():
    lv = datafiles.college_levels()["in_state_public"]
    full = (lv.tuition_fees_cents + lv.living_cents) / 100
    assert sim.college_cost("in_state_public", 2026, 2026) == full
    assert sim.college_cost("in_state_public", 2026, 2026, 50) == full / 2
    assert sim.college_cost("in_state_public", 2026, 2026, 100, False) == lv.tuition_fees_cents / 100
    assert sim.college_cost("in_state_public", 2026, 2026, 0) == 0.0
    private = datafiles.college_levels()["private"]
    assert sim.college_cost("private", 2033, 2026, 50, False) == pytest.approx(private.tuition_fees_cents / 100 * 0.5 * 1.01 ** 7)
    assert (sim.college_years("two_year"), sim.college_years("in_state_public")) == (2, 4)


def test_two_year_college_covers_ages_18_and_19_only():
    inputs = bare(cash=Bucket(100_000_000, CASH), children=(Child("Kid", 2008, "two_year", Bucket(0, CASH), 0),))
    out = sim.simulate(inputs, inputs.levers, [70], flat(inputs.household))   # still working: cash moves only for college
    c = [sim.college_cost("two_year", y, 2026) for y in (2026, 2027)]
    assert out.investable[1, 0, 0] == pytest.approx(1_000_000 - c[0], abs=1.0)
    assert out.investable[2, 0, 0] == pytest.approx(1_000_000 - sum(c), abs=1.0)
    assert out.investable[3, 0, 0] == pytest.approx(out.investable[2, 0, 0], abs=0.01)   # nothing at 20


def test_a_level_lever_changes_the_years_in_one_batch_and_each_row_matches_its_solo_run():
    inputs = bare(cash=Bucket(15_000_000, CASH), children=(Child("Kid", 2008, "two_year", Bucket(0, CASH), 0),))
    prep = flat(inputs.household)
    trials = [Levers(college_levels=("two_year",)), Levers(college_levels=("in_state_public",))]
    batched = sim.trial_success_rates(inputs, trials, [66, 68, 70], prep, stop_below=0.0)
    for k, lv in enumerate(trials):
        assert np.array_equal(batched[k], sim.simulate(inputs, lv, [66, 68, 70], prep).success.mean(axis=0))
    two = sim.simulate(inputs, trials[0], [70], prep).investable[:, 0, 0]
    four = sim.simulate(inputs, trials[1], [70], prep).investable[:, 0, 0]
    assert two[3] == pytest.approx(two[2]) and four[3] < four[2] and four[5] == pytest.approx(four[4])


def test_the_529_pays_toward_the_share_and_a_zero_share_draws_nothing():
    kid = Child("Kid", 2008, "in_state_public", Bucket(1_000_000, CASH), 0, share_pct=50)
    inputs = bare(cash=Bucket(100_000_000, CASH), children=(kid,))
    prep = flat(inputs.household)
    out = sim.simulate(inputs, inputs.levers, [70], prep)
    half = sim.college_cost("in_state_public", 2026, 2026, 50)
    assert out.investable[1, 0, 0] == pytest.approx(1_000_000 - (half - 10_000), abs=1.0)   # the 529's $10,000 first
    zero = replace(inputs, household=replace(inputs.household, children=(replace(kid, share_pct=0),)))
    none = bare(cash=Bucket(100_000_000, CASH))
    assert np.array_equal(sim.simulate(zero, zero.levers, [70], prep).investable,
                          sim.simulate(none, none.levers, [70], prep).investable)
