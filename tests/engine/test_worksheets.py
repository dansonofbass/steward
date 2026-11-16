"""The IRS worksheets annual_tax follows, against published worked examples and table rows (spec 9). Where no IRS
example exists for a worksheet, the test walks the form's lines by hand in comments, from the stated inputs."""
import pytest

from steward.engine.tax import rules
from steward.engine.tax import worksheets as w

B25 = rules.table("federal", 2025)["brackets"]
B26 = rules.table("federal", 2026)["brackets"]


@pytest.mark.parametrize("x, want", [(2_800.5, 2_801), (2_800.49, 2_800), (0.5, 1), (-2_800.5, -2_801), (0, 0)])
def test_whole_rounds_half_up_like_the_forms(x, want):
    assert w.whole(x) == want


@pytest.mark.parametrize("filing, ti, want", [
    # 2025 Form 1040 instructions, Tax Table rows: "At least / But less than / Single / Married filing jointly"
    ("single", 25_300, 2_801), ("mfj", 25_349, 2_562),        # row 25,300-25,350: 2,801 / 2,562
    ("single", 46_550, 5_351), ("mfj", 46_599, 5_112),        # row 46,550-46,600: 5,351 / 5,112
    ("single", 99_950, 16_909), ("mfj", 99_999, 11_823),      # row 99,950-100,000: 16,909 / 11,823
    ("single", 2_975, 299), ("single", 3_000, 303),           # rows 2,975-3,000 and 3,000-3,050
    ("single", 30, 4), ("single", 4, 0),                      # rows 25-50 and 0-5
])
def test_2025_tax_table_rows(filing, ti, want):
    assert w.federal_income_tax(B25[filing], ti) == want


def test_over_100000_uses_the_tax_computation_worksheet():
    # 2026 single, $150,000: 17,966 + 24% of 44,300 = 28,598
    assert w.federal_income_tax(B26["single"], 150_000) == 28_598
    assert w.schedule_tax(B26["mfj"], 1_000_000) == pytest.approx(292_164.5)   # 206,583.50 + 37% of 231,300


def test_publication_915_2025_examples():
    # Example 1: single; pension 18,600 + wages 9,400 + interest 990 = 28,990; benefits 5,980 -> taxable 2,990
    assert w.taxable_social_security(5_980, 28_990, 0, 0, (25_000, 34_000)) == 2_990
    # Example 2 (Casey and Pat Hopkins): joint; 29,750 of income, a 1,000 IRA deduction, benefits 5,600 -> none taxable
    assert w.taxable_social_security(5_600, 29_750, 0, 1_000, (32_000, 44_000)) == 0
    # Terry Jackson's Worksheet 1: single; 25,500 of other income, 11,000 of benefits -> 3,000 taxable
    assert w.taxable_social_security(11_000, 25_500, 0, 0, (25_000, 34_000)) == 3_000


def test_publication_915_worksheet_reaches_the_85_percent_cap():
    # Worksheet 1 by hand: single; benefits 28,000; other income 43,500. Line 2 14,000; line 6 57,500; line 10 32,500;
    # line 12 23,500; line 13 9,000; line 15 4,500; line 16 19,975; line 17 24,475; line 18 23,800 -> 23,800
    assert w.taxable_social_security(28_000, 43_500, 0, 0, (25_000, 34_000)) == 23_800
    # tax-exempt interest counts (line 4): Example 1 with 5,000 of it: line 6 36,980; line 10 11,980; line 12 2,980;
    # line 15 2,990; line 16 2,533; line 17 5,523; line 18 5,083 -> 5,083
    assert w.taxable_social_security(5_980, 28_990, 5_000, 0, (25_000, 34_000)) == 5_083


def test_schedule_se_and_publication_334():
    # Publication 334 (2025): a $1,200 net profit gives actual net earnings of $1,108 ($1,200 x 0.9235)
    tax, half, net = w.schedule_se(1_200, 0, 176_100, 0.9235, 0.124, 0.029, 400)
    assert round(net) == 1_108 and (tax, half) == (170, 85)    # 1,108.20 x 15.3% = 169.55
    # Publication 334 Example 4: a $175 profit is under $400 of net earnings, so no SE tax
    assert w.schedule_se(175, 0, 176_100, 0.9235, 0.124, 0.029, 400)[:2] == (0, 0)
    # Schedule SE (2026 wage base $184,500) by hand: profit 90,000 -> line 4a 83,115; line 10 12.4% x 83,115 =
    # 10,306.26; line 11 2.9% x 83,115 = 2,410.34; line 12 12,717; line 13 6,359 (6,358.50 rounded up)
    assert w.schedule_se(90_000, 0, 184_500, 0.9235, 0.124, 0.029, 400)[:2] == (12_717, 6_359)
    # with $160,000 of W-2 wages only 24,500 of the wage base is left: 12.4% x 24,500 + 2.9% x 83,115 = 5,448.34
    assert w.schedule_se(90_000, 160_000, 184_500, 0.9235, 0.124, 0.029, 400)[:2] == (5_448, 2_724)


