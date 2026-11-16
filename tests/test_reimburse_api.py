"""Reimbursable spec, Marking: the payers (made on first use, renamed, listed), the PATCH's Reimbursable mark and a
repayment's payer, business and reimbursable exclusive both ways, the receipt's facts, Undo, the switch's reach (R2),
household only, and a viewer changes nothing."""
from datetime import date

from sqlalchemy import select

from steward.db.models import BusinessState, UndoEntry
from steward.deps import VIEWER_COPY
from steward.services import reimburse as rb
from tests.factories import login, make_account, make_person, make_txn, make_user

D = date(2026, 10, 3)


def signin(client, db):
    make_user(db)
    login(client, "jr")


def payer(client, name="Acme"):
    r = client.post("/api/b/ours/reimburse/payers", json={"name": name})
    assert r.status_code in (200, 201), r.text
    return r.json()


def patch(client, t, **body):
    return client.patch(f"/api/b/ours/transactions/{t.id}", json=body)


def test_payers_are_made_on_first_use_listed_and_renamed(client, db):
    signin(client, db)
    assert client.get("/api/b/ours/reimburse/payers").json() == {"payers": []}
    r = client.post("/api/b/ours/reimburse/payers", json={"name": " Acme "})
    assert (r.status_code, r.json()["name"]) == (201, "Acme")
    assert client.post("/api/b/ours/reimburse/payers", json={"name": ""}).json() == {
        "error": "Give a name from 1 to 60 characters."}
    g = payer(client, "Globex")
    assert client.patch(f"/api/b/ours/reimburse/payers/{g['id']}", json={"name": "acme"}).json() == {
        "error": "Another payer already has that name."}
    assert client.patch(f"/api/b/ours/reimburse/payers/{g['id']}", json={"name": "Globex Corp"}).json()["name"] == "Globex Corp"
    assert client.patch("/api/b/ours/reimburse/payers/999", json={"name": "X"}).status_code == 404
    assert [p["name"] for p in client.get("/api/b/ours/reimburse/payers").json()["payers"]] == ["Acme", "Globex Corp"]


def test_creating_a_payer_twice_with_other_case_or_spaces_returns_the_first(client, db):
    """Review Focus 5: one employer typed on two devices stays one payer, so no chooser appears."""
    signin(client, db)
    first = client.post("/api/b/ours/reimburse/payers", json={"name": "Acme"})
    again = client.post("/api/b/ours/reimburse/payers", json={"name": "  acme "})
    assert (first.status_code, again.status_code) == (201, 200) and again.json() == first.json()
    assert len(client.get("/api/b/ours/reimburse/payers").json()["payers"]) == 1


def test_marking_a_charge_reimbursable_rides_the_sort_and_answers_the_balance(client, db):
    signin(client, db)
    acme = payer(client)
    t = make_txn(db, make_account(db, "Card", type="credit"), D, -41_218, "HILTON CHICAGO IL")
    r = patch(client, t, category="travel", reimbursable=True)
    assert r.status_code == 200 and r.json()["reimburser_id"] == acme["id"] and r.json()["reimburse_ok"] is True
    res = r.json()["result"]
    assert res["reimburse"] == {"change": "marked", "reimburser_id": acme["id"], "payer": "Acme", "was_cents": 0,
                                "owed_cents": 41_218}
    db.rollback()
    assert (t.category, t.reimburser_id, t.reimburse_source) == ("travel", acme["id"], "manual")
    assert client.post(f"/api/b/ours/undo/{res['undo']}").status_code == 200
    db.rollback()
    assert (t.category, t.reimburser_id, t.reimburse_source) == ("uncategorized", None, "none")


def test_the_switch_alone_answers_a_result_and_not_reimbursed_says_what_it_was(client, db):
    signin(client, db)
    acme = payer(client)
    t = make_txn(db, make_account(db), D, -1_840, "TAXI 22", category="transport")
    on = patch(client, t, reimbursable=True).json()["result"]
    assert (on["category"], on["applied"], on["rule"], on["reimburse"]["owed_cents"]) == ("transport", 0, "none", 1_840)
    off = patch(client, t, reimbursable=False).json()["result"]
    assert off["reimburse"] == {"change": "unmarked", "reimburser_id": acme["id"], "payer": "Acme", "was_cents": 1_840,
                                "owed_cents": 0}
    db.rollback()
    assert (t.reimburser_id, t.reimburse_source) == (None, "manual")
    assert client.post(f"/api/b/ours/undo/{off['undo']}").status_code == 200       # Not reimbursed is undoable
    db.rollback()
    assert t.reimburser_id == acme["id"]
    assert "result" not in patch(client, t, merchant="Taxi").json()


