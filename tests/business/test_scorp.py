"""The S-corp comparison (spec 5.4; ruling 14), first against a stand-in tax function with known numbers, then once
against part 1's real engine for the direction of the answer."""
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest

from steward.business.scorp import NotReady, compare
from steward.business.settings import update_settings
from tests.factories import add_fact, make_account, make_txn

TODAY = date(2026, 10, 13)
AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


@dataclass
class FakeResult:
    total_tax_cents: int
    rules_year: int = 2026
    state: object = None


def fake_tax(facts, year):
    """10% on all income, plus 14.13% self-employment tax on a sole proprietor's profit. An S-corp's payroll tax
    (15.3% of the salary) is added by the comparison itself from the payroll table. Only for checking the arithmetic."""
    income = facts.wages_cents + facts.business_profit_cents + facts.scorp_profit_cents
    return FakeResult(income // 10 + facts.business_profit_cents * 1413 // 10_000, rules_year=year)


def household(db, profit_cents, low=None, high=None, state="CA", salary="0"):
    for k, v in (("jr.dob", "1982-05-01"), ("spouse.dob", "1984-08-01"), ("state", state), ("filing_status", "mfj"),
                 ("jr.salary_cents", salary)):
        add_fact(db, k, v)
    make_txn(db, make_account(db, "Business checking", type="business_checking", owner="business"),
             date(2026, 3, 3), profit_cents, "ACH CLIENT INV 1", category="business_income", is_business=True)
    body = {"type": "sole_prop", "car_method": "actual"}
    if low is not None:
        body["expect"] = {"low_cents": low, "high_cents": high}
    update_settings(db, body, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    db.commit()


def test_the_arithmetic_at_the_range(db):
    household(db, 4_000_000, low=2_000_000, high=6_000_000)           # full year $60,000 to $100,000
    c = compare(db, 2026, TODAY, tax=fake_tax)
    assert [p.label for p in c.points] == ["low", "middle", "high"]
    mid = c.points[1]
    assert (mid.profit_cents, mid.salary_cents, mid.cost_cents) == (8_000_000, 4_000_000, 150_000)
    assert mid.sole_tax_cents == 800_000 + 8_000_000 * 1413 // 10_000
    # Payroll tax 7.65% each side on $40,000. The S-corp's net income is 80,000 - 40,000 - 3,060 - 1,500 = 35,440;
    # 1.5% of it is $532, so California's $800 minimum franchise tax applies. SDI is 1.3% of the $40,000 salary.
    assert (mid.payroll_cents, mid.franchise_cents, mid.sdi_cents) == (612_000, 80_000, 52_000)
    # California UI (3.4%) and ETT (0.1%) on the first $7,000 of wages: $245, also a business cost. K-1 income is the net
    # income less that and the franchise tax: 35,440 - 245 - 800 = 34,395
    assert mid.unemployment_cents == 24_500
    assert mid.scorp_tax_cents == (4_000_000 + 3_439_500) // 10 + 612_000 + 80_000 + 52_000 + 24_500
    assert mid.saves_cents == mid.sole_tax_cents - mid.scorp_tax_cents - 150_000
    assert (mid.sole_tax_cents, mid.scorp_tax_cents, mid.saves_cents) == (1_930_400, 1_512_450, 267_950)
    assert c.worth_it is True and c.line == "An S-corp would save about $2,700 a year at your profit."   # nearest $100
    assert c.rules_note == "2026 tax rules"
    assert c.state_note == "Includes California's S-corp franchise tax, employer unemployment and training taxes, and SDI on the salary."


def test_california_does_not_allow_the_franchise_tax_as_a_deduction_from_k1_income(db):
    household(db, 8_000_000)
    seen = []

    def recording_tax(facts, year):
        seen.append(facts)
        return fake_tax(facts, year)
    c = compare(db, 2026, TODAY, tax=recording_tax)
    sole, scorp = seen
    franchise = c.points[0].franchise_cents
    assert franchise > 0 and sole.state_addback_cents == 0
    assert scorp.state_addback_cents == franchise                     # the federal return deducts it; California adds it back
    assert scorp.scorp_profit_cents == 8_000_000 - 4_000_000 - 612_000 // 2 - 150_000 - franchise - c.points[0].unemployment_cents


def test_the_employer_owes_social_security_on_the_salary_whatever_the_owner_earns_elsewhere(db):
    # Final review minor 1: $120,000 of other wages and a $75,000 salary. The employer pays 6.2% on all of it; the
    # owner's own Social Security stops at the wage base (the excess comes back as a credit).
    household(db, 15_000_000, salary="12000000")
    p = compare(db, 2026, TODAY, tax=fake_tax).points[0]
    assert p.salary_cents == 7_500_000
    assert p.payroll_cents == round(7_500_000 * 0.0765) + round(6_450_000 * 0.062 + 7_500_000 * 0.0145)


def test_another_states_s_corp_costs_are_named_as_not_included(db):
    household(db, 4_000_000, state="NY")
    c = compare(db, 2026, TODAY, tax=fake_tax)
    assert c.points[0].franchise_cents == 0 and c.points[0].sdi_cents == 0
    assert c.state_note == "New York's S-corp and payroll taxes aren't included."


def test_a_year_without_its_own_tax_rules_says_which_rules_it_used(db):
    household(db, 4_000_000)

    def older(facts, year):
        return FakeResult(1, rules_year=2025)
    assert compare(db, 2026, TODAY, tax=older).rules_note == "Using 2025 rules"


def test_the_state_rules_year_shows_when_older(db):
    household(db, 4_000_000)

    @dataclass
    class St:
        rules_year: int

    def ca(facts, year):
        return FakeResult(1, rules_year=year, state=St(2025))
    assert compare(db, 2026, TODAY, tax=ca).rules_note == "2026 federal and 2025 California rules"


def test_other_filing_statuses_are_not_ready_in_plain_words(db):
    household(db, 4_000_000)
    add_fact(db, "filing_status", "hoh", as_of=date(2026, 10, 2))
    db.commit()
    with pytest.raises(NotReady) as e:
        compare(db, 2026, TODAY, tax=fake_tax)
    assert str(e.value) == "The comparison works for married filing jointly or single."


def test_a_small_profit_is_not_yet_worth_it_and_without_a_range_there_is_one_point(db):
    household(db, 800_000)
    c = compare(db, 2026, TODAY, tax=fake_tax)
    assert [p.label for p in c.points] == ["so far"] and c.worth_it is False
    # Final review minor 3: year to date isn't a year; say so, and point to the expected range
    assert c.line == ("Not yet worth it at your profit so far. Add what you expect for the rest of the year to compare "
                      "the full year.")


def test_a_saving_so_far_says_so_far(db):
    household(db, 25_000_000)
    c = compare(db, 2026, TODAY, tax=fake_tax)
    assert c.worth_it and c.line.endswith("a year at your profit so far.")


def test_a_loss_compares_nothing(db):
    household(db, -50_000)
    c = compare(db, 2026, TODAY, tax=fake_tax)
    assert c.points[0].saves_cents == 0 and c.worth_it is False


def test_it_needs_the_households_tax_facts(db):
    update_settings(db, {"type": "sole_prop"}, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    db.commit()
    with pytest.raises(NotReady) as e:
        compare(db, 2026, TODAY, tax=fake_tax)
    assert str(e.value) == "Add both birth dates, your state and how you file taxes in Set up first."


def test_the_real_engine_agrees_on_the_direction(db):
    household(db, 25_000_000)                                           # $250,000 so far
    assert compare(db, 2026, TODAY).worth_it is True


def test_the_real_engine_says_a_small_business_isnt_worth_it(db):
    household(db, 1_000_000)                                            # $10,000 so far
    assert compare(db, 2026, TODAY).worth_it is False

def test_a_spouse_who_runs_the_business_counts_only_their_own_wages(db):
    """Final review ruling I2: JR earns $120,000 at a W-2 job and Sam runs the business. Schedule SE and the S-corp
    salary's Social Security count Sam's wages (none), not JR's."""
    household(db, 15_000_000, salary="12000000")
    update_settings(db, {"owner": "spouse"}, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    db.commit()
    seen = []

    def recording_tax(facts, year):
        seen.append(facts)
        return fake_tax(facts, year)
    p = compare(db, 2026, TODAY, tax=recording_tax).points[0]
    sole, scorp = seen
    assert (sole.business_owner, sole.ss_wages_by_person_cents) == (1, (12_000_000, 0))
    assert (scorp.business_owner, scorp.ss_wages_by_person_cents) == (1, (12_000_000, 7_500_000))
    assert p.payroll_cents == 2 * round(7_500_000 * 0.0765)            # all of Sam's salary is under the wage base
