"""California (spec 3.1, D4, 9): the FTB 2025 booklet's worked example and Tax Table rows, exemption credits and their
phase-out, the 1% tax over $1,000,000, the estimate schedule, and the plan's vector path."""
from datetime import date

import numpy as np
import pytest

from steward.engine.tax import rules
from steward.engine.tax.facts import FederalFigures, Installment, TaxFacts
from steward.engine.tax.state import california as ca
from steward.engine.tax.state import module_for

C = rules.table("california", 2025)


def test_the_ftb_worked_example_chris_and_pat_smith():
    # 2025 California Tax Rate Schedules: taxable income $125,000, joint: 3,974.82 + 8% x 9,916 = 4,768.10 -> $4,768
    assert ca.income_tax(C["brackets"]["mfj"], 125_000, 100_000) == 4_768


@pytest.mark.parametrize("filing, ti, want", [
    # 2025 California Tax Table rows ("At least / But not over / 1 or 3 / 2 or 5")
    ("single", 50_000, 1_535), ("mfj", 50_050, 778),       # row 49,951-50,050: 1,535 / 778
    ("mfj", 75_000, 1_728), ("single", 74_951, 3_414),     # row 74,951-75,050: 3,414 / 1,728
    ("single", 13_200, 153), ("mfj", 13_151, 132),         # row 13,151-13,250: 153 / 132
    ("mfj", 22_200, 222), ("single", 30_100, 568),         # rows 22,151-22,250 and 30,051-30,150
    ("mfj", 93_200, 2_662), ("single", 99_990, 5_736),     # rows 93,151-93,250 and 99,951-100,000
    ("single", 50, 0),                                     # row 1-50
])
def test_2025_california_tax_table_rows(filing, ti, want):
    assert ca.income_tax(C["brackets"][filing], ti, 100_000) == want


def test_exemption_credits_and_the_agi_limitation_worksheet():
    # joint, both 65 or older, one dependent, AGI under $504,411: 2 x 153 + 2 x 153 + 475
    assert ca.exemption_credits(C, "mfj", (70, 66), 1, 200_000) == 1_087
    # single, 40, AGI 262,203: 10,000 over -> 4 steps x $6 = 24 off each credit: 153 - 24 = 129
    assert ca.exemption_credits(C, "single", (40,), 0, 262_203) == 129
    # a dependent's credit shrinks by the same 24: 475 - 24
    assert ca.exemption_credits(C, "single", (40,), 1, 262_203) == 129 + 451
    assert ca.exemption_credits(C, "single", (40,), 0, 900_000) == 0


def test_the_one_percent_tax_over_a_million_comes_after_credits():
    f = TaxFacts(filing="single", ages=(60,), state="CA")
    r = ca.MODULE.tax(f, 2026, FederalFigures(agi=1_205_706, taxable_social_security=0, hsa_deduction=0))
    # taxable 1,200,000: 72,219.84 + 12.3% x 457,047 = 128,436.62 -> 128,437; credits phased out; + 1% x 200,000
    assert r.taxable_income_cents == 120_000_000 and r.tax_cents == (128_437 + 2_000) * 100
    assert any("1% tax on income over $1,000,000 adds $2,000" in line for line in r.explain)


def test_the_estimate_schedule_is_30_40_0_30():
    assert ca.MODULE.estimates_schedule(2026) == (
        Installment(date(2026, 4, 15), 0.30), Installment(date(2026, 6, 15), 0.40),
        Installment(date(2026, 9, 15), 0.0), Installment(date(2027, 1, 15), 0.30))


def test_the_vector_path_matches_the_rate_schedule_and_leaves_its_inputs_alone():
    income = np.array([125_000.0, 5_000.0, 2_011_412.0])
    agi = income.copy()
    got = module_for("CA").vector_tax(income, agi, "mfj", 0, 2026)
    assert got[0] == pytest.approx(3_579.06)                           # tax on 113,588 less 306
    assert got[1] == 0.0
    # 2,000,000 taxable: 144,439.65 + 12.3% x 514,094 + 1% x 1,000,000; credits phased out
    assert got[2] == pytest.approx(144_439.65 + 0.123 * 514_094 + 10_000)
    assert income.tolist() == [125_000.0, 5_000.0, 2_011_412.0] and np.array_equal(agi, income)
    two_65 = module_for("CA").vector_tax(np.array([125_000.0]), np.array([125_000.0]), "mfj", 2, 2026)
    assert two_65[0] == pytest.approx(3_579.06 - 306)


def test_california_2025_pins_the_ftb_booklet():
    c = rules.table("california", 2025)
    assert c["brackets"]["mfj"][4] == [115084, 0.08] and c["brackets"]["mfj"][-1] == [1485906, 0.123]
    assert c["brackets"]["single"][3] == [41452, 0.06] and c["brackets"]["single"][-1] == [742953, 0.123]
    assert c["standard_deduction"] == {"mfj": 11412, "single": 5706}
    assert c["exemption_credit"] == {"personal": 153, "age_65": 153, "dependent": 475}
    assert c["credit_phase_out"] == {"threshold": {"mfj": 504411, "single": 252203}, "step": 2500, "per_step": 6}
    assert c["itemized_limit"] == {"threshold": {"mfj": 504411, "single": 252203}, "agi_rate": 0.06, "itemized_rate": 0.80}
    assert c["estimates"]["shares"] == [0.30, 0.40, 0.0, 0.30]
    assert rules.table("california", 2026).year == 2025         # FTB publishes 2026 figures in late December 2026


def test_california_taxes_hsa_contributions_made_through_payroll():
    # Final review minor 9: payroll HSA contributions are already out of federal wages (box 1); California taxes them
    f = TaxFacts(filing="single", ages=(50,), state="CA", payroll_hsa_cents=430_000)
    r = ca.MODULE.tax(f, 2026, FederalFigures(agi=100_000, taxable_social_security=0, hsa_deduction=1_000))
    assert r.agi_cents == (100_000 + 1_000 + 4_300) * 100
