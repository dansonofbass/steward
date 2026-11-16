"""Estimates from an item's age (spec, Estimates): the planned year is a year before the end of the usual range,
the amount the middle of the cost range (a car: less what it sells for), and every figure has a source."""
import json
from datetime import date

import pytest

from steward.services import setasides as sa

TODAY = date(2026, 10, 25)


def test_the_data_file_names_its_sources():
    data = sa.lifespans()
    assert isinstance(data["source"], list) and data["source"] and data["checked"]["date"] >= "2026-10-01"
    assert data["checked"]["covers"] and data["needs_check"]
    assert set(data["items"]) == {"roof", "water_heater", "hvac", "car", "appliance"}
    for key, item in data["items"].items():
        lo, hi = item["lifespan_years"]
        clo, chi = item["cost_cents"]
        assert 0 < lo < hi and 0 < clo <= chi and item["source"].strip() and item["label"], key
    assert data["items"]["car"]["lifespan_miles"] == [150_000, 200_000] and data["items"]["car"]["resale_bp"] == 2300
    assert sa.ITEMS == ("roof", "water_heater", "hvac", "car", "appliance", "other")


def test_what_is_unverified_says_so_and_is_flagged():
    data = sa.lifespans()
    today = date(2026, 10, 25)
    args = {"roof": {"installed_year": 2010}, "water_heater": {"installed_year": 2014}, "hvac": {"installed_year": 2010},
            "car": {"model_year": 2016}, "appliance": {"installed_year": 2014}}
    for key, item in data["items"].items():
        e = sa.estimate(key, today, **args[key])
        assert "to be checked" in item["cost_source"] and e["cost_to_check"] is True, key
        if key in data["needs_check"]:
            assert "to be checked" in item["source"] and e["to_check"] is True, key
        else:
            assert "to be checked" not in item["source"] and e["to_check"] is False, key
        assert e["sources"] == [item["source"], item["cost_source"]], key
        assert json.loads(sa.estimate_json(e))["to_check"] is e["to_check"]
    assert not data["needs_check"] == list(data["items"])        # something is verified
    assert "energy.gov/sites/default/files/2024-04/cwh_fr1.pdf" in data["items"]["water_heater"]["source"]


def test_a_car_with_almost_no_miles_is_decided_by_age():
    e = sa.estimate("car", TODAY, model_year=2016, miles=4)          # under half a mile a year: no pace to count
    assert (e["decided_by"], e["miles_per_year"], e["planned_year"]) == ("age", 0, 2030)


def test_the_data_file_is_refused_without_its_sources(tmp_path, monkeypatch):
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"source": [], "checked": {"date": "2026-10-26", "covers": []}, "items": {}}))
    monkeypatch.setattr(sa, "DATA", bad)
    sa.lifespans.cache_clear()
    try:
        with pytest.raises(sa.EstimateError, match="source list"):
            sa.lifespans()
        bad.write_text(json.dumps({"source": ["s"], "checked": {"date": "2026-10-26", "covers": []},
                                   "items": {"roof": {"source": " ", "cost_source": "c"}}}))
        sa.lifespans.cache_clear()
        with pytest.raises(sa.EstimateError, match="roof needs a source"):
            sa.lifespans()
    finally:
        sa.lifespans.cache_clear()


def test_a_water_heater_from_2014_is_planned_for_december_2028():
    e = sa.estimate("water_heater", TODAY, installed_year=2014)
    assert (e["label"], e["age"], e["lifespan"], e["range"], e["planned_year"]) == ("Water heater", 12, [10, 15], [2024, 2029], 2028)
    assert (e["due_year"], e["due_month"], e["first_month"], e["months"]) == (2028, 12, "2026-11-01", 26)
    assert (e["cost_range"], e["replacement_cents"], e["sale_cents"], e["amount_cents"]) == ([150_000, 300_000], 225_000, 0, 225_000)
    assert e["monthly_cents"] == sa.div_round(225_000, 26) and e["decided_by"] == "age"
    assert e["sources"] and all(isinstance(s, str) for s in e["sources"])


