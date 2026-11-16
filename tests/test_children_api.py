from datetime import date

from steward.db.models import BalanceSnapshot
from tests.factories import make_account

K = "/api/b/ours/children"


def test_kids_crud_with_share_living_and_a_soft_remove(frozen, signed_in, db):
    c = signed_in
    p529 = make_account(db, "529 Ava", type="plan529")
    r = c.post(K, json={"label": " Ava ", "birth_year": 2015, "account_id": p529.id, "monthly_contribution_cents": 30_000})
    assert r.status_code == 201
    kid = r.json()
    assert (kid["label"], kid["cost_level"], kid["share_pct"], kid["covers_living"]) == ("Ava", "not_sure", 100, True)
    assert kid["college_start_year"] == 2033 and kid["undo"]
    assert set(kid["outlook"]) == {"years", "total_cents", "covered_cents"} and kid["outlook"]["years"] == 4
    r = c.patch(f"{K}/{kid['id']}", json={"cost_level": "two_year", "share_pct": 50, "covers_living": False})
    assert (r.json()["cost_level"], r.json()["share_pct"], r.json()["covers_living"], r.json()["outlook"]["years"]) == (
        "two_year", 50, False, 2)
    body = c.get(K).json()
    assert list(body["college"]["levels"]) == ["two_year", "in_state_public", "out_of_state_public", "private"]
    assert body["plans"][0]["account_id"] == p529.id and body["children"][0]["plan529"]["monthly_cents"] == 30_000
    r = c.delete(f"{K}/{kid['id']}")
    assert r.status_code == 200 and set(r.json()) == {"undo"}
    assert c.get(K).json()["children"] == []
    assert c.patch(f"{K}/{kid['id']}", json={"label": "x"}).json() == {"error": "No such child."}
    assert c.delete(f"{K}/{kid['id']}").status_code == 404


def test_kid_values_are_checked_in_plain_words(frozen, signed_in, db):
    base = {"label": "Ava", "birth_year": 2015}
    cases = [
        ({**base, "label": ""}, "Enter the kid's name."),
        ({**base, "birth_year": 1990}, "Enter a birth year between 1996 and 2027."),
        ({**base, "cost_level": "ivy"}, "Choose a school type."),
        ({**base, "share_pct": 55}, "Choose a share from 0% to 100%."),
        ({**base, "share_pct": 110}, "Choose a share from 0% to 100%."),
        ({**base, "covers_living": "yes"}, "Say true or false for living costs."),
        ({**base, "monthly_contribution_cents": -1}, "Enter a monthly amount that isn't negative."),
        ({**base, "name": "Pat"}, "Unknown field: name."),
        ({"label": "Ava"}, "Enter a birth year between 1996 and 2027."),
        ({**base, "set_type": True}, "Choose one of your 529 accounts."),
    ]
    for body, message in cases:
        r = signed_in.post(K, json=body)
        assert r.status_code == 422 and r.json() == {"error": message}, body
    assert signed_in.get(K).json()["children"] == []


def test_529_links_set_type_and_a_529_that_belongs_to_another_kid(frozen, signed_in, db):
    c = signed_in
    p529 = make_account(db, "529", type="plan529")
    savings = make_account(db, "Ava's college fund", type="savings")
    card = make_account(db, "Visa", type="credit")
    base = {"label": "Ava", "birth_year": 2015}
    assert c.post(K, json={**base, "account_id": savings.id}).json() == {"error": "Choose one of your 529 accounts."}
    assert c.post(K, json={**base, "account_id": card.id, "set_type": True}).json() == {"error": "That account can't be a 529 plan."}
    ava = c.post(K, json={**base, "account_id": p529.id}).json()
    r = c.post(K, json={"label": "Ben", "birth_year": 2018, "account_id": p529.id})
    assert r.status_code == 409 and r.json() == {"error": "That 529 already belongs to Ava."}
    ben = c.post(K, json={"label": "Ben", "birth_year": 2018}).json()
    r = c.patch(f"{K}/{ben['id']}", json={"account_id": savings.id, "set_type": True})
    assert r.status_code == 200 and r.json()["account_id"] == savings.id
    db.rollback()   # end the read snapshot so we see the request's commit
    assert savings.type.value == "plan529"
    assert c.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200    # one Undo: the link and the type
    db.rollback()   # end the read snapshot so we see the request's commit
    assert savings.type.value == "savings"
    assert c.patch(f"{K}/{ava['id']}", json={"account_id": p529.id}).status_code == 200      # its own 529 is fine


def test_a_suggestion_appears_for_an_unlinked_kid(frozen, signed_in, db):
    acct = make_account(db, "Ava 529", type="plan529")
    kid = signed_in.post(K, json={"label": "Ava", "birth_year": 2015}).json()
    assert signed_in.get(K).json()["suggestions"] == [
        {"child_id": kid["id"], "account_id": acct.id, "account_name": "Ava 529", "account_type": "plan529"}]


def test_children_need_sign_in(client):
    assert client.get(K).status_code == 401
    assert client.post(K, json={}).status_code == 401
