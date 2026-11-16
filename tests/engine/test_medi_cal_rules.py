"""The Medi-Cal rule table (spec 3.6): the 2026 asset limit, exempt property, the look-back, and the 2027 change
recorded as reported but unconfirmed, so no projection uses it."""
from datetime import date

from steward.engine.tax import rules


def test_medi_cal_2026_and_the_unconfirmed_2027_change():
    m = rules.table("medi_cal", 2026)
    assert m.effective_from == date(2026, 1, 1) and m.effective_to is None
    assert m["asset_limit"] == {"first_person": 130000, "each_additional": 65000, "max_household": 10}
    assert m["look_back_months"] == 30 and "home" in m["exempt"]
    (later,) = m["scheduled"]
    assert later["effective_from"] == "2027-07-01" and later["status"] == "reported_unconfirmed"
