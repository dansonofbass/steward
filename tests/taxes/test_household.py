"""The household's year for the tax engine (rulings 3, 14, 19)."""
from datetime import date

import pytest

from steward.taxes.household import ADD_RANGE, FILING_ONLY, LEFT_OUT, NEEDS, SCORP, NotReady, household_tax
from tests.factories import add_fact
from tests.taxes.helpers import household

TODAY = date(2026, 10, 13)


def test_it_needs_set_up_first(db):
    with pytest.raises(NotReady, match=NEEDS):
        household_tax(db, 2026, TODAY)
    household(db)
    add_fact(db, "filing_status", "hoh", as_of=date(2026, 10, 2))
    with pytest.raises(NotReady, match=FILING_ONLY):
        household_tax(db, 2026, TODAY)


def test_salary_deferrals_children_and_the_range(db):
    # $160,000 salary, 10% to the 401(k), half of it Roth; profit so far $40,000, the rest of the year $20,000-$60,000
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000, salary="16000000", k401="1000", roth="5000",
              kids=(2015, 2008, 2007))
    h = household_tax(db, 2026, TODAY)
    f = h.facts
    assert (f.filing, f.ages, f.state) == ("mfj", (44, 42), "CA")
    assert (f.wages_cents, f.payroll_wages_cents, h.w2_deferrals_cents) == (15_200_000, 16_000_000, 1_600_000)
    assert f.ss_wages_by_person_cents == (16_000_000, 0) and f.business_owner == 0  # owner_index: JR by default
    assert f.dependents == (11, 18)                  # 19 at the end of 2026 isn't counted (ruling 19)
    assert (h.profit_cents, f.business_profit_cents) == (10_000_000, 10_000_000)   # the high end (ruling 3)
    assert household_tax(db, 2026, TODAY, point="low").profit_cents == 6_000_000
    assert household_tax(db, 2026, TODAY, point="mid").profit_cents == 8_000_000
    assert household_tax(db, 2026, TODAY, point="so_far").profit_cents == 4_000_000
    assert h.notes == (LEFT_OUT,) and (h.jr_age, h.salary_cents, h.business) == (44, 16_000_000, "sole_prop")


def test_deferrals_stop_at_the_limit(db):
    household(db, salary="50000000", k401="1000")                    # 10% of $500,000 is over $24,500
    h = household_tax(db, 2026, TODAY)
    assert h.w2_deferrals_cents == 2_450_000 and h.facts.wages_cents == 50_000_000 - 2_450_000


def test_no_range_says_so_and_no_business_counts_nothing(db):
    household(db, profit_cents=3_000_000)
    h = household_tax(db, 2026, TODAY)
    assert h.profit_cents == 3_000_000 and h.notes == (LEFT_OUT, ADD_RANGE)


def test_without_a_business_there_is_no_profit(db):
    household(db, business="none")
    h = household_tax(db, 2026, TODAY)
    assert (h.range, h.profit_cents, h.facts.business_profit_cents) == (None, 0, 0)


def test_an_s_corp_is_figured_as_a_sole_proprietor(db):
    household(db, profit_cents=3_000_000, business="s_corp")
    assert SCORP in household_tax(db, 2026, TODAY).notes


def test_single_has_one_age(db):
    household(db, filing="single")
    h = household_tax(db, 2026, TODAY)
    assert h.facts.ages == (44,) and h.facts.ss_wages_by_person_cents == (0,)


def test_a_spouse_run_business_is_the_spouses_on_the_return(db):
    from datetime import datetime, timezone
    from steward.business.settings import update_settings
    household(db, profit_cents=3_000_000, salary="9000000")
    update_settings(db, {"owner": "spouse"}, year=2026, this_year=2026, periods=2, user_id=1,
                    at=datetime(2026, 10, 13, tzinfo=timezone.utc))
    db.commit()
    assert household_tax(db, 2026, TODAY).facts.business_owner == 1
