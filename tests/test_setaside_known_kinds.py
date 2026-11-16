"""Polish round, item 3: only true yearly or twice-yearly costs: a known kind, or a category on the eligible list,
with every payment within 25% of the newest, in today's gap bands. Clean names, one row per name and category,
grouped Home, Car, Kids, Memberships, Other, the largest year first."""
from datetime import date

from steward.services import setasides as sa
from tests.factories import make_account, make_txn
from tests.setaside_fixtures import TODAY


def pay(db, acct, d, cents, raw, merchant, category):
    return make_txn(db, acct, d, -cents, raw, merchant=merchant, category=category)


def rows(db):
    return [(s["name"], s["group"], s["kind"]) for s in sa.find_occasional(db, TODAY)]


def test_known_kinds_by_the_table():
    assert sa.known_kind("COUNTY TAX COLLECTOR", "taxes").key == "property_tax"
    assert sa.known_kind("COUNTY PARKS FEE", "home") is None                     # county, not Taxes
    assert sa.known_kind("ST OF CA DMV INTERNET", "transport").name == "DMV registration"
    assert sa.known_kind("GEICO AUTO", "insurance").name == "Car insurance"
    assert sa.known_kind("STATE FARM HOMEOWNERS", "insurance").name == "Home insurance"
    assert sa.known_kind("BIG MUTUAL INS", "insurance").key == "other_insurance"
    assert sa.known_kind("AAA NCNU MEMBERSHIP", "transport").name == "AAA"       # first match wins
    assert sa.known_kind("COSTCO MEMBERSHIP", "shopping").group == "memberships"
    assert sa.known_kind("LINCOLN ELEMENTARY PTA", "personal").group == "kids"
    assert sa.known_kind("LITTLE SPROUTS", "childcare_education").group == "kids"
    assert sa.known_kind("ADOBE", "subscriptions").key == "yearly_subscription"
    assert sa.known_kind("NOODLE HOUSE", "dining") is None


def test_property_tax_under_two_county_keys_is_one_row_in_home(db):
    chk = make_account(db, "Checking")
    pay(db, chk, date(2025, 11, 3), 421_000, "SANTA CLARA COUNTY TAX", "Santa Clara County", "taxes")
    pay(db, chk, date(2026, 4, 10), 421_000, "COUNTY TAX COLLECTOR", "County Tax Collector", "taxes")
    (s,) = sa.find_occasional(db, TODAY)
    assert (s["name"], s["group"], s["kind"], s["payee_key"], s["key"]) == (
        "Property tax", "home", "twice_yearly", "COUNTY TAX COLLECTOR", "COUNTY TAX COLLECTOR|taxes")
    assert (s["due_month"], s["due_day"], s["second_month"], s["second_day"]) == (4, 10, 11, 3)
    assert (s["amount_cents"], s["yearly_cents"], s["monthly_cents"], s["months"]) == (421_000, 842_000, 70_167, [4, 11])
    assert s["payments"] == ["2026-04-10", "2025-11-03"]


def test_dmv_and_aaa_go_to_car_and_a_twice_yearly_school_fee_to_kids(db):
    chk = make_account(db, "Checking")
    for d in (date(2025, 3, 3), date(2026, 3, 10)):
        pay(db, chk, d, 41_200, "ST OF CA DMV INTERNET", None, "transport")
    for d in (date(2025, 6, 1), date(2026, 6, 1)):
        pay(db, chk, d, 18_900, "AAA NCNU", "AAA", "transport")
    for d in (date(2025, 9, 5), date(2026, 3, 5), date(2026, 9, 5)):
        pay(db, chk, d, 12_500, "LINCOLN ELEMENTARY PTA", "Lincoln PTA", "personal")
    assert rows(db) == [("DMV registration", "car", "yearly"), ("AAA", "car", "yearly"), ("Lincoln PTA", "kids", "twice_yearly")]


def test_dining_shopping_and_travel_are_never_yearly_costs(db):
    chk = make_account(db, "Checking")
    for d in (date(2025, 5, 10), date(2026, 5, 12)):
        pay(db, chk, d, 8_000, "NOODLE HOUSE", "Noodle House", "dining")              # two dinners a year apart
        pay(db, chk, d, 150_000, "AIRBNB HMQ", "Airbnb", "travel")                     # a yearly trip
        pay(db, chk, d, 9_900, "MEGAMART", "Megamart", "shopping")
    assert sa.find_occasional(db, TODAY) == []


def test_a_similar_amount_is_within_25_percent_of_the_newest(db):
    chk = make_account(db, "Checking")
    pay(db, chk, date(2025, 5, 9), 110_500, "BIG MUTUAL INS", "Big Mutual", "insurance")     # 20% under: similar
    pay(db, chk, date(2026, 5, 12), 138_000, "BIG MUTUAL INS", "Big Mutual", "insurance")
    pay(db, chk, date(2025, 8, 14), 82_800, "SAFE INS", "Safe Insurance", "insurance")        # 40% under: not
    pay(db, chk, date(2026, 8, 14), 138_000, "SAFE INS", "Safe Insurance", "insurance")
    assert [s["name"] for s in sa.find_occasional(db, TODAY)] == ["Big Mutual"]


def test_groups_in_order_and_the_largest_year_first(db):
    chk = make_account(db, "Checking")
    pay(db, chk, date(2026, 4, 10), 421_000, "COUNTY TAX COLLECTOR", "County Tax Collector", "taxes")
    for d in (date(2025, 7, 1), date(2026, 7, 1)):
        pay(db, chk, d, 180_000, "STATE FARM HOMEOWNERS", "State Farm", "insurance")
        pay(db, chk, d, 6_500, "COSTCO MEMBERSHIP FEE", "Costco", "shopping")
        pay(db, chk, d, 138_000, "BIG MUTUAL INS", "Big Mutual", "insurance")
    assert rows(db) == [("Property tax", "home", "twice_yearly"), ("Home insurance", "home", "yearly"),
                        ("Costco", "memberships", "yearly"), ("Big Mutual", "other", "yearly")]


def test_a_dismissal_of_the_newest_key_leaves_out_the_merged_row(db):
    chk = make_account(db, "Checking")
    pay(db, chk, date(2025, 11, 3), 421_000, "SANTA CLARA COUNTY TAX", "Santa Clara County", "taxes")
    pay(db, chk, date(2026, 4, 10), 421_000, "COUNTY TAX COLLECTOR", "County Tax Collector", "taxes")
    sa.dismiss(db, "COUNTY TAX COLLECTOR", "taxes", by=1)
    db.commit()
    assert sa.find_occasional(db, TODAY) == []
    assert [(d["payee_name"], d["monthly_cents"]) for d in sa.dismissed_view(db, TODAY)] == [("County Tax Collector", 70_167)]