def test_with_two_payers_the_mark_needs_one_chosen(client, db):
    signin(client, db)
    payer(client, "Acme")
    g = payer(client, "Globex")
    t = make_txn(db, make_account(db), D, -1_000, "TAXI 22")
    assert patch(client, t, category="transport", reimbursable=True).json() == {"error": "Choose who pays you back."}
    db.rollback()
    assert t.category == "uncategorized" and db.scalars(select(UndoEntry)).all() == []
    assert patch(client, t, category="transport", reimbursable=True, reimburser_id=g["id"]).json()["reimburser_id"] == g["id"]
    assert patch(client, t, reimbursable=True, reimburser_id=999).json() == {"error": "No such payer."}


def test_with_no_payer_the_mark_and_a_repayment_are_refused_in_plain_words(client, db):
    signin(client, db)
    t = make_txn(db, make_account(db), D, -1_000, "TAXI 22")
    assert patch(client, t, reimbursable=True).json() == {"error": "Say who pays you back first."}
    dep = make_txn(db, make_account(db), D, 50_000, "ACME CORP EXP")
    assert patch(client, dep, category="reimbursement").json() == {"error": "Say who pays you back first."}


def test_business_and_reimbursable_are_exclusive_both_ways(client, db):
    signin(client, db)
    acme = payer(client)
    t = make_txn(db, make_account(db), D, -40_000, "HILTON", business_pct=100)
    assert patch(client, t, reimbursable=True, is_business=True).json() == {
        "error": "A charge is either business or reimbursable."}
    row = patch(client, t, reimbursable=True).json()
    assert (row["business_pct"], row["reimburser_id"]) == (0, acme["id"])
    row = patch(client, t, is_business=True).json()
    assert (row["business_pct"], row["reimburser_id"]) == (100, None)
    patch(client, t, reimbursable=True)
    row = client.put(f"/api/b/ours/business/transactions/{t.id}", json={"pct": 40}).json()
    assert (row["business_pct"], row["reimburser_id"]) == (40, None)


def test_review_no_longer_asks_whether_a_reimbursable_charge_is_business(client, db):
    signin(client, db)
    payer(client)
    db.add(BusinessState(key="type", value="sole_prop"))
    db.commit()
    t = make_txn(db, make_account(db), D, -40_000, "COWORK SPACE", category="business_expense", business_hint=90)
    assert [r["id"] for r in client.get("/api/b/ours/review").json()["business"]] == [t.id]
    patch(client, t, reimbursable=True)
    assert client.get("/api/b/ours/review").json()["business"] == []


def test_a_business_rule_leaves_a_reimbursable_charge_alone(client, db):
    signin(client, db)
    acme = payer(client)
    card = make_account(db, "Card", type="credit")
    a = make_txn(db, card, D, -4_000, "COWORK SPACE 1")
    b = make_txn(db, card, date(2026, 9, 3), -4_000, "COWORK SPACE 2")
    patch(client, b, reimbursable=True)
    r = client.post("/api/b/ours/business/rules", json={"kind": "merchant", "transaction_id": a.id, "pct": 100, "line": None})
    assert r.json()["also_tagged"] == 1                         # a itself; b is reimbursable
    db.rollback()
    assert (b.business_pct, b.reimburser_id) == (0, acme["id"])


