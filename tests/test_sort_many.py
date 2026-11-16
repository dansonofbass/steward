"""Bulk sort (profile spec, Sorting several rows at once; P29): POST /transactions/sort gives up to 200 rows one
category in one action, as a person's correction, with no merchant rule, no spread and one Undo for all of them."""
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.api.transactions import TOO_MANY
from steward.db.models import CategorySource, ChangeRecord, MerchantRule, ReimburseRule, Reimburser, Transaction, UndoEntry
from steward.deps import VIEWER_COPY
from steward.services import reimburse as rb
from steward.services.undo import CHANGED_SINCE
from tests.factories import login, make_account, make_person, make_txn, make_user

D = date(2026, 10, 3)
URL = "/api/b/ours/transactions/sort"


def _signed_in(client, db):
    make_user(db)
    login(client, "jr")


def test_sorts_every_row_as_a_correction_and_makes_no_rule(client, db):
    _signed_in(client, db)
    a = make_account(db)
    rows = [make_txn(db, a, D, -100 * (i + 1), f"SQ *STALL {i}") for i in range(3)]
    guessed = make_txn(db, a, D, -900, "ODD SHOP", category="shopping", category_source=CategorySource.model)
    guessed.guess_category, guessed.guess_pct = "gifts", 60
    db.commit()
    ids = [t.id for t in rows] + [guessed.id]
    r = client.post(URL, json={"ids": ids, "category": "gifts"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["sorted"], body["ids"], body["skipped"], body["category"]) == (4, ids, [], "gifts")
    assert isinstance(body["undo"], str)
    db.rollback()
    for i in ids:
        t = db.get(Transaction, i)
        assert (t.category, t.category_source, t.guess_category) == ("gifts", CategorySource.correction, None)
        assert t.reviewed_at is not None
    assert db.scalars(select(MerchantRule)).all() == []          # P29: the rows share no text
    assert [e.action for e in db.scalars(select(UndoEntry))] == ["sort_many"]


def test_one_undo_restores_every_row(client, db):
    _signed_in(client, db)
    a = make_account(db)
    plain = make_txn(db, a, D, -500, "SQ *A")
    model = make_txn(db, a, D, -600, "SQ *B", category="dining", category_source=CategorySource.model)
    token = client.post(URL, json={"ids": [plain.id, model.id], "category": "travel"}).json()["undo"]
    u = client.post(f"/api/b/ours/undo/{token}")
    assert u.status_code == 200 and u.json()["undone"] == 2
    db.rollback()
    assert (plain.category, plain.category_source, plain.reviewed_at) == ("uncategorized", CategorySource.none, None)
    assert (model.category, model.category_source, model.reviewed_at) == ("dining", CategorySource.model, None)


def test_a_transfer_pairs_and_undo_unpairs(client, db):
    _signed_in(client, db)
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE EPAY 0042")
    back = make_txn(db, card, date(2026, 10, 7), 40000, "PAYMENT RECEIVED")
    other = make_txn(db, chk, D, -1234, "MOVE TO SAVINGS")
    r = client.post(URL, json={"ids": [out.id, other.id], "category": "transfer"})
    assert r.json()["sorted"] == 2
    db.rollback()
    assert (out.is_transfer, out.transfer_peer_id, back.transfer_peer_id, back.category) == (True, back.id, out.id, "transfer")
    assert (other.is_transfer, other.transfer_peer_id) == (True, None)
    client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    db.rollback()
    assert (out.is_transfer, out.transfer_peer_id, out.category) == (False, None, "uncategorized")
    assert (back.is_transfer, back.transfer_peer_id, back.category) == (False, None, "uncategorized")
    assert other.is_transfer is False


def test_two_selected_sides_of_one_transfer_pair_with_each_other(client, db):
    _signed_in(client, db)
    out = make_txn(db, make_account(db, "Checking"), D, -5000, "TO SAVINGS")
    into = make_txn(db, make_account(db, "Savings", type="savings", institution_name="Other"), D, 5000, "FROM CHECKING")
    assert client.post(URL, json={"ids": [out.id, into.id], "category": "transfer"}).json()["sorted"] == 2
    db.rollback()
    assert (out.transfer_peer_id, into.transfer_peer_id) == (into.id, out.id)
    assert {out.category_source, into.category_source} == {CategorySource.correction}


def test_sorting_a_paired_transfer_as_spending_unpairs_it_as_the_single_sort_does(client, db):
    _signed_in(client, db)
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, D, -7000, "XFER OUT", category="transfer", is_transfer=True, category_source=CategorySource.rule)
    into = make_txn(db, sav, D, 7000, "XFER IN", category="transfer", is_transfer=True, category_source=CategorySource.rule)
    out.transfer_peer_id, into.transfer_peer_id = into.id, out.id
    db.commit()
    r = client.post(URL, json={"ids": [out.id], "category": "home"})
    db.rollback()
    assert (out.category, out.is_transfer, out.transfer_peer_id) == ("home", False, None)
    assert (into.category, into.is_transfer, into.transfer_peer_id) == ("uncategorized", False, None)   # back to Review
    client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    db.rollback()
    assert (out.transfer_peer_id, into.transfer_peer_id, into.category) == (into.id, out.id, "transfer")


