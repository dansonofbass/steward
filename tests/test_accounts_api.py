from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from steward.db.models import Account, AccountType, Institution, Owner, Source
from steward.services.accounts import staleness_days
from tests.factories import make_user


def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_a_card_or_loan_takes_a_rate_and_nothing_else_does(client, db):
    login(client, db)
    card = client.post("/api/b/ours/accounts", json={"name": "Visa", "type": "credit", "owner": "joint",
                                                     "balance_cents": -430000}).json()
    assert card["rate_bp"] is None
    r = client.patch(f"/api/b/ours/accounts/{card['id']}", json={"rate_bp": 2290})
    assert r.status_code == 200 and r.json()["rate_bp"] == 2290
    assert client.patch(f"/api/b/ours/accounts/{card['id']}", json={"name": "Visa card"}).json()["rate_bp"] == 2290
    assert client.patch(f"/api/b/ours/accounts/{card['id']}", json={"rate_bp": None}).json()["rate_bp"] is None
    for bad in (-1, 10_001, True, "22.9"):
        r = client.patch(f"/api/b/ours/accounts/{card['id']}", json={"rate_bp": bad})
        assert r.status_code == 422, bad
    chk = client.post("/api/b/ours/accounts", json={"name": "Checking", "type": "checking", "owner": "joint",
                                                    "balance_cents": 100}).json()
    r = client.patch(f"/api/b/ours/accounts/{chk['id']}", json={"rate_bp": 400})
    assert r.status_code == 422 and r.json()["error"] == "Only a card or a loan has an interest rate here."


def test_requires_login(client):
    assert client.get("/api/b/ours/accounts").status_code == 401


def test_create_manual_account_with_balance(client, db):
    login(client, db)
    r = client.post("/api/b/ours/accounts", json={"name": "Mortgage", "type": "mortgage", "owner": "joint",
                                           "balance_cents": -41250000, "as_of": "2026-10-01"})
    assert r.status_code == 201
    a = r.json()
    assert a["balance_cents"] == -41250000 and a["as_of"] == "2026-10-01" and a["institution"] == "Manual"
    listed = client.get("/api/b/ours/accounts").json()["accounts"]
    assert listed[0]["name"] == "Mortgage" and listed[0]["stale_days"] >= 0


def test_update_balance_upserts_same_day(client, db):
    login(client, db)
    aid = client.post("/api/b/ours/accounts", json={"name": "529 A", "type": "plan529", "owner": "joint",
                                             "balance_cents": 1000000, "as_of": "2026-10-11"}).json()["id"]
    client.post(f"/api/b/ours/accounts/{aid}/balance", json={"balance_cents": 1100000, "as_of": "2026-10-12"})
    client.post(f"/api/b/ours/accounts/{aid}/balance", json={"balance_cents": 1200000, "as_of": "2026-10-12"})
    a = next(x for x in client.get("/api/b/ours/accounts").json()["accounts"] if x["id"] == aid)
    assert a["balance_cents"] == 1200000 and a["as_of"] == "2026-10-12"


def test_invalid_type_rejected(client, db):
    login(client, db)
    r = client.post("/api/b/ours/accounts", json={"name": "x", "type": "crypto", "owner": "jr", "balance_cents": 0})
    assert r.status_code == 422


def test_staleness():
    assert staleness_days(date(2026, 10, 1), date(2026, 10, 12)) == 11
    assert staleness_days(None, date(2026, 10, 12)) is None


def _manual(client, name="Cash", **kw):
    body = {"name": name, "type": "plan529", "owner": "joint", "balance_cents": 100, **kw}
    return client.post("/api/b/ours/accounts", json=body)


def test_second_manual_institution_rejected(db):
    db.add(Institution(name="Manual", source=Source.manual))
    db.commit()
    db.add(Institution(name="Manual", source=Source.manual))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_manual_institution_reused(client, db):
    login(client, db)
    _manual(client, "A")
    _manual(client, "B")
    assert db.scalar(select(func.count()).select_from(Institution).where(Institution.source == Source.manual)) == 1


def test_synced_account_balance_conflict(client, db):
    login(client, db)
    inst = Institution(name="Bank", source=Source.simplefin)
    db.add(inst)
    db.flush()
    acct = Account(institution_id=inst.id, name="Checking", type=AccountType.checking,
                   owner=Owner.joint, source=Source.simplefin)
    db.add(acct)
    db.commit()
    r = client.post(f"/api/b/ours/accounts/{acct.id}/balance", json={"balance_cents": 5})
    assert r.status_code == 409
    assert r.json() == {"error": "This account updates itself from the bank."}


def test_institutions_account_count(client, db):
    login(client, db)
    db.add(Institution(name="Empty Bank", source=Source.simplefin))
    db.commit()
    _manual(client)
    rows = {i["name"]: i for i in client.get("/api/b/ours/institutions").json()["institutions"]}
    assert rows["Manual"]["account_count"] == 1
    assert rows["Empty Bank"]["account_count"] == 0