def test_rows_say_where_the_switch_is_offered_and_a_refund_lowers_the_balance(client, db):
    """R2."""
    signin(client, db)
    payer(client)
    card = make_account(db, "Card", type="credit")
    hotel = make_txn(db, card, D, -40_000, "HILTON CHICAGO IL 0042", category="travel")
    patch(client, hotel, reimbursable=True)
    db.rollback()                                   # end the read snapshot before the next insert
    refund = make_txn(db, card, D, 2_000, "HILTON CHICAGO IL 0043")
    other = make_txn(db, card, D, 2_000, "MYSTERY CREDIT")
    rows = {r["id"]: r for r in client.get("/api/b/ours/transactions").json()["transactions"]}
    assert [rows[t.id]["reimburse_ok"] for t in (hotel, refund, other)] == [True, True, False]
    queue = {r["id"]: r for r in client.get("/api/b/ours/review").json()["uncategorized"]}
    assert (queue[refund.id]["reimburse_ok"], queue[other.id]["reimburse_ok"]) == (True, False)
    res = patch(client, refund, category="travel", reimbursable=True).json()["result"]["reimburse"]
    assert (res["was_cents"], res["owed_cents"]) == (40_000, 38_000)
    assert patch(client, other, reimbursable=True).json() == {
        "error": "Only money out, or a refund from a merchant you've marked reimbursable, can be reimbursable."}


def test_a_repayment_takes_the_only_payer_and_says_what_is_left(client, db):
    signin(client, db)
    acme = payer(client)
    t = make_txn(db, make_account(db, "Card", type="credit"), D, -40_000, "HILTON")
    patch(client, t, reimbursable=True)
    db.rollback()
    dep = make_txn(db, make_account(db), D, 33_965, "ACME CORP EXP")
    res = patch(client, dep, category="reimbursement").json()
    assert res["reimburser_id"] == acme["id"] and "reimburse_ok" in res
    assert res["result"]["reimburse"] == {"change": "repaid", "reimburser_id": acme["id"], "payer": "Acme",
                                          "was_cents": 40_000, "owed_cents": 6_035}


def test_sorting_a_reimbursable_row_as_a_transfer_takes_the_mark_off(client, db):
    """Review Focus 1."""
    signin(client, db)
    acme = payer(client)
    t = make_txn(db, make_account(db), D, -40_000, "CHASE EPAY 0042", category="travel")
    patch(client, t, reimbursable=True)
    res = patch(client, t, category="transfer").json()
    assert res["reimburser_id"] is None and res["result"]["reimburse"] is None
    db.rollback()
    assert rb.owed_map(db) == {acme["id"]: 0}


def test_moving_a_repayment_to_income_clears_its_payer_and_the_balance_goes_back(client, db):
    """Review Focus 2."""
    signin(client, db)
    acme = payer(client)
    t = make_txn(db, make_account(db, "Card", type="credit"), D, -40_000, "HILTON")
    patch(client, t, reimbursable=True)
    db.rollback()
    dep = make_txn(db, make_account(db), D, 30_000, "ACME CORP EXP")
    assert patch(client, dep, category="reimbursement").json()["result"]["reimburse"]["owed_cents"] == 10_000
    assert patch(client, dep, category="income").json()["reimburser_id"] is None
    db.rollback()
    assert rb.owed_map(db) == {acme["id"]: 40_000}


def test_parent_books_refuse_reimbursable_and_have_no_payers(margaret, mdb, client):
    login(client, "jr")
    t = make_txn(mdb, make_account(mdb), D, -100, "TAXI")
    for body in ({"reimbursable": True}, {"category": "reimbursement"}, {"reimburser_id": 1}):
        r = client.patch(f"/api/b/margaret-ellis/transactions/{t.id}", json=body)
        assert (r.status_code, r.json()) == (422, {"error": "Reimbursements are for household books."}), body
    assert client.get("/api/b/margaret-ellis/reimburse/payers").status_code == 404
    assert "reimburse_ok" not in client.get("/api/b/margaret-ellis/transactions").json()["transactions"][0]


# Every write the /reimburse router has. Tasks 6 and 8 add theirs here.
WRITES = [("post", "/reimburse/payers", {"name": "Acme"}), ("patch", "/reimburse/payers/1", {"name": "A"}),
          ("post", "/reimburse/rules", {"transaction_id": 1}),
          ("post", "/reimburse/trips", {"start": "2026-10-06", "end": "2026-10-09", "name": "X"}),
          ("patch", "/reimburse/trips/1", {}), ("post", "/reimburse/trips/1/mark", {"ids": []}),
          ("post", "/reimburse/payers/1/settle", {"amount_cents": 1, "category": "travel"})]


def test_a_viewer_changes_nothing(client, db, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    for method, path, body in WRITES:
        r = getattr(client, method)(f"/api/b/ours{path}", json=body)
        assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY}), path