def test_more_than_200_is_refused_in_plain_words_and_changes_nothing(client, db):
    _signed_in(client, db)
    a = make_account(db)
    t = make_txn(db, a, D, -100, "SQ *A")
    r = client.post(URL, json={"ids": [t.id] + list(range(10_000, 10_200)), "category": "gifts"})
    assert (r.status_code, r.json()) == (422, {"error": TOO_MANY})
    assert TOO_MANY == "Sort up to 200 at a time."
    db.rollback()
    assert t.category == "uncategorized"


def test_exactly_200_is_one_action(client, db):
    _signed_in(client, db)
    a = make_account(db)
    rows = [make_txn(db, a, D, -100 - i, f"ROW {i}") for i in range(200)]
    r = client.post(URL, json={"ids": [t.id for t in rows], "category": "kids"})
    assert r.status_code == 200 and r.json()["sorted"] == 200
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").json()["undone"] == 200


def test_an_unknown_id_refuses_the_whole_request(client, db):
    _signed_in(client, db)
    t = make_txn(db, make_account(db), D, -100, "SQ *A")
    r = client.post(URL, json={"ids": [t.id, 99_999], "category": "gifts"})
    assert (r.status_code, r.json()) == (404, {"error": "No such transaction."})
    db.rollback()
    assert t.category == "uncategorized" and db.scalars(select(UndoEntry)).all() == []


def test_refuses_no_ids_an_unknown_category_and_not_sure_yet(client, db):
    _signed_in(client, db)
    t = make_txn(db, make_account(db), D, -100, "SQ *A")
    assert client.post(URL, json={"ids": [], "category": "gifts"}).json() == {"error": "Choose what to sort."}
    for c in ("nope", "uncategorized"):
        r = client.post(URL, json={"ids": [t.id], "category": c})
        assert (r.status_code, r.json()) == (422, {"error": "That isn't one of the categories."})


def test_a_repeated_id_is_sorted_once(client, db):
    _signed_in(client, db)
    t = make_txn(db, make_account(db), D, -100, "SQ *A")
    assert client.post(URL, json={"ids": [t.id, t.id], "category": "gifts"}).json()["sorted"] == 1


def test_a_viewer_gets_403_and_nothing_changes(client, db, ddb, ours):
    t = make_txn(db, make_account(db), D, -100, "SQ *A")
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    r = client.post(URL, json={"ids": [t.id], "category": "gifts"})
    assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY})
    db.rollback()
    assert t.category == "uncategorized"


def test_a_repayment_with_no_payer_skips_every_row_with_the_reason(client, db):
    _signed_in(client, db)
    a = make_account(db)
    rows = [make_txn(db, a, D, 5000, "ACME PAYROLL"), make_txn(db, a, D, 6000, "ACME EXPENSES")]
    r = client.post(URL, json={"ids": [t.id for t in rows], "category": "reimbursement"})
    assert r.status_code == 200
    assert r.json()["sorted"] == 0 and r.json()["undo"] is None
    assert r.json()["skipped"] == [{"id": t.id, "reason": rb.NO_PAYER} for t in rows]
    db.rollback()
    assert all(t.category == "uncategorized" for t in rows)