def test_patch_account(client, db):
    login(client, db)
    aid = _manual(client).json()["id"]
    r = client.patch(f"/api/b/ours/accounts/{aid}", json={"name": "Renamed", "is_active": False})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed" and r.json()["is_active"] is False
    assert client.patch("/api/b/ours/accounts/9999", json={"name": "x"}).status_code == 404


def test_balance_unknown_account_404(client, db):
    login(client, db)
    assert client.post("/api/b/ours/accounts/9999/balance", json={"balance_cents": 1}).status_code == 404


def test_as_of_defaults_to_pacific_date(client, db, monkeypatch):
    login(client, db)
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc))
    assert _manual(client).json()["as_of"] == "2026-10-12"


def test_liability_balance_must_be_negative(client, db):
    login(client, db)
    body = {"name": "Mortgage", "type": "mortgage", "owner": "joint"}
    r = client.post("/api/b/ours/accounts", json={**body, "balance_cents": 300_000_00})
    assert r.status_code == 422 and r.json() == {"error": "Enter what you owe as a negative number."}
    r = client.post("/api/b/ours/accounts", json={**body, "balance_cents": -300_000_00})
    assert r.status_code == 201
    r = client.post(f"/api/b/ours/accounts/{r.json()['id']}/balance", json={"balance_cents": 299_000_00})
    assert r.status_code == 422 and r.json() == {"error": "Enter what you owe as a negative number."}


def test_patch_sets_and_clears_an_investment_accounts_advisory_fee(frozen, signed_in, db):
    from tests.factories import make_account
    a = make_account(db, "Betterment", type="brokerage_taxable")
    r = signed_in.patch(f"/api/b/ours/accounts/{a.id}", json={"advisory_fee_bp": 25})
    assert r.status_code == 200 and r.json()["advisory_fee_bp"] == 25
    assert signed_in.get("/api/b/ours/accounts").json()["accounts"][0]["advisory_fee_bp"] == 25
    r = signed_in.patch(f"/api/b/ours/accounts/{a.id}", json={"advisory_fee_bp": None})
    assert r.status_code == 200 and r.json()["advisory_fee_bp"] is None


def test_an_advisory_fee_is_for_an_investment_account_from_0_to_3_percent(frozen, signed_in, db):
    from tests.factories import make_account
    chk = make_account(db, "Checking")
    a = make_account(db, "Betterment", type="brokerage_taxable")
    for aid, fee, msg in ((a.id, 301, "Enter a fee between 0% and 3%."), (a.id, -1, "Enter a fee between 0% and 3%."),
                          (chk.id, 25, "Only an investment account has an advisory fee here.")):
        r = signed_in.patch(f"/api/b/ours/accounts/{aid}", json={"advisory_fee_bp": fee})
        assert r.status_code == 422 and r.json() == {"error": msg}, (aid, fee)


def test_a_vehicle_is_entered_by_hand_with_its_value_and_an_optional_loan(frozen, signed_in, db):
    from tests.factories import make_account
    loan = make_account(db, "Car loan", type="loan")
    r = signed_in.post("/api/b/ours/accounts", json={"name": "Subaru", "type": "vehicle", "owner": "joint",
                                                     "balance_cents": 18_000_00, "loan_id": loan.id})
    assert r.status_code == 201 and (r.json()["type"], r.json()["loan_id"], r.json()["balance_cents"]) == ("vehicle", loan.id, 18_000_00)
    vid = r.json()["id"]
    assert signed_in.patch(f"/api/b/ours/accounts/{vid}", json={"loan_id": None}).json()["loan_id"] is None
    assert signed_in.patch(f"/api/b/ours/accounts/{vid}", json={"loan_id": loan.id}).json()["loan_id"] == loan.id
    r = signed_in.post(f"/api/b/ours/accounts/{vid}/balance", json={"balance_cents": -5})
    assert r.status_code == 422 and r.json() == {"error": "Enter what it's worth, as a positive number."}
    assert signed_in.patch(f"/api/b/ours/accounts/{vid}", json={"type": "property"}).json()["loan_id"] is None


def test_the_vehicle_rules(frozen, signed_in, db):
    from tests.factories import make_account
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", source="simplefin", institution_name="Big Bank")
    loan = make_account(db, "Car loan", type="loan")
    new = {"name": "Subaru", "type": "vehicle", "owner": "joint", "balance_cents": 100}
    for method, url, body, msg in (
            ("post", "/api/b/ours/accounts", {**new, "balance_cents": -1}, "Enter what it's worth, as a positive number."),
            ("post", "/api/b/ours/accounts", {**new, "loan_id": chk.id}, "Choose one of your loan accounts."),
            ("post", "/api/b/ours/accounts", {**new, "loan_id": 999}, "Choose one of your loan accounts."),
            ("post", "/api/b/ours/accounts", {**new, "type": "property", "loan_id": loan.id}, "Choose one of your mortgage accounts."),
            ("patch", f"/api/b/ours/accounts/{card.id}", {"type": "vehicle"}, "A vehicle is entered by hand, so a bank's account can't be one.")):
        r = getattr(signed_in, method)(url, json=body)
        assert r.status_code == 422 and r.json() == {"error": msg}, body
