"""Reimbursable spec, Trips and Settling: making and editing a trip, its review list, marking in one request with one
Undo (unticked rows leave the trip), the Reimbursements summary, Settle and its Undo, and the refusals."""
from datetime import date

from sqlalchemy import select

from steward.db.models import ReimburseSettlement
from steward.services import reimburse as rb
from tests.factories import login, make_account, make_txn, make_user

TRIP = {"start": "2026-10-06", "end": "2026-10-09", "city": "Chicago, IL"}


def setup(client, db):
    make_user(db)
    login(client, "jr")
    acme = client.post("/api/b/ours/reimburse/payers", json={"name": "Acme"}).json()
    card = make_account(db, "Sapphire", type="credit")
    rows = {
        "hotel": make_txn(db, card, date(2026, 10, 6), -61_200, "PALMER HOUSE HOTEL", category="travel"),
        "ride": make_txn(db, card, date(2026, 10, 7), -2_840, "UBER TRIP", category="transport"),
        "dinner": make_txn(db, card, date(2026, 10, 7), -5_580, "PORTILLOS CHICAGO IL", category="dining"),
        "kids": make_txn(db, card, date(2026, 10, 8), -2_500, "BRIGHT KIDS DAYCARE", category="childcare_education"),
    }
    return acme, rows


def trip(client, **over):
    r = client.post("/api/b/ours/reimburse/trips", json={**TRIP, **over})
    assert r.status_code == 201, r.text
    return r.json()["trip"]


def test_a_trip_is_made_with_a_default_name_and_edited(client, db):
    acme, _ = setup(client, db)
    t = trip(client)
    assert {k: t[k] for k in ("name", "start", "end", "city", "reimburser_id", "payer", "count", "total_cents", "status")} == {
        "name": "Chicago trip", "start": "2026-10-06", "end": "2026-10-09", "city": "Chicago, IL",
        "reimburser_id": acme["id"], "payer": "Acme", "count": 0, "total_cents": 0, "status": None}
    r = client.patch(f"/api/b/ours/reimburse/trips/{t['id']}", json={**TRIP, "name": "Chicago, spring", "end": "2026-10-10"})
    assert (r.json()["trip"]["name"], r.json()["trip"]["end"]) == ("Chicago, spring", "2026-10-10")
    assert client.post("/api/b/ours/reimburse/trips", json={**TRIP, "end": "2026-10-01"}).json() == {
        "error": "The trip ends before it starts."}
    assert client.get("/api/b/ours/reimburse/trips/999").json() == {"error": "No such trip."}


def test_the_review_list_and_marking_in_one_request_with_one_undo(client, db):
    acme, rows = setup(client, db)
    t = trip(client)
    got = client.get(f"/api/b/ours/reimburse/trips/{t['id']}").json()
    listed = {r["id"]: (r["group"], r["reason"], r["ticked"]) for r in got["rows"]}
    assert listed[rows["hotel"].id] == ("likely", {"why": "hotel"}, True)
    assert listed[rows["kids"].id] == ("home", {"why": "home_only", "category": "childcare_education"}, False)
    ids = [rows[k].id for k in ("hotel", "ride", "dinner")]
    r = client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark", json={"ids": ids})
    assert r.status_code == 200
    out = r.json()
    assert {k: out[k] for k in ("count", "total_cents", "payer", "owed_cents")} == {
        "count": 3, "total_cents": 69_620, "payer": "Acme", "owed_cents": 69_620}
    assert (out["trip"]["count"], out["trip"]["total_cents"], out["trip"]["status"]) == (3, 69_620, "waiting")
    db.rollback()
    assert [(rows[k].trip_id, rows[k].reimburser_id) for k in ("hotel", "ride", "dinner")] == [(t["id"], acme["id"])] * 3
    # Untick the ride: it leaves the trip and is no longer reimbursable (engineering choice 4).
    again = client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark", json={"ids": ids[:1] + ids[2:]}).json()
    db.rollback()
    assert (rows["ride"].trip_id, rows["ride"].reimburser_id, rows["ride"].reimburse_source) == (None, None, "manual")
    assert again["owed_cents"] == 66_780
    assert client.post(f"/api/b/ours/undo/{again['undo']}").status_code == 200
    db.rollback()
    assert (rows["ride"].trip_id, rows["ride"].reimburser_id) == (t["id"], acme["id"])
    assert client.post(f"/api/b/ours/undo/{out['undo']}").status_code == 200
    db.rollback()
    assert all(rows[k].trip_id is None and rows[k].reimburser_id is None for k in ("hotel", "ride", "dinner"))


def test_marking_ids_outside_the_list_is_refused(client, db):
    _, rows = setup(client, db)
    t = trip(client)
    far = make_txn(db, make_account(db), date(2026, 3, 1), -1_000, "FAR AWAY")
    for ids in ([far.id], [rows["hotel"].id, rows["hotel"].id], ["1"], "x"):
        r = client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark", json={"ids": ids})
        assert r.status_code == 422, ids
    assert client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark", json={"ids": [far.id]}).json() == {
        "error": "That list changed. Open the trip again."}


