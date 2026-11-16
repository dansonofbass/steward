import numpy as np
import pytest

from steward.engine import social_security as ss
from steward.engine.inputs import Levers, Person
from steward.engine.synthetic import synthetic_household

# SSA, "Benefit Calculation Examples for Workers Retiring in 2026", case A: born 1964, retires at 62 in 2026.
# https://www.ssa.gov/oact/ProgData/retirebenefit1.html and retirebenefit2.html (fetched 2026-10-13)
CASE_A_EARNINGS = dict(zip(range(1986, 2026), [
    16196, 17283, 18191, 18971, 19909, 20715, 21850, 22107, 22770, 23755, 24994, 26533, 28007, 29657, 31392,
    32238, 32660, 33558, 35224, 36621, 38419, 40281, 41330, 40826, 41914, 43354, 44839, 45544, 47298, 49085,
    49783, 51651, 53677, 55848, 57590, 62889, 66421, 69560, 73133, 75868,
]))


def test_case_a_aime_pia_and_age_62_benefit_match_ssa():
    record = {y: e * 100 for y, e in CASE_A_EARNINGS.items()}
    assert ss.aime_cents(record, 2024) == 5_825_00
    assert ss.pia_cents(5_825_00, 2026) == 2_609_80
    assert ss.monthly_benefit_cents(2_609_80, 62, 1964) == 1_826_00
    person = Person(1964, "male", tuple(sorted(record.items())))
    assert ss.person_pia_cents(person, start_year=2026, yearly_cents=0, stop_age=0) == 2_609_80


def test_case_b_pia_formula_before_colas_matches_ssa():
    # case B: AIME $11,463, first eligible 2021 (bend points $996 / $6,002): .9(996)+.32(5006)+.15(5461) = $3,317.47
    assert ss.pia_cents(11_463_00, 2021) == 3_317_40


def test_full_retirement_age_by_birth_year():
    assert ss.fra_months(1960) == ss.fra_months(1982) == 67 * 12
    assert ss.fra_months(1959) == 66 * 12 + 10
    assert ss.fra_months(1957) == 66 * 12 + 6
    assert ss.fra_months(1954) == ss.fra_months(1943) == 66 * 12
    assert ss.fra_months(1937) == 65 * 12


def test_claiming_factors_follow_ssa_rules():
    # 5/9 of 1% a month for the first 36 months, 5/12 of 1% after; 8% a year delayed credits to 70
    assert ss.claim_factor(62, 1964) == pytest.approx(0.70)
    assert ss.claim_factor(63, 1964) == pytest.approx(0.75)
    assert ss.claim_factor(64, 1964) == pytest.approx(0.80)
    assert ss.claim_factor(67, 1964) == pytest.approx(1.00)
    assert ss.claim_factor(68, 1964) == pytest.approx(1.08)
    assert ss.claim_factor(70, 1964) == pytest.approx(1.24)
    assert ss.claim_factor(70, 1959) == pytest.approx(1 + 38 * 0.08 / 12)   # FRA 66y10m: 38 months of credits


def test_spousal_factor_and_benefit_match_ssa_example():
    # SSA: PIA $1,600, spouse claims 36 months early -> 50% = $800, reduced 25% -> $600
    assert ss.spousal_factor(64, 1960) == pytest.approx(0.75)
    assert ss.spousal_benefit_cents(1_600_00, 64, 1960) == 600_00
    # 60 months early: 25% + 24 * 5/12% = 35% reduction -> 32.5% of PIA
    assert ss.spousal_factor(62, 1960) == pytest.approx(0.65)
    assert ss.spousal_benefit_cents(1_600_00, 62, 1960) == 520_00
    assert ss.spousal_factor(70, 1960) == 1.0           # no delayed credits on spousal benefits


def test_projected_earnings_are_capped_and_stop_at_the_retirement_age():
    person = Person(1982, "male")
    pia_60 = ss.person_pia_cents(person, start_year=2026, yearly_cents=20_000_000, stop_age=60)
    pia_65 = ss.person_pia_cents(person, start_year=2026, yearly_cents=20_000_000, stop_age=65)
    capped = ss.person_pia_cents(person, start_year=2026, yearly_cents=18_450_000, stop_age=60)
    assert pia_60 == capped                      # $200,000 counts as the $184,500 taxable maximum
    assert pia_65 > pia_60                       # more years at the cap replace zero years
    record = {y: 18_450_000 for y in range(2026, 2026 + 34)}
    assert ss.aime_cents(record, 2024) == 184_500 * 34 * 100 // 420 // 100 * 100


def test_empty_record_gives_zero():
    assert ss.person_pia_cents(Person(1984, "female"), start_year=2026, yearly_cents=0, stop_age=0) == 0


def test_jr_pia_never_falls_as_he_works_longer():
    hh = synthetic_household().household
    pia = ss.jr_pia_by_age(hh, range(44, 71))
    assert pia.dtype == np.int64 and pia.shape == (27,)
    assert np.all(np.diff(pia) >= 0) and pia[0] > 0


