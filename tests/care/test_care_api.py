"""The Care routes (spec 4): parent books only, managers edit, viewers read, every write in the change record.
Fictional parent: Margaret Ellis. Today is 2026-10-13 (the frozen fixture)."""
import pytest

from steward.care import edit as E
from steward.care.views import NO_SPENDING
from steward.deps import NOT_IN_THIS_BOOK, VIEWER_COPY
from tests.factories import login

CARE = "/api/b/margaret-ellis/care"
CHANGES = "/api/b/margaret-ellis/changes?kind=care"
SETUP = {"person": "margaret", "birth_year": 1944, "spouse_birth_year": None, "state": "CA", "care_inflation_bp": 400,
         "spending_monthly_cents": 400_000}


def _texts(client) -> list[str]:
    return [c["text"] for c in client.get(CHANGES).json()["changes"]]


def test_before_setup(frozen, margaret, client):
    login(client, "jr")
    out = client.get(CARE).json()
    assert (out["set_up"], out["setup"], out["scenarios"], out["medi_cal"]) == (False, None, [], None)
    assert out["people"] == [{"key": "margaret", "label": "Margaret"},
                             {"key": "robert-husband", "label": "Robert (husband)"}]
    assert len(out["monthly"]["months"]) == 6 and out["max_scenarios"] == 5


def test_setup_makes_two_scenarios_and_is_recorded(frozen, margaret, client):
    login(client, "jr")
    r = client.put(f"{CARE}/setup", json=SETUP)
    assert r.status_code == 200
    out = r.json()
    assert (out["set_up"], out["age"], out["this_year"]) == (True, 82, 2026)
    assert [s["label"] for s in out["scenarios"]] == ["At home as today", "Assisted living from 2027"]
    # no savings in the inventory and $4,000 a month going out
    assert all(s["headline"] == "Money runs short in 2026 (age 82)" for s in out["scenarios"])
    al = next(c for c in out["costs"] if c["key"] == "assisted_living_monthly")
    assert (al["text"], al["quote"]) == ("$7,280 a month", None)
    assert al["line"] == "Typical in California: CareScout Cost of Care Survey 2025, raised 4% a year to 2026."
    assert out["medi_cal"]["rule_line"] == ("Limit $130,000 for one person, from January 1, 2026 (2026 rules, DHCS All "
                                            "County Welfare Directors Letter 25-14).")
    assert out["medi_cal"]["disclaimer"] == "An estimate to take to an elder-law attorney, not legal advice."
    assert out["medi_cal"]["topics"][2] == "The 30-month look-back on gifts and transfers (2026 rules)"
    assert out["spending"]["line"] == "Spending: $4,000 a month, typed in."
    assert out["how"][0] == out["spending"]["line"] and "Care costs rise 4% a year." in out["how"]
    assert "set up Care" in _texts(client)
    again = client.put(f"{CARE}/setup", json={**SETUP, "spending_monthly_cents": 450_000}).json()
    assert len(again["scenarios"]) == 2 and again["spending"]["line"] == "Spending: $4,500 a month, typed in."
    assert _texts(client)[0] == "changed Care setup"


@pytest.mark.parametrize("change,error", [
    ({"person": "joint"}, E.PERSON_RULE), ({"birth_year": 1850}, "Enter the year born, from 1900 to 2026."),
    ({"spouse_birth_year": "1946"}, "Enter the spouse's year born, from 1900 to 2026, or leave it blank."),
    ({"state": "XX"}, E.STATE_RULE), ({"care_inflation_bp": 2000}, E.GROWTH_RULE),
    ({"spending_monthly_cents": -1}, E.SPENDING_RULE),
])
def test_bad_setup_is_refused_in_plain_words(frozen, margaret, client, change, error):
    login(client, "jr")
    r = client.put(f"{CARE}/setup", json={**SETUP, **change})
    assert (r.status_code, r.json()) == (422, {"error": error})


def test_scenarios_add_change_and_remove(frozen, margaret, client):
    login(client, "jr")
    assert client.post(f"{CARE}/scenarios", json={"level": "at_home"}).json() == {"error": E.NOT_SET_UP}
    client.put(f"{CARE}/setup", json=SETUP)
    r = client.post(f"{CARE}/scenarios", json={"level": "in_home_help", "hours_week": 20})
    assert r.status_code == 201
    added = r.json()["scenarios"][-1]
    # $41.60 an hour in 2026 dollars x 20 hours x 52 / 12
    assert (added["label"], added["care_monthly_cents"]) == ("In-home help, 20 hours a week, starting now", 360_533)
    assert client.post(f"{CARE}/scenarios", json={"level": "in_home_help"}).json() == {"error": E.HOURS_RULE}
    assert client.post(f"{CARE}/scenarios", json={"level": "hospice"}).json() == {"error": E.LEVEL_RULE}
    changed = client.patch(f"{CARE}/scenarios/{added['id']}", json={"level": "nursing_home", "room": "private"}).json()
    s = next(x for x in changed["scenarios"] if x["id"] == added["id"])
    assert (s["label"], s["hours_week"], s["room"]) == ("Nursing home, private room, starting now", None, "private")
    for _ in range(2):
        client.post(f"{CARE}/scenarios", json={"level": "memory_care", "start_year": 2030})
    assert len(client.get(CARE).json()["scenarios"]) == 5
    over = client.post(f"{CARE}/scenarios", json={"level": "memory_care"})
    assert (over.status_code, over.json()) == (422, {"error": E.TOO_MANY})
    ids = [x["id"] for x in client.get(CARE).json()["scenarios"]]
    for i in ids[1:]:
        assert client.delete(f"{CARE}/scenarios/{i}").status_code == 200
    last = client.delete(f"{CARE}/scenarios/{ids[0]}")
    assert (last.status_code, last.json()) == (422, {"error": E.LAST_ONE})
    assert client.delete(f"{CARE}/scenarios/999999").json() == {"error": E.NO_SUCH_SCENARIO}
    assert {"added a care scenario", "changed a care scenario", "removed a care scenario"} <= set(_texts(client))


