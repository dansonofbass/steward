"""The dated business tables (spec 3.2): year, source and checked on every table, the latest earlier table for a
year without one, and the figures spec 5 names."""
import json
from datetime import date

import pytest

from steward.business.rules_table import RULES_DIR, RulesTableError, business_rules


def test_every_business_table_says_its_year_source_and_when_it_was_checked():
    files = sorted(RULES_DIR.glob("business_*.json"))
    assert [f.name for f in files] == ["business_2025.json", "business_2026.json"]
    for f in files:
        t = json.loads(f.read_text())
        assert isinstance(t["year"], int) and t["source"].startswith("https://www.irs.gov/")
        date.fromisoformat(t["checked"])
        assert t["home_office"]["source"].startswith("https://www.irs.gov/")
        assert all(p["source"].startswith("https://www.irs.gov/") for p in t["mileage"])


def test_2026_figures():
    r = business_rules(2026)
    assert (r.year, r.home_office_rate_cents, r.home_office_max_sqft, r.meals_pct) == (2026, 500, 300, 50)
    assert [(p.start, p.end, p.tenths_of_cent) for p in r.mileage] == [
        (date(2026, 1, 1), date(2026, 6, 30), 725), (date(2026, 7, 1), date(2026, 12, 31), 760)]
    assert r.using_note is None


def test_a_year_without_a_table_uses_the_latest_earlier_one_and_says_so():
    r = business_rules(2027)
    assert r.year == 2026 and r.asked_year == 2027 and r.using_note == "Using 2026 rules"
    assert business_rules(2025).mileage[0].tenths_of_cent == 700


def test_a_year_before_every_table_is_refused():
    with pytest.raises(RulesTableError):
        business_rules(2019)