def test_undoing_a_trip_after_a_row_changed_is_409_and_changes_nothing(client, db):
    """Review Focus 4."""
    acme, rows = setup(client, db)
    t = trip(client)
    out = client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark",
                      json={"ids": [rows["hotel"].id, rows["dinner"].id]}).json()
    client.patch(f"/api/b/ours/transactions/{rows['dinner'].id}", json={"category": "entertainment"})
    r = client.post(f"/api/b/ours/undo/{out['undo']}")
    assert (r.status_code, r.json()) == (409, {"error": "That changed since, so it can't be undone."})
    db.rollback()
    assert (rows["hotel"].trip_id, rows["dinner"].trip_id) == (t["id"], t["id"])


def test_the_summary_has_each_payers_balance_the_trips_and_the_single_charges(client, db):
    acme, rows = setup(client, db)
    t = trip(client)
    client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark", json={"ids": [rows["hotel"].id]})
    db.rollback()   # release the test session's read snapshot so the next write isn't locked out
    taxi = make_txn(db, make_account(db), date(2026, 10, 20), -1_840, "TAXI 22", category="transport")
    client.patch(f"/api/b/ours/transactions/{taxi.id}", json={"reimbursable": True})
    db.rollback()
    dep = make_txn(db, make_account(db), date(2026, 10, 25), 61_200, "ACME CORP EXP")
    client.patch(f"/api/b/ours/transactions/{dep.id}", json={"category": "reimbursement"})
    s = client.get("/api/b/ours/reimburse").json()
    (p,) = s["payers"]
    assert {k: p[k] for k in ("id", "name", "owed_cents", "marked_cents", "repaid_cents", "cleared_cents", "since",
                              "last_repaid_on", "settle_category")} == {
        "id": acme["id"], "name": "Acme", "owed_cents": 1_840, "marked_cents": 63_040, "repaid_cents": 61_200,
        "cleared_cents": 61_200, "since": "2026-10-06", "last_repaid_on": "2026-10-25", "settle_category": "transport"}
    assert [(x["name"], x["count"], x["total_cents"], x["status"]) for x in s["trips"]] == [("Chicago trip", 1, 61_200, "paid")]
    assert [(x["id"], x["status"]) for x in s["singles"]] == [(taxi.id, "waiting")]


def test_settle_counts_the_rest_as_spending_once_and_undoes(client, db):
    acme, rows = setup(client, db)
    client.patch(f"/api/b/ours/transactions/{rows['dinner'].id}", json={"reimbursable": True})
    r = client.post(f"/api/b/ours/reimburse/payers/{acme['id']}/settle", json={"amount_cents": 5_580, "category": "dining"})
    assert r.status_code == 200
    out = r.json()
    assert {k: out[k] for k in ("owed_cents", "settled_cents", "category")} == {
        "owed_cents": 0, "settled_cents": 5_580, "category": "dining"}
    assert len(out["month"]) == 7
    db.rollback()
    (s,) = db.scalars(select(ReimburseSettlement)).all()
    assert (s.amount_cents, s.category, s.reimburser_id) == (5_580, "dining", acme["id"])
    assert client.post(f"/api/b/ours/undo/{out['undo']}").json()["undone"] == 0
    db.rollback()
    assert db.scalars(select(ReimburseSettlement)).all() == [] and rb.owed_map(db) == {acme["id"]: 5_580}


def test_a_second_settle_is_refused_and_makes_no_second_settlement(client, db):
    """Review Focus 3: a double tap, or a second tab."""
    acme, rows = setup(client, db)
    client.patch(f"/api/b/ours/transactions/{rows['dinner'].id}", json={"reimbursable": True})
    body = {"amount_cents": 5_580, "category": "dining"}
    assert client.post(f"/api/b/ours/reimburse/payers/{acme['id']}/settle", json=body).status_code == 200
    r = client.post(f"/api/b/ours/reimburse/payers/{acme['id']}/settle", json=body)
    assert (r.status_code, r.json()) == (422, {"error": "There's nothing to settle."})
    db.rollback()
    assert len(db.scalars(select(ReimburseSettlement)).all()) == 1


def test_settle_refuses_a_stale_amount_and_a_category_that_isnt_spending(client, db):
    acme, rows = setup(client, db)
    client.patch(f"/api/b/ours/transactions/{rows['dinner'].id}", json={"reimbursable": True})
    url = f"/api/b/ours/reimburse/payers/{acme['id']}/settle"
    r = client.post(url, json={"amount_cents": 9_999, "category": "dining"})
    assert (r.status_code, r.json()) == (409, {"error": "The balance changed since. Look again."})
    for bad in ("income", "reimbursement", "uncategorized", "lambos", None):
        assert client.post(url, json={"amount_cents": 5_580, "category": bad}).json() == {
            "error": "Choose a spending category."}, bad
    assert client.post("/api/b/ours/reimburse/payers/999/settle", json={}).status_code == 404


def test_changing_a_trips_payer_moves_its_marked_charges(client, db):
    """Pre-flight F11: the trip's charges follow its payer, so each payer's balance stays right."""
    acme, rows = setup(client, db)
    globex = client.post("/api/b/ours/reimburse/payers", json={"name": "Globex"}).json()
    t = trip(client, reimburser_id=acme["id"])
    client.post(f"/api/b/ours/reimburse/trips/{t['id']}/mark", json={"ids": [rows["hotel"].id]})
    r = client.patch(f"/api/b/ours/reimburse/trips/{t['id']}", json={**TRIP, "reimburser_id": globex["id"]})
    assert r.json()["trip"]["payer"] == "Globex"
    db.rollback()
    assert rb.owed_map(db) == {acme["id"]: 0, globex["id"]: 61_200}
