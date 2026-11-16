"""Care costs (spec 4.2, D5): the dated California table with a source and year on every figure, figures raised to
this year at the care rate, and a quote in place of the typical figure."""
from datetime import date

from steward.care import costs as C
from steward.care.vocab import COST_KEYS
from steward.engine.tax import rules


def test_the_table_carries_every_figure_with_its_source_and_year():
    t = rules.table("care_costs", 2026)
    assert t.year == 2025 and t["state"] == "CA"
    assert set(t["figures"]) == set(COST_KEYS)
    for key, f in t["figures"].items():
        assert f["survey_year"] == 2025 and f["url"].startswith("https://") and f["survey"], key
        assert f["per"] in ("hour", "day", "month"), key
    assert {k: f["cents"] for k, f in t["figures"].items()} == {
        "in_home_hourly": 4000, "adult_day_daily": 9400, "assisted_living_monthly": 700000,
        "memory_care_monthly": 875000, "nursing_home_shared_monthly": 1216700, "nursing_home_private_monthly": 1517800}


def test_a_typical_figure_is_raised_to_this_year_at_the_care_rate():
    f = C.typical("assisted_living_monthly", 2026, 0.04)
    assert (f.cents, f.base_cents, f.base_year, f.quoted_on) == (728000, 700000, 2025, None)
    assert f.line == "Typical in California: CareScout Cost of Care Survey 2025, raised 4% a year to 2026."
    assert C.typical("assisted_living_monthly", 2025, 0.04).line == "Typical in California: CareScout Cost of Care Survey 2025."
    assert C.typical("assisted_living_monthly", 2026, 0.0).line == "Typical in California: CareScout Cost of Care Survey 2025."
    assert C.typical("in_home_hourly", 2027, 0.04).cents == 4326            # $40 x 1.04^2 = $43.264
    assert C.typical("memory_care_monthly", 2025, 0.04).line == "Estimate: assisted living plus 25%, CareScout 2025."


def test_a_quote_replaces_the_typical_figure_and_says_so():
    q = C.Quote("assisted_living_monthly", 645000, date(2026, 10, 2))
    figs = C.figures({q.key: q}, 2026, 0.04)
    assert figs["assisted_living_monthly"].cents == 645000
    assert figs["assisted_living_monthly"].line == "Your quote, October 2, 2026."
    assert figs["memory_care_monthly"].quoted_on is None
    assert C.figures({q.key: q}, 2027, 0.04)["assisted_living_monthly"].cents == 670800


def test_monthly_cost_by_level():
    figs = C.figures({}, 2025, 0.0)
    # $40 x 20 hours x 52 weeks / 12 = $3,466.67; adult day $94 x 2 days x 52 / 12 = $814.67
    assert C.monthly_cents("in_home_help", figs, hours_week=20) == 346667
    assert C.monthly_cents("in_home_help", figs, hours_week=20, adult_day_days=2) == 346667 + 81467
    assert C.monthly_cents("nursing_home", figs, room="private") == 1517800
    assert C.monthly_cents("nursing_home", figs) == 1216700
    assert C.monthly_cents("memory_care", figs) == 875000
    assert C.monthly_cents("assisted_living", figs) == 700000 and C.monthly_cents("at_home", figs) == 0
    assert C.figure_text(figs["in_home_hourly"]) == "$40 an hour"
    assert C.figure_text(C.figures({}, 2026, 0.04)["in_home_hourly"]) == "$41.60 an hour"


def test_dollars_are_whole_and_signed():
    assert (C.dollars(13_000_000), C.dollars(-500), C.dollars(49), C.dollars(150)) == ("$130,000", "−$5", "$0", "$2")
