"""Margaret's care in the demo book: the setup, four scenarios, one quote and the policy's terms."""
from datetime import date

from steward.care.store import read_quotes, read_scenarios, read_setup
from steward.care.views import PREMIUM_STOPS, compute, how
from steward.demo_care import seed_care
from steward.demo_parent import seed_parent
from steward.services.cashflow import cashflow

TODAY = date(2026, 10, 19)
OWNERS = {"margaret": "Margaret", "robert-husband": "Robert (husband)", "joint": "Joint"}


def test_seed_care(mdb):
    seed_parent(mdb, TODAY)
    seed_care(mdb, TODAY)
    s = read_setup(mdb)
    assert (s.person, s.birth_year, s.state, s.care_inflation_bp) == ("margaret", 1944, "CA", 400)
    assert [x.level for x in read_scenarios(mdb)] == ["at_home", "in_home_help", "assisted_living", "nursing_home"]
    assert read_quotes(mdb)["assisted_living_monthly"].cents == 645_000
    v = compute(mdb, OWNERS, TODAY)
    assert len(v.results) == 4 and v.book.policies and v.book.policies[0].benefit_daily_cents == 15_000
    assert v.results[2].ltc_pays_from == 2027


def test_the_demo_card_payment_is_not_money_out_in_month_by_month(mdb):
    # final review I2: the demo pays its Citi card from checking every month, categorized transfer and unpaired
    seed_parent(mdb, TODAY)
    seed_care(mdb, TODAY)
    months = compute(mdb, OWNERS, TODAY).monthly.months
    sept = next(r for r in months if r["month"] == "2026-09")
    assert "transfer" not in {c["category"] for c in sept["categories"]}
    assert sept["out_cents"] == sum(c["out_cents"] for c in sept["categories"])
    with_card = cashflow(mdb, TODAY, 6)[-2]
    citi = next(c["out_cents"] for c in with_card["categories"] if c["category"] == "transfer")
    assert citi > 0 and sept["out_cents"] == with_card["out_cents"] - citi


def test_how_this_works_says_the_premium_stops_once_the_policy_pays(mdb):
    seed_parent(mdb, TODAY)
    seed_care(mdb, TODAY)
    v = compute(mdb, OWNERS, TODAY)
    assert v.book.policies[0].premium_yearly_cents == 254_400
    assert PREMIUM_STOPS in how(v)