def test_form_8959_additional_medicare_tax():
    # single, $230,000 of wages: 0.9% of 30,000 = 270; plus $50,000 of SE earnings, all over what wages left: +450
    assert w.additional_medicare_tax(230_000, 0.0, 200_000, 0.009) == 270
    assert w.additional_medicare_tax(230_000, 50_000.0, 200_000, 0.009) == 720
    # $150,000 of wages leaves $50,000 of threshold for SE earnings of $80,000: 0.9% of 30,000
    assert w.additional_medicare_tax(150_000, 80_000.0, 200_000, 0.009) == 270


QBI_2026 = dict(rate=0.20, threshold=201_750, phase_in=75_000, wage_limit_rate=0.50, minimum_deduction=400, minimum_qbi=1_000)


def test_form_8995_at_or_below_the_threshold():
    # QBI 71,641; taxable income before QBI 34,041; net capital gain 1,000:
    # line 5 20% x 71,641 = 14,328.20; line 14 20% x (34,041 - 1,000) = 6,608.20; line 15 the smaller -> 6,608
    assert w.qbi_deduction(71_641, 0, True, 34_041, 1_000, **QBI_2026) == 6_608
    assert w.qbi_deduction(50_000, 0, True, 150_000, 0, **QBI_2026) == 10_000          # 20% of QBI
    assert w.qbi_deduction(-5_000, 0, False, 150_000, 0, **QBI_2026) == 0               # a loss: no deduction


def test_the_2026_minimum_deduction():
    # $1,500 of QBI and taxable income of $1,800: 20% would be 300; section 199A(i) makes it $400
    assert w.qbi_deduction(1_500, 0, False, 1_800, 0, **QBI_2026) == 400
    assert w.qbi_deduction(900, 0, False, 50_000, 0, **QBI_2026) == 180                 # under $1,000 of QBI: no minimum
    assert w.qbi_deduction(1_500, 0, False, 1_800, 0, **{**QBI_2026, "minimum_deduction": 0, "minimum_qbi": 0}) == 300


def test_form_8995a_phase_in_for_a_specified_service_business():
    # single 2026, taxable income 239,250: 37,500 over the threshold, half of the 75,000 range. A consulting business
    # (SSTB) with QBI 100,000 and no W-2 wages keeps 50%: 20% x 50,000 = 10,000; the wage limit (0) phases in by half:
    # reduction (10,000 - 0) x 50% = 5,000 -> 5,000
    assert w.qbi_deduction(100_000, 0, True, 239_250, 0, **QBI_2026) == 5_000
    # the same income from a non-service business with no wages: 20,000 less half of 20,000 -> 10,000
    assert w.qbi_deduction(100_000, 0, False, 239_250, 0, **QBI_2026) == 10_000
    # above the range: the SSTB gets nothing; a business paying $30,000 of wages gets the wage limit 15,000
    assert w.qbi_deduction(100_000, 0, True, 300_000, 0, **QBI_2026) == 0
    assert w.qbi_deduction(100_000, 30_000, False, 300_000, 0, **QBI_2026) == 15_000


def test_schedule_1a_part_v_deduction_for_people_65_and_over():
    # joint, MAGI 170,000: line 33 20,000; line 34 1,200; line 35 4,800 each; two people -> 9,600
    assert w.over_65_deduction(170_000, 2, 6_000, 150_000, 0.06) == 9_600
    assert w.over_65_deduction(67_300, 1, 6_000, 75_000, 0.06) == 6_000      # under the threshold: the full $6,000
    assert w.over_65_deduction(200_000, 1, 6_000, 75_000, 0.06) == 0        # phased out
    assert w.over_65_deduction(80_000, 0, 6_000, 75_000, 0.06) == 0


def test_schedule_a_line_5e_state_and_local_tax_cap():
    kw = dict(amount=40_400, threshold=505_000, rate=0.30, floor=10_000)
    assert w.state_and_local_tax_deduction(12_000, 200_000, **kw) == 12_000
    assert w.state_and_local_tax_deduction(55_000, 200_000, **kw) == 40_400
    assert w.state_and_local_tax_deduction(55_000, 555_000, **kw) == 25_400   # 40,400 - 30% x 50,000
    assert w.state_and_local_tax_deduction(55_000, 900_000, **kw) == 10_000   # never below $10,000


def test_schedule_8812_child_credit():
    kw = dict(per_child=2_200, other_dependent=500, phase_out_start=400_000, phase_out_per_1000=50,
              refundable_per_child=1_700, earned_income_floor=2_500, refundable_rate=0.15)
    # three children, tax 2,675, earned income 83,641: 6,600 credit; 2,675 used; refundable min(3,925, 5,100, 12,171)
    assert w.child_credit(3, 0, 68_241, 2_675, 83_641, **kw) == (2_675, 3_925)
    # phase-out: AGI 410,500 is 10,500 over -> 11 x $50 = 550 off
    assert w.child_credit(1, 0, 410_500, 50_000, 410_500, **kw) == (1_650, 0)
    # a dependent parent (17 or over) gets the $500 credit, which is never refundable
    assert w.child_credit(0, 1, 60_000, 300, 60_000, **kw) == (300, 0)
    # one child plus a dependent parent: 2,700 credit; line 16a is all of what is left, 16b caps it at 1,700
    assert w.child_credit(1, 1, 60_000, 1_000, 60_000, **kw) == (1_000, 1_700)
    assert w.child_credit(1, 1, 60_000, 2_400, 60_000, **kw) == (2_400, 300)
