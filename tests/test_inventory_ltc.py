"""D8: the long-term care policy is an inventory item with its terms (spec 4.1)."""
import pytest

from tests.factories import login

BOOK = "/api/b/margaret-ellis/inventory"
LTC = {"kind": "insurance", "name": "Long-term care", "owner": "margaret", "institution": "Evergreen Mutual",
       "status": "confirmed",
       "details": {"type": "long_term_care", "amount_cents": 21200, "frequency": "monthly", "benefit_cents": 15000,
                   "benefit_per": "day", "waiting_days": 90, "benefit_years": 3, "rider_bp": 300}}
TERMS = ("benefit_cents", "benefit_per", "waiting_days", "benefit_years", "rider_bp")


def test_a_policy_keeps_its_terms_and_the_change_record_names_them(frozen, margaret, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/items", json=LTC)
    assert r.status_code == 201
    item = r.json()["id"]
    d = client.get(f"{BOOK}/items/{item}").json()["details"]
    assert {k: d[k] for k in TERMS} == {"benefit_cents": 15000, "benefit_per": "day", "waiting_days": 90,
                                        "benefit_years": 3, "rider_bp": 300}
    assert client.patch(f"{BOOK}/items/{item}",
                        json={"details": {"pool_cents": 16_425_000, "benefit_years": None}}).status_code == 200
    history = client.get(f"{BOOK}/items/{item}").json()["history"]
    assert history[0]["diffs"] == [{"label": "Total benefit", "before": "not known", "after": "$164,250.00"},
                                   {"label": "Benefit years", "before": "3 years", "after": "not known"}]


@pytest.mark.parametrize("terms,error", [
    ({"benefit_cents": 15000}, "Choose whether the benefit is paid by the day or the month."),
    ({"benefit_cents": 15000, "benefit_per": "week"}, "Choose whether the benefit is paid by the day or the month."),
    ({"benefit_cents": 15000, "benefit_per": "day", "waiting_days": 1000}, "Enter the waiting period in days, from 0 to 730."),
    ({"benefit_cents": 15000, "benefit_per": "day", "benefit_years": 0}, "Enter the benefit years as a whole number from 1 to 30."),
    ({"benefit_cents": 15000, "benefit_per": "day", "rider_bp": 1500}, "Enter inflation protection from 0% to 10% a year."),
    ({"benefit_cents": -1, "benefit_per": "day"}, "Enter an amount in dollars and cents."),
])
def test_bad_terms_are_refused_in_plain_words(frozen, margaret, client, terms, error):
    login(client, "jr")
    r = client.post(f"{BOOK}/items", json={**LTC, "details": {"type": "long_term_care", **terms}})
    assert (r.status_code, r.json()) == (422, {"error": error})


def test_blank_terms_are_not_stored(frozen, margaret, client):
    login(client, "jr")
    blanks = {k: None for k in ("benefit_cents", "benefit_per", "waiting_days", "pool_cents", "benefit_years", "rider_bp")}
    item = client.post(f"{BOOK}/items", json={**LTC, "details": {"type": "long_term_care", "amount_cents": 21200,
                                                                  "frequency": "monthly", **blanks}}).json()["id"]
    d = client.get(f"{BOOK}/items/{item}").json()["details"]
    assert not set(blanks) & set(d)


def test_another_kind_of_policy_drops_the_terms(frozen, margaret, client):
    login(client, "jr")
    item = client.post(f"{BOOK}/items", json=LTC).json()["id"]
    client.patch(f"{BOOK}/items/{item}", json={"details": {"type": "supplement"}})
    d = client.get(f"{BOOK}/items/{item}").json()["details"]
    assert d["type"] == "supplement" and not set(TERMS) & set(d)