def test_spouse_without_record_gets_spousal_only():
    inputs = synthetic_household(spouse=Person(1984, "female"))
    hh = inputs.household
    assert ss.spouse_pia_cents(hh, inputs.levers) == 0
    sched = ss.benefit_schedule(hh, inputs.levers, [60, 65])
    assert sched.sp_own == 0.0 and sched.jr_spousal == 0.0
    assert np.allclose(sched.sp_spousal, np.floor(sched.jr_own * 0.5))   # claimed at FRA: half of JR's PIA, whole dollars
    alive = np.ones((3, 1), bool)
    # 2049: JR is 67 and has claimed; the spouse is 65 and has not (67). 2049 is after the 2034 cut.
    only_jr = ss.household_benefit(sched, inputs.levers, 2049, 67, 65, alive, alive)
    assert np.allclose(only_jr, sched.jr_own * 0.83)
    # 2051: both have claimed; her own benefit is zero, so she takes the spousal amount
    both = ss.household_benefit(sched, inputs.levers, 2051, 69, 67, alive, alive)
    assert np.allclose(both, (sched.jr_own + sched.sp_spousal) * 0.83)



def test_spousal_reduction_counts_from_when_the_spousal_benefit_can_start():
    # JR (1966) claims at 67; the spouse (1968, no record) files at 62 but the spousal benefit cannot start until JR files,
    # when she is 65, so it is reduced for 65, not 62
    inputs = synthetic_household(jr=Person(1966, "male", ((2000, 6_000_000), (2001, 6_000_000))), spouse=Person(1968, "female"))
    hh = inputs.household
    pia = ss.jr_pia_by_age(hh, [60])[0]
    sched = ss.benefit_schedule(hh, Levers(jr_claim_age=67, spouse_claim_age=62), [60])
    assert sched.sp_spousal[0] == np.floor(pia / 100 * 0.5 * ss.spousal_factor(65, 1968))
    # filing after JR has claimed: her own claim age stands
    late = ss.benefit_schedule(hh, Levers(jr_claim_age=67, spouse_claim_age=68), [60])
    assert late.sp_spousal[0] == ss.spousal_benefit_cents(int(pia), 68, 1968) / 100
    # the mirror: the spouse (1966) claims at 67, JR (1968) files at 62 and can take the spousal top-up only from 65
    mirror = synthetic_household(jr=Person(1968, "male"), spouse=Person(1966, "female", ((2000, 6_000_000), (2001, 6_000_000)))).household
    sp_pia = ss.spouse_pia_cents(mirror, Levers())
    m = ss.benefit_schedule(mirror, Levers(jr_claim_age=62, spouse_claim_age=67), [60])
    assert m.jr_spousal == np.floor(sp_pia / 100 * 0.5 * ss.spousal_factor(65, 1968))


def test_spouse_earnings_lever_builds_her_own_record():
    inputs = synthetic_household(spouse=Person(1984, "female"))
    none = ss.spouse_pia_cents(inputs.household, inputs.levers)
    some = ss.spouse_pia_cents(inputs.household, Levers(spouse_earnings_cents=6_000_000, spouse_start_year=2027, spouse_stop_age=65))
    assert none == 0 and some > 0


def test_trust_fund_factor_from_the_2026_trustees_report():
    assert ss.trust_fund_factor(2033, False) == 1.0
    assert ss.trust_fund_factor(2034, False) == 0.83
    assert ss.trust_fund_factor(2060, False) == 0.83
    assert ss.trust_fund_factor(2060, True) == 1.0


def test_household_benefit_handles_claiming_survivors_and_the_cut():
    hh = synthetic_household().household
    levers = Levers(jr_claim_age=67, spouse_claim_age=67)
    sched = ss.BenefitSchedule(jr_own=np.array([3000.0, 3200.0]), sp_own=900.0,
                               sp_spousal=np.array([1500.0, 1600.0]), jr_spousal=450.0)
    alive = np.array([[True], [True], [False]])      # history 2: JR has died
    sp_alive = np.array([[True], [False], [True]])   # history 1: spouse has died
    # year 2030 (before the cut): JR 48, spouse 46 -> nobody has claimed
    assert np.all(ss.household_benefit(sched, levers, 2030, 48, 46, alive, sp_alive) == 0)
    # JR 67 has claimed, spouse 65 has not: JR's own only, cut applies (2049 >= 2034)
    out = ss.household_benefit(sched, levers, 2049, 67, 65, alive, sp_alive)
    assert np.allclose(out[0], np.array([3000.0, 3200.0]) * 0.83)      # both alive
    assert np.allclose(out[1], np.array([3000.0, 3200.0]) * 0.83)      # spouse dead, JR claimed: his own
    assert np.allclose(out[2], 0.0)                                     # JR dead, spouse not yet claimed
    # both claimed: spouse takes the larger of her own ($900) and spousal ($1,500 / $1,600)
    out = ss.household_benefit(sched, levers, 2051, 69, 67, alive, sp_alive)
    assert np.allclose(out[0], (np.array([3000.0, 3200.0]) + np.array([1500.0, 1600.0])) * 0.83)
    assert np.allclose(out[2], np.array([3000.0, 3200.0]) * 0.83)      # survivor keeps the larger benefit
    # full benefits switch
    full = ss.household_benefit(sched, Levers(full_ss_benefits=True), 2051, 69, 67, alive, sp_alive)
    assert np.allclose(full[0], np.array([4500.0, 4800.0]))