def test_selling_without_a_home_in_the_inventory_needs_a_price(frozen, margaret, client):
    login(client, "jr")
    client.put(f"{CARE}/setup", json=SETUP)
    assert client.post(f"{CARE}/scenarios", json={"level": "at_home", "sell_home_year": 2028}).json() == {"error": E.NO_HOME}
    ok = client.post(f"{CARE}/scenarios", json={"level": "at_home", "sell_home_year": 2028, "home_price_cents": 78_000_000})
    assert ok.status_code == 201
    assert ok.json()["scenarios"][-1]["levers"][0].startswith(
        "Home sold in 2028 for $780,000, less 6% selling costs; no purchase price entered")


def test_a_quote_replaces_the_typical_figure_and_can_be_removed(frozen, margaret, client):
    login(client, "jr")
    client.put(f"{CARE}/setup", json=SETUP)
    out = client.put(f"{CARE}/quotes/assisted_living_monthly", json={"cents": 645_000, "quoted_on": "2026-10-02"}).json()
    al = next(c for c in out["costs"] if c["key"] == "assisted_living_monthly")
    assert (al["text"], al["line"], al["quote"]) == ("$6,450 a month", "Your quote, October 2, 2026.",
                                                     {"cents": 645_000, "quoted_on": "2026-10-02"})
    scenario = next(s for s in out["scenarios"] if s["level"] == "assisted_living")
    assert scenario["cost_lines"] == ["Assisted living: $6,450 a month. Your quote, October 2, 2026."]
    late = client.put(f"{CARE}/quotes/assisted_living_monthly", json={"cents": 645_000, "quoted_on": "2026-10-14"})
    assert late.json() == {"error": E.QUOTE_DATE_RULE}
    assert client.put(f"{CARE}/quotes/hospice", json={"cents": 1, "quoted_on": "2026-10-02"}).json() == {"error": E.QUOTE_KEY_RULE}
    back = client.delete(f"{CARE}/quotes/assisted_living_monthly").json()
    assert next(c for c in back["costs"] if c["key"] == "assisted_living_monthly")["quote"] is None
    assert client.delete(f"{CARE}/quotes/assisted_living_monthly").json() == {"error": E.NO_QUOTE}
    texts = _texts(client)
    assert "entered a quote for assisted living" in texts
    assert "went back to the typical cost for assisted living" in texts


def test_viewers_read_and_household_books_have_no_care(frozen, margaret, client):
    login(client, "jr")
    client.put(f"{CARE}/setup", json=SETUP)
    assert client.get("/api/b/ours/care").json() == {"error": NOT_IN_THIS_BOOK}
    login(client, "vee")
    assert client.get(CARE).json()["set_up"] is True
    for method, path, body in (("put", "/setup", SETUP), ("post", "/scenarios", {"level": "at_home"}),
                               ("put", "/quotes/assisted_living_monthly", {"cents": 1, "quoted_on": "2026-10-02"})):
        r = getattr(client, method)(f"{CARE}{path}", json=body)
        assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY})


def test_a_book_without_transactions_says_no_spending_is_counted(frozen, margaret, client):
    # Review Focus 1
    login(client, "jr")
    out = client.put(f"{CARE}/setup", json={**SETUP, "spending_monthly_cents": None}).json()
    assert out["spending"]["line"] == NO_SPENDING and out["how"][0] == NO_SPENDING
    assert out["scenarios"][0]["headline"] == "Lasts past age 100"


def test_how_this_works_names_the_age_the_projection_really_runs_to(frozen, margaret, client):
    # M4: born 1944 runs to 100; born 1966 stops at the 40-year cap, age 99; born 1925 gets the one year, age 101
    login(client, "jr")
    for born, age in ((1944, 100), (1966, 99), (1925, 101)):
        how = client.put(f"{CARE}/setup", json={**SETUP, "birth_year": born}).json()["how"]
        assert f"Each year counts in full, this year included, and the projection runs to age {age}." in how, born


def test_an_edit_next_year_moves_past_years_to_now():
    # Review Focus 2: saved in 2026 "from 2026" with the home sold in 2026, edited in 2027
    current = {"level": "assisted_living", "start_year": 2026, "hours_week": None, "adult_day_days": None, "room": None,
               "sell_home_year": 2026, "home_price_cents": 1_000_000, "home_basis_cents": None, "selling_cost_bp": 600,
               "family_monthly_cents": 0, "spending_change_monthly_cents": 0}
    out = E.clean_scenario({"family_monthly_cents": 10_000}, current, 2027, None)
    assert (out["start_year"], out["sell_home_year"], out["family_monthly_cents"]) == (None, 2027, 10_000)
    with pytest.raises(E.CareRefused, match=r"Choose a start year from 2027 to 2067, or now\."):
        E.clean_scenario({"start_year": 2026}, current, 2027, None)
