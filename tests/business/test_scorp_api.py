"""GET /business/s-corp (spec 5.4): available for sole proprietors and S-corps with their tax facts, plain words
otherwise, and nothing in parent books."""
from datetime import date

from steward.business.settings import update_settings
from steward.engine.inputs import InputError
from tests.factories import add_fact, login, make_account, make_txn, make_user


def test_the_comparison_and_its_refusals(frozen, signed_in, db):
    r = signed_in.get("/api/b/ours/business/s-corp").json()
    assert r == {"available": False, "reason": "Choose sole proprietor or S-corp in Settings, Business."}
    update_settings(db, {"type": "s_corp"}, year=2026, this_year=2026, periods=2, user_id=1, at=frozen)
    db.commit()
    r = signed_in.get("/api/b/ours/business/s-corp").json()
    assert r == {"available": False, "reason": "Add both birth dates, your state and how you file taxes in Set up first."}
    for k, v in (("jr.dob", "1982-05-01"), ("spouse.dob", "1984-08-01"), ("state", "CA"), ("filing_status", "mfj")):
        add_fact(db, k, v)
    make_txn(db, make_account(db, "Business checking", type="business_checking", owner="business"),
             date(2026, 3, 3), 25_000_000, "ACH CLIENT INV 1", category="business_income", is_business=True)
    r = signed_in.get("/api/b/ours/business/s-corp").json()
    assert r["available"] is True and r["worth_it"] is True and r["line"].startswith("An S-corp would save about $")
    assert [p["label"] for p in r["points"]] == ["so far"]
    assert r["rules_note"] in ("2026 tax rules", "Using 2025 rules", "2026 federal and 2025 California rules")
    add_fact(db, "filing_status", "hoh", as_of=date(2026, 10, 2))
    r = signed_in.get("/api/b/ours/business/s-corp").json()
    assert r == {"available": False, "reason": "The comparison works for married filing jointly or single."}


def test_an_engine_refusal_names_person_1_by_label(frozen, client, db, monkeypatch):
    """TRI-1: an engine refusal that reaches the S-corp card as the reason names Person 1 by the household's label."""
    def refuse(*args, **kwargs):
        raise InputError("{person1} must be born before the plan year.")
    make_user(db, username="alex", email="alex@x.com", display_name="Alex")
    login(client, "alex")
    update_settings(db, {"type": "s_corp"}, year=2026, this_year=2026, periods=2, user_id=1, at=frozen)
    db.commit()
    monkeypatch.setattr("steward.api.business.compare", refuse)
    r = client.get("/api/b/ours/business/s-corp").json()
    assert r == {"available": False, "reason": "Alex must be born before the plan year."}


def test_parent_books_have_no_s_corp(frozen, client, margaret):
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/business/s-corp").status_code == 404
