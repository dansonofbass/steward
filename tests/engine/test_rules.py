"""Dated rule tables (spec 3.2): every table carries its year (or effective dates), source and checked date; a year
with no table uses the latest earlier one; the values match their published sources."""
import json
from datetime import date

import pytest

from steward.engine.tax import rules


def test_every_table_has_a_year_a_source_and_a_checked_date():
    tables = rules.all_tables()
    assert {t.topic for t in tables} >= {"federal", "payroll", "retirement", "medicare", "rmd"}
    for t in tables:
        assert t.source and all(s.strip() for s in t.source), t.topic
        assert isinstance(t.checked, date) and t.checked <= date(2026, 12, 31), t.topic
        assert t.effective_from.year == t.year


def test_a_single_string_source_from_the_business_tables_loads_as_a_one_item_tuple():
    t = rules.table("business", 2026)
    assert isinstance(t.source, tuple) and len(t.source) == 1 and t.source[0].startswith("https://")


@pytest.mark.parametrize("drop", ["source", "checked", "year"])
def test_a_table_missing_its_metadata_is_refused(tmp_path, drop):
    raw = json.loads((rules.RULES_DIR / "payroll_2026.json").read_text())
    del raw[drop]
    path = tmp_path / "payroll_2026.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(rules.RulesError):
        rules.load(path)


def test_a_misnamed_or_mismatched_table_is_refused(tmp_path):
    raw = json.loads((rules.RULES_DIR / "payroll_2026.json").read_text())
    (tmp_path / "payroll_2027.json").write_text(json.dumps(raw))
    with pytest.raises(rules.RulesError, match="doesn't match"):
        rules.load(tmp_path / "payroll_2027.json")
    (tmp_path / "Payroll-2026.json").write_text(json.dumps(raw))
    with pytest.raises(rules.RulesError, match="named"):
        rules.load(tmp_path / "Payroll-2026.json")
    raw["source"] = []
    (tmp_path / "payroll_2026.json").write_text(json.dumps(raw))
    with pytest.raises(rules.RulesError, match="source"):
        rules.load(tmp_path / "payroll_2026.json")


def test_a_year_without_its_own_table_uses_the_latest_earlier_one():
    assert rules.table("federal", 2025).year == 2025
    assert rules.table("federal", 2026).year == 2026
    assert rules.table("federal", 2041).year == 2026
    assert rules.table("rmd", 2030).year == 2022
    with pytest.raises(rules.RulesError, match="no federal rules for 2019"):
        rules.table("federal", 2019)


def test_federal_2026_pins_rev_proc_2025_32_and_the_obbba():
    f = rules.table("federal", 2026)
    assert f["brackets"]["mfj"] == [[0, 0.10], [24800, 0.12], [100800, 0.22], [211400, 0.24], [403550, 0.32], [512450, 0.35], [768700, 0.37]]
    assert f["brackets"]["single"] == [[0, 0.10], [12400, 0.12], [50400, 0.22], [105700, 0.24], [201775, 0.32], [256225, 0.35], [640600, 0.37]]
    assert f["standard_deduction"] == {"mfj": 32200, "single": 16100} and f["aged_additional"] == {"mfj": 1650, "single": 2050}
    assert f["ltcg"] == {"mfj": [98900, 613700], "single": [49450, 545500]}
    assert f["ss_thresholds"] == {"mfj": [32000, 44000], "single": [25000, 34000]}
    assert f["salt_cap"] == {"amount": 40400, "threshold": 505000, "rate": 0.30, "floor": 10000}
    assert f["over_65_deduction"] == {"amount": 6000, "threshold": {"mfj": 150000, "single": 75000}, "rate": 0.06, "last_year": 2028}
    assert f["charity"] == {"non_itemizer_cap": {"mfj": 2000, "single": 1000}, "itemized_floor": 0.005}
    assert f["qbi"]["threshold"] == {"mfj": 403500, "single": 201750} and f["qbi"]["phase_in"] == {"mfj": 150000, "single": 75000}
    assert (f["qbi"]["minimum_deduction"], f["qbi"]["minimum_qbi"]) == (400, 1000)
    assert f["child_credit"]["per_child"] == 2200 and f["child_credit"]["refundable_per_child"] == 1700
    assert f["medical_floor"] == 0.075 and f["home_sale_exclusion"] == {"mfj": 500000, "single": 250000}
    assert f["estimates"]["high_income_agi"] == 150000 and f["estimates"]["high_income_prior_year_share"] == 1.10