def test_a_car_counts_its_age_and_its_miles_and_the_later_year_loses():
    """A 2016 car with 118,000 miles is likely by 2030: $28,000 less $6,440 it sells for, over 50 months."""
    e = sa.estimate("car", TODAY, model_year=2016, miles=118_000)
    assert (e["age"], e["miles_per_year"], e["lifespan"], e["lifespan_miles"]) == (10, 11_800, [12, 15], [150_000, 200_000])
    assert (e["range"], e["decided_by"], e["planned_year"]) == ([2028, 2031], "age", 2030)
    assert (e["replacement_cents"], e["sale_cents"], e["amount_cents"], e["months"], e["monthly_cents"]) == (
        2_800_000, 644_000, 2_156_000, 50, 43_120)
    # 40,000 miles a year: it is already past 200,000, so the miles end is this year (2026), before 2031, and decides.
    m = sa.estimate("car", TODAY, model_year=2016, miles=400_000)
    assert (m["decided_by"], m["range"], m["planned_year"]) == ("miles", [2028, 2026], 2026)
    assert m["due_year"] == 2026 and m["months"] == 2


def test_an_item_past_its_range_is_planned_for_this_december_or_next():
    assert sa.estimate("water_heater", TODAY, installed_year=2000)["planned_year"] == 2026          # 2000 + 15 - 1 = 2014: gone
    assert sa.estimate("water_heater", date(2026, 12, 3), installed_year=2000)["planned_year"] == 2027   # in December, next year
    assert sa.estimate("roof", TODAY, installed_year=2026)["planned_year"] == 2026 + 30 - 1


def test_other_has_no_estimate_and_bad_inputs_are_refused():
    with pytest.raises(sa.EstimateError, match="no typical lifespan"):
        sa.estimate("other", TODAY, installed_year=2010)
    with pytest.raises(sa.EstimateError, match="Choose"):
        sa.estimate("boat", TODAY, installed_year=2010)
    with pytest.raises(sa.EstimateError, match="installed"):
        sa.estimate("roof", TODAY)
    with pytest.raises(sa.EstimateError, match="1950"):
        sa.estimate("roof", TODAY, installed_year=1949)
    with pytest.raises(sa.EstimateError, match="future"):
        sa.estimate("roof", TODAY, installed_year=2027)
    with pytest.raises(sa.EstimateError, match="model year"):
        sa.estimate("car", TODAY, miles=50_000)
    with pytest.raises(sa.EstimateError, match="miles"):
        sa.estimate("car", TODAY, model_year=2016, miles=-1)
    assert sa.estimate("car", TODAY, model_year=2016)["decided_by"] == "age"      # miles are optional


def test_a_given_cost_replaces_the_middle_of_the_range():
    """The replacement one-off after a paid one carries what the paid one cost (sale 0), and keeps it in its estimate."""
    e = sa.estimate("car", TODAY, model_year=2016, miles=118_000, cost_cents=3_000_000)
    assert (e["replacement_cents"], e["sale_cents"], e["amount_cents"]) == (3_000_000, 0, 3_000_000)
    assert e["cost_range"] == [2_000_000, 3_600_000] and e["monthly_cents"] == 60_000 and e["months"] == 50
    assert json.loads(sa.estimate_json(e))["replacement_cents"] == 3_000_000
    with pytest.raises(sa.EstimateError, match="cost"):
        sa.estimate("roof", TODAY, installed_year=2010, cost_cents=0)


def test_the_stored_estimate_keeps_the_basis_and_is_unconfirmed():
    e = sa.estimate("water_heater", TODAY, installed_year=2014)
    stored = json.loads(sa.estimate_json(e))
    assert stored == {"item": "water_heater", "installed_year": 2014, "model_year": None, "miles": None,
                      "lifespan": [10, 15], "cost_range": [150_000, 300_000], "planned_year": 2028,
                      "replacement_cents": 225_000, "sale_cents": 0, "to_check": False, "cost_to_check": True,
                      "confirmed": False}
