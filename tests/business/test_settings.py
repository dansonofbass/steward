"""The household's business settings (ruling 12): defaults, plain-words refusals, and per-year miles and expectations."""
from datetime import datetime, timezone

import pytest

from steward.business.settings import (
    Expect, HomeOffice, SCorp, SettingsError, business_owner, business_type, expect_for, miles_for, read_settings, update_settings,
)

AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def put(db, body, year=2026, periods=2):
    update_settings(db, body, year=year, this_year=2026, periods=periods, user_id=1, at=AT)
    db.commit()


def test_defaults(db):
    s = read_settings(db, 2026)
    assert (s.type, s.home_office, s.car_method, s.s_corp) == ("none", HomeOffice(), "standard", SCorp())
    assert s.owner == "jr" and business_owner(db) == "jr"      # who runs the business: the first adult by default
    assert business_type(db) == "none" and miles_for(db, 2026, 2) == (0, 0) and expect_for(db, 2026) is None


def test_values_round_trip(db):
    put(db, {"type": "sole_prop", "car_method": "actual", "miles": [1200, 900],
             "home_office": {"method": "actual", "office_sqft": 150, "home_sqft": 1500, "home_costs_cents": 3_600_000},
             "expect": {"low_cents": -100_000, "high_cents": 2_000_000}, "s_corp": {"salary_pct": 60, "cost_cents": 200_000}})
    s = read_settings(db, 2026)
    assert s.type == "sole_prop" and s.car_method == "actual"
    assert s.home_office == HomeOffice("actual", 150, 1500, 3_600_000) and s.s_corp == SCorp(60, 200_000)
    assert miles_for(db, 2026, 2) == (1200, 900) and expect_for(db, 2026) == Expect(-100_000, 2_000_000)
    put(db, {"expect": None})
    assert expect_for(db, 2026) is None


def test_miles_follow_the_number_of_rate_periods(db):
    put(db, {"miles": [5000]}, year=2025, periods=1)
    assert miles_for(db, 2025, 1) == (5000,) and miles_for(db, 2025, 2) == (5000, 0)


@pytest.mark.parametrize("body,message", [
    ({"type": "llc"}, "Choose none, sole proprietor or S-corp."),
    ({"home_office": {"method": "garage"}}, "Choose no home office, the simplified method or actual expenses."),
    ({"home_office": {"method": "simplified", "office_sqft": -1}}, "Enter square feet as a whole number from 0 to 100,000."),
    ({"home_office": {"method": "simplified", "office_sqft": 12.5}}, "Enter square feet as a whole number from 0 to 100,000."),
    ({"home_office": {"method": "actual", "office_sqft": 300, "home_sqft": 200, "home_costs_cents": 0}},
     "The office can't be bigger than the home."),
    ({"home_office": {"method": "actual", "office_sqft": 100, "home_sqft": 1000, "home_costs_cents": -5}},
     "Enter the yearly home costs from $0 to $10,000,000."),
    ({"car_method": "bike"}, "Choose standard mileage or actual costs."),
    ({"miles": [100]}, "Enter business miles as whole numbers, one for each rate period."),
    ({"miles": [100, True]}, "Enter business miles as whole numbers, one for each rate period."),
    ({"expect": {"low_cents": 500, "high_cents": 100}}, "The low can't be more than the high."),
    ({"expect": {"low_cents": "a", "high_cents": 100}}, "Enter the low and high as whole numbers of cents."),
    ({"s_corp": {"salary_pct": 0, "cost_cents": 150_000}}, "Enter the salary as a percent of profit from 1 to 100."),
    ({"s_corp": {"salary_pct": 50, "cost_cents": 10_000_001}}, "Enter the yearly cost from $0 to $100,000."),
    ({"colour": "blue"}, "That request wasn't understood."),
    ({"owner": "business"}, "Choose who runs the business."),
])
def test_bad_values_are_refused_in_plain_words(db, body, message):
    with pytest.raises(SettingsError) as e:
        put(db, body)
    assert str(e.value) == message


def test_expectations_are_for_this_year_only(db):
    with pytest.raises(SettingsError) as e:
        put(db, {"expect": {"low_cents": 0, "high_cents": 1}}, year=2025, periods=1)
    assert str(e.value) == "Expected profit is for this year only."


def test_home_office_and_car_are_kept_per_year_and_a_new_year_starts_from_the_last(db):
    """Final review ruling I2: last year can be finished, and this year's settings never rewrite it."""
    put(db, {"home_office": {"method": "simplified", "office_sqft": 150}, "car_method": "actual"}, year=2026)
    assert read_settings(db, 2026).home_office == HomeOffice("simplified", 150, 0, 0)
    assert read_settings(db, 2027).home_office == HomeOffice("simplified", 150, 0, 0)    # starts from 2026's
    assert read_settings(db, 2027).car_method == "actual" and read_settings(db, 2025).car_method == "standard"
    update_settings(db, {"home_office": {"method": "none"}, "car_method": "standard"}, year=2027, this_year=2027,
                    periods=1, user_id=1, at=AT)
    assert read_settings(db, 2026).home_office == HomeOffice("simplified", 150, 0, 0)
    assert read_settings(db, 2026).car_method == "actual" and read_settings(db, 2027).car_method == "standard"


def test_changing_last_year_leaves_this_year_as_it_was_shown(db):
    put(db, {"home_office": {"method": "simplified", "office_sqft": 150}, "car_method": "actual"}, year=2026)
    shown = read_settings(db, 2027)
    update_settings(db, {"home_office": {"method": "simplified", "office_sqft": 90}, "car_method": "standard"},
                    year=2026, this_year=2027, periods=2, user_id=1, at=AT)
    assert read_settings(db, 2027) == shown
    assert read_settings(db, 2026).home_office.office_sqft == 90 and read_settings(db, 2026).car_method == "standard"


def test_who_runs_the_business_is_one_value_for_every_year(db):
    """Final review ruling I2."""
    put(db, {"owner": "spouse"}, year=2025)
    assert read_settings(db, 2026).owner == "spouse" and read_settings(db, 2025).owner == "spouse"
    assert business_owner(db) == "spouse"