def test_federal_2025_pins_rev_proc_2024_40_with_the_obbba_changes():
    f = rules.table("federal", 2025)
    assert f["brackets"]["mfj"][1] == [23850, 0.12] and f["brackets"]["mfj"][-1] == [751600, 0.37]
    assert f["brackets"]["single"][2] == [48475, 0.22] and f["brackets"]["single"][-1] == [626350, 0.37]
    assert f["standard_deduction"] == {"mfj": 31500, "single": 15750} and f["aged_additional"] == {"mfj": 1600, "single": 2000}
    assert f["ltcg"] == {"mfj": [96700, 600050], "single": [48350, 533400]}
    assert f["salt_cap"]["amount"] == 40000 and f["salt_cap"]["threshold"] == 500000
    assert f["charity"] is None and f["itemized_limit"] is None and f["qbi"]["minimum_deduction"] == 0


def test_payroll_retirement_and_medicare_pin_their_sources():
    assert rules.table("payroll", 2026)["wage_base"] == 184500 and rules.table("payroll", 2025)["wage_base"] == 176100
    assert rules.table("payroll", 2026)["se"] == {"net_factor": 0.9235, "oasdi_rate": 0.124, "medicare_rate": 0.029, "minimum_net_earnings": 400}
    r = rules.table("retirement", 2026)
    assert (r["k401_deferral"], r["k401_catch_up_50"], r["k401_catch_up_60_to_63"], r["overall_cap"]) == (24500, 8000, 11250, 72000)
    assert (r["ira"], r["ira_catch_up_50"], r["compensation_cap"]) == (7500, 1100, 360000)
    assert r["hsa"] == {"self_only": 4400, "family": 8750, "catch_up_55": 1000}
    assert r["roth_ira_phaseout"] == {"mfj": [242000, 252000], "single": [153000, 168000]}   # Notice 2025-67
    m = rules.table("medicare", 2026)
    assert m["part_b_monthly"] == 202.90 and m["part_b_deductible"] == 283 and m["income_lookback_years"] == 2


@pytest.mark.parametrize("magi, filing, want", [
    (109_000, "single", (202.90, 0.0)),        # "less than or equal to $109,000"
    (109_001, "single", (284.10, 14.50)),
    (205_000, "single", (527.50, 60.40)),
    (499_999, "single", (649.20, 83.30)),      # "less than $500,000"
    (500_000, "single", (689.90, 91.00)),      # "greater than or equal to $500,000"
    (218_000, "mfj", (202.90, 0.0)),
    (300_000, "mfj", (405.80, 37.50)),
    (750_000, "mfj", (689.90, 91.00)),
])
def test_irmaa_follows_the_cms_2026_table(magi, filing, want):
    assert rules.irmaa_monthly(magi, filing, 2026) == want


def test_rmd_ages_and_divisors_follow_pub_590b_and_secure_2():
    assert [rules.rmd_start_age(b, 2026) for b in (1949, 1950, 1951, 1959, 1960, 1982)] == [72, 72, 73, 73, 75, 75]
    assert rules.rmd_divisor(75, 2026) == 24.6 and rules.rmd_divisor(82, 2026) == 18.5 and rules.rmd_divisor(125, 2026) == 2.0
    assert rules.rmd_divisor(70, 2026) == 27.4                    # below the table: its first row
    assert len(rules.table("rmd", 2026)["uniform_lifetime"]) == 49



def test_the_old_tax_data_is_gone_and_the_checklist_reads_the_rules():
    from steward.engine import checklist, datafiles
    assert not hasattr(datafiles, "tax_tables") and not hasattr(datafiles, "uniform_lifetime")
    assert not (datafiles.DATA_DIR / "tax_2026.json").exists() and not (datafiles.DATA_DIR / "uniform_lifetime.csv").exists()
    r = rules.table("retirement", 2026)
    assert checklist.K401_LIMIT_CENTS == r["k401_deferral"] * 100 == 2_450_000
    assert checklist.ROTH_IRA_LIMIT_CENTS == r["ira"] * 100 and checklist.HSA_FAMILY_LIMIT_CENTS == r["hsa"]["family"] * 100
