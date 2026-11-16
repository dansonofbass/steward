"""GET and PUT /business/settings: the rules year shown with the figures, managers change, viewers read, parent
books have no business (Review Focus 3)."""
from datetime import date

from tests.factories import add_fact, login, make_person, make_user

URL = "/api/b/ours/business/settings"


def test_defaults_carry_the_rules_and_the_rate_periods(frozen, signed_in):
    r = signed_in.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == 2026 and body["this_year"] == 2026 and body["type"] == "none" and body["expect"] is None
    assert body["home_office"] == {"method": "none", "office_sqft": 0, "home_sqft": 0, "home_costs_cents": 0}
    assert body["car_method"] == "standard" and body["s_corp"] == {"salary_pct": 50, "cost_cents": 150_000}
    assert body["miles"] == [{"from": "2026-01-01", "to": "2026-06-30", "rate_tenths": 725, "miles": 0},
                             {"from": "2026-07-01", "to": "2026-12-31", "rate_tenths": 760, "miles": 0}]
    assert body["rules"] == {"year": 2026, "using_note": None, "home_office_rate_cents": 500,
                             "home_office_max_sqft": 300, "meals_pct": 50}
    assert signed_in.get(URL + "?year=2025").json()["miles"] == [
        {"from": "2025-01-01", "to": "2025-12-31", "rate_tenths": 700, "miles": 0}]


def test_a_manager_changes_settings_and_gets_them_back(frozen, signed_in):
    r = signed_in.put(URL, json={"type": "sole_prop", "miles": [1200, 900],
                                 "expect": {"low_cents": 800_000, "high_cents": 2_000_000}})
    assert r.status_code == 200 and r.json()["type"] == "sole_prop"
    assert [p["miles"] for p in r.json()["miles"]] == [1200, 900]
    assert signed_in.get(URL).json()["expect"] == {"low_cents": 800_000, "high_cents": 2_000_000}


def test_refusals_and_years(frozen, signed_in):
    r = signed_in.put(URL, json={"type": "llc"})
    assert r.status_code == 422 and r.json() == {"error": "Choose none, sole proprietor or S-corp."}
    assert signed_in.put(URL, json=[1]).status_code == 422
    for bad in ("2024", "2027", "abc"):
        r = signed_in.get(f"{URL}?year={bad}")
        assert r.status_code == 422 and r.json() == {"error": "Choose this year or last year."}
    r = signed_in.put(URL, json={"year": 2024, "miles": [1]})
    assert r.status_code == 422 and r.json() == {"error": "Choose this year or last year."}


def test_a_viewer_reads_and_cannot_change(frozen, client, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.get(URL).status_code == 200
    r = client.put(URL, json={"type": "sole_prop"})
    assert r.status_code == 403 and r.json() == {"error": "You can see this book but not change it."}


def test_parent_books_have_no_business(frozen, client, margaret):
    login(client, "jr")
    for method, body in (("GET", None), ("PUT", {"type": "sole_prop"})):
        r = client.request(method, "/api/b/margaret-ellis/business/settings", json=body)
        assert r.status_code == 404 and r.json() == {"error": "This book doesn't have that."}


def test_last_years_home_office_and_car_can_be_changed(frozen, signed_in):
    """Final review ruling I2: Settings, Business has a year switch."""
    signed_in.put(URL, json={"type": "sole_prop", "car_method": "actual",
                             "home_office": {"method": "simplified", "office_sqft": 200}})
    r = signed_in.put(URL, json={"year": 2025, "car_method": "standard", "miles": [3000],
                                 "home_office": {"method": "simplified", "office_sqft": 120}})
    assert r.status_code == 200 and (r.json()["year"], r.json()["this_year"]) == (2025, 2026)
    assert r.json()["home_office"]["office_sqft"] == 120 and r.json()["car_method"] == "standard"
    now = signed_in.get(URL).json()
    assert now["home_office"]["office_sqft"] == 200 and now["car_method"] == "actual"


def test_who_runs_the_business_is_one_of_the_adults(frozen, signed_in, db):
    """Final review ruling I2: one of the household's adults, the first by default. A household of one has one."""
    assert [a["key"] for a in signed_in.get(URL).json()["adults"]] == ["jr"]
    make_user(db, "sam", "sam@x.com", "Sam")
    body = signed_in.get(URL).json()
    assert body["owner"] == "jr" and [a["key"] for a in body["adults"]] == ["jr", "spouse"]
    assert body["adults"][0]["name"] == "JR"
    r = signed_in.put(URL, json={"owner": "spouse"})
    assert r.status_code == 200 and r.json()["owner"] == "spouse"
    add_fact(db, "filing_status", "single", as_of=date(2026, 10, 2))
    body = signed_in.get(URL).json()
    assert body["owner"] == "jr" and [a["key"] for a in body["adults"]] == ["jr"]   # a single filer: the one adult
    r = signed_in.put(URL, json={"owner": "spouse"})
    assert r.status_code == 422 and r.json() == {"error": "Choose one of the adults on the return."}
