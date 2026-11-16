"""Payroll tax on wages and a state's S-corp costs (final review I2 and minors 1-2): both live in the tax engine,
from the dated rule tables."""
import pytest

from steward.engine.tax import payroll_tax, rules, scorp_state_costs


def test_both_halves_of_payroll_tax_on_a_salary_2026():
    p = payroll_tax(7_500_000, 2026)
    assert p.employee_cents == p.employer_cents == round(7_500_000 * 0.0765)
    assert p.total_cents == p.employee_cents + p.employer_cents


def test_the_employer_owes_social_security_to_the_wage_base_whatever_the_employee_earns_elsewhere_2026():
    # Final review minor 1: $120,000 of other wages and a $75,000 salary. The employer pays 6.2% on all $75,000; the
    # employee's Social Security stops at the $184,500 wage base ($64,500 of room) and the excess comes back as a credit.
    p = payroll_tax(7_500_000, 2026, other_ss_wages_cents=12_000_000)
    assert p.employer_cents == round(7_500_000 * 0.062 + 7_500_000 * 0.0145)
    assert p.employee_cents == round(6_450_000 * 0.062 + 7_500_000 * 0.0145)
    assert p.total_cents == pytest.approx(1_082_400, abs=100)
    # a salary over the wage base: Social Security stops there for both halves, Medicare doesn't
    big = payroll_tax(20_000_000, 2026)
    assert big.employer_cents == round(18_450_000 * 0.062 + 20_000_000 * 0.0145)


def test_california_s_corp_franchise_tax_and_sdi_from_the_dated_tables_2026():
    t = rules.table("california_business", 2026)
    assert t["scorp_franchise_rate"] == 0.015 and t["minimum_franchise_tax"] == 800
    assert t["sdi_rate"] == 0.013 and t["sdi_wage_limit"] is None
    assert rules.table("california_business", 2025)["sdi_rate"] == 0.012
    assert any("ftb.ca.gov" in s for s in t.source) and any("edd.ca.gov" in s for s in t.source)
    assert t["new_employer_ui_rate"] == 0.034 and t["ett_rate"] == 0.001 and t["ui_ett_wage_limit"] == 7000
    # $150,000 of net income before UI and ETT. Employer UI and ETT are 3.5% of the first $7,000 of wages: $245, which
    # comes off the net income; 1.5% of the rest is $2,246.32, over the $800 minimum; SDI is 1.3% of every dollar of a
    # $75,000 salary
    c = scorp_state_costs("CA", salary_cents=7_500_000, net_income_cents=15_000_000, year=2026)
    assert c.calculated and c.unemployment_cents == 24_500 and c.franchise_cents == 224_632
    assert c.sdi_cents == 97_500 and c.rules_year == 2026
    assert c.total_cents == 224_632 + 24_500 + 97_500
    # a salary under $7,000 owes UI and ETT on all of it
    assert scorp_state_costs("CA", salary_cents=500_000, net_income_cents=0, year=2026).unemployment_cents == 17_500
    # a small S-corp still owes the $800 minimum; SDI has no wage cap since 2024
    small = scorp_state_costs("CA", salary_cents=30_000_000, net_income_cents=2_000_000, year=2026)
    assert small.franchise_cents == 80_000 and small.sdi_cents == 390_000
    # a later year with no table of its own uses the latest one and says so
    assert scorp_state_costs("CA", salary_cents=0, net_income_cents=0, year=2028).rules_year == 2026


def test_another_state_s_corp_costs_are_not_calculated_and_say_so():
    c = scorp_state_costs("NY", salary_cents=7_500_000, net_income_cents=15_000_000, year=2026)
    assert not c.calculated and c.franchise_cents == 0 and c.sdi_cents == 0
    assert c.explain == ("New York's S-corp and payroll taxes aren't included.",)