def test_a_repayment_takes_the_only_payer_and_remembers_no_description(client, db):
    _signed_in(client, db)
    a = make_account(db)
    acme = Reimburser(name="Acme", created_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    db.add(acme)
    db.commit()
    rows = [make_txn(db, a, D, 5000, "ACME PAYROLL"), make_txn(db, a, D, 6000, "ACME EXPENSES")]
    r = client.post(URL, json={"ids": [t.id for t in rows], "category": "reimbursement"})
    assert r.json()["sorted"] == 2
    db.rollback()
    assert [t.reimburser_id for t in rows] == [acme.id, acme.id]
    assert db.scalars(select(ReimburseRule)).all() == []
    client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    db.rollback()
    assert [t.reimburser_id for t in rows] == [None, None]


def test_a_reimbursable_charge_sorted_as_transfer_loses_its_payer(client, db):
    _signed_in(client, db)
    acme = Reimburser(name="Acme", created_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    db.add(acme)
    db.commit()
    t = make_txn(db, make_account(db), D, -5000, "HOTEL")
    t.reimburser_id = acme.id
    db.commit()
    client.post(URL, json={"ids": [t.id], "category": "transfer"})
    db.rollback()
    assert (t.category, t.reimburser_id) == ("transfer", None)


def test_a_parent_book_records_one_entry_with_the_count(margaret, mdb, client):
    login(client, "jr")
    a = make_account(mdb)
    rows = [make_txn(mdb, a, D, -8000, "OAKHAVEN PHARMACY"), make_txn(mdb, a, D, -900, "CVS 0012")]
    r = client.post("/api/b/margaret-ellis/transactions/sort", json={"ids": [t.id for t in rows], "category": "health"})
    assert r.status_code == 200 and r.json()["sorted"] == 2
    mdb.rollback()
    assert [x.action for x in mdb.scalars(select(ChangeRecord))] == ["txn.sort_many"]
    row = client.get("/api/b/margaret-ellis/changes", params={"kind": "transactions"}).json()["changes"][0]
    assert row["text"] == "sorted 2 transactions as Health"
    assert client.post(f"/api/b/margaret-ellis/undo/{r.json()['undo']}").status_code == 200
    row = client.get("/api/b/margaret-ellis/changes", params={"kind": "transactions"}).json()["changes"][0]
    assert row["text"] == "undid a change to 2 transactions"


def test_a_parent_book_has_no_repayments(margaret, mdb, client):
    login(client, "jr")
    t = make_txn(mdb, make_account(mdb), D, 8000, "REFUND")
    r = client.post("/api/b/margaret-ellis/transactions/sort", json={"ids": [t.id], "category": "reimbursement"})
    assert (r.status_code, r.json()) == (422, {"error": rb.HOUSEHOLD_ONLY})


def _fields(t: Transaction) -> tuple:
    return (t.category, t.category_source, t.is_transfer, t.transfer_peer_id, t.reviewed_at)


def test_both_sides_of_a_pair_sorted_as_spending_unpair_and_undo_restores_both_exactly(client, db):
    _signed_in(client, db)
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, D, -7000, "XFER OUT", category="transfer", is_transfer=True, category_source=CategorySource.rule)
    into = make_txn(db, sav, D, 7000, "XFER IN", category="transfer", is_transfer=True, category_source=CategorySource.rule)
    out.transfer_peer_id, into.transfer_peer_id = into.id, out.id
    db.commit()
    was = [_fields(out), _fields(into)]
    r = client.post(URL, json={"ids": [out.id, into.id], "category": "home"})
    assert r.json()["sorted"] == 2
    db.rollback()
    for t in (out, into):
        assert (t.category, t.category_source, t.is_transfer, t.transfer_peer_id) == ("home", CategorySource.correction, False, None)
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").json()["undone"] == 2
    db.rollback()
    assert [_fields(out), _fields(into)] == was


def test_undo_is_refused_with_409_when_one_row_changed_since(client, db):
    _signed_in(client, db)
    a = make_account(db)
    rows = [make_txn(db, a, D, -100, "SQ *A"), make_txn(db, a, D, -200, "SQ *B")]
    token = client.post(URL, json={"ids": [t.id for t in rows], "category": "gifts"}).json()["undo"]
    db.rollback()
    rows[1].category = "dining"                       # edited since the bulk sort
    db.commit()
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (409, {"error": CHANGED_SINCE})
    db.rollback()
    assert [t.category for t in rows] == ["gifts", "dining"]           # nothing was put back
    assert db.get(UndoEntry, token).used_at is None


def test_an_id_too_large_for_sqlite_is_a_plain_404(client, db):
    _signed_in(client, db)
    t = make_txn(db, make_account(db), D, -100, "SQ *A")
    for bad_id in (2**70, 2**63, 0, -5):
        r = client.post(URL, json={"ids": [t.id, bad_id], "category": "gifts"})
        assert (r.status_code, r.json()) == (404, {"error": "No such transaction."}), bad_id
    db.rollback()
    assert t.category == "uncategorized"
