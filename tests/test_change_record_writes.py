from steward import clock
import json
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from steward.db.models import ChangeRecord, SimplefinLink
from tests.factories import login, make_account, make_txn

S = Path(__file__).parent / "samples"
BOOK = "/api/b/margaret-ellis"


def _changes(client, **q):
    return client.get(f"{BOOK}/changes", params=q).json()["changes"]


def test_a_transaction_edit_in_a_parent_book_is_recorded(frozen, margaret, mdb, client):
    t = make_txn(mdb, make_account(mdb, "Joint checking"), date(2026, 10, 3), -8617, "STATER BROS 123")
    login(client, "jr")
    assert client.patch(f"{BOOK}/transactions/{t.id}", json={"category": "groceries"}).status_code == 200
    row = _changes(client, kind="transactions")[0]
    assert (row["who"], row["text"]) == ("Jr", "edited a transaction")
    assert row["diffs"] == [{"label": "Category", "before": "Uncategorized", "after": "Groceries"}]
    assert row["lines"] == ["STATER BROS 123 · −$86.17 · Oct 3"]


def test_household_books_record_nothing(frozen, margaret, db, client):
    t = make_txn(db, make_account(db, "Checking"), date(2026, 10, 3), -100, "X")
    login(client, "jr")
    assert client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "groceries"}).status_code == 200
    db.rollback()
    assert db.scalar(select(func.count()).select_from(ChangeRecord)) == 0


def test_removing_reviewing_and_keeping_both_are_recorded(frozen, margaret, mdb, client):
    a = make_account(mdb, "Joint checking")
    t1 = make_txn(mdb, a, date(2026, 10, 3), -500, "BEAN AND LEAF")
    t2 = make_txn(mdb, a, date(2026, 10, 4), -500, "BEAN AND LEAF")
    t3 = make_txn(mdb, a, date(2026, 10, 5), -900, "HARDWARE 12")
    login(client, "jr")
    assert client.post(f"{BOOK}/review/duplicates/keep", json={"a": t1.id, "b": t2.id}).status_code == 204
    assert client.post(f"{BOOK}/review/{t3.id}/ignore").status_code == 200
    assert client.post(f"{BOOK}/review/{t3.id}/snooze").status_code == 200
    assert client.delete(f"{BOOK}/transactions/{t3.id}").status_code == 204
    texts = [c["text"] for c in _changes(client, kind="transactions")]
    assert texts == ["removed a transaction", "marked a transaction reviewed", "kept two transactions that look alike"]


def test_an_import_and_its_undo_are_recorded(frozen, margaret, mdb, client):
    from tests.import_helpers import import_file
    a = make_account(mdb, "Joint checking")
    login(client, "jr")
    r = import_file(client, "chase_checking.csv", a.id, raw=(S / "chase_checking.csv").read_bytes(), slug="margaret-ellis")
    assert r.status_code == 201
    assert client.post(f"{BOOK}/import/batches/{r.json()['batch_ids'][0]}/rollback").status_code == 200
    rows = _changes(client, kind="imports")
    assert [c["text"] for c in rows] == ["undid the import of chase_checking.csv", "imported chase_checking.csv"]
    assert rows[1]["lines"] == ["3 transactions into Joint checking"]


def test_disconnecting_the_bank_feed_is_recorded(frozen, margaret, mdb, client):
    mdb.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=clock.now()))
    mdb.commit()
    login(client, "jr")
    assert client.delete(f"{BOOK}/simplefin").status_code == 204
    assert [c["text"] for c in _changes(client, kind="bank_feed")] == ["disconnected the bank feed"]


def test_a_parent_book_has_no_accounts_routes_for_writing(margaret, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/accounts", json={"name": "x", "type": "checking", "owner": "margaret", "balance_cents": 0})
    assert (r.status_code, r.json()) == (404, {"error": "This book doesn't have that."})
    assert client.get(f"{BOOK}/accounts").status_code == 200


def test_removing_a_transaction_refreshes_the_suggestions(frozen, margaret, mdb, client):
    import json
    from datetime import datetime, timezone
    from steward.db.models import Suggestion
    a = make_account(mdb, "Joint checking")
    t = make_txn(mdb, a, date(2026, 10, 5), 150_000, "ACME PAYROLL")
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    mdb.add(Suggestion(kind="income", payer_key="acme payroll", payer_name="Acme Payroll", status="open",
                       details=json.dumps({"signal": "deposits", "guess": None, "hint_word": None, "amount_cents": 150_000,
                                           "frequency": "monthly", "usual_day": 5, "account_id": a.id,
                                           "related_item_id": None, "match_text": "ACME PAYROLL"}),
                       evidence=json.dumps({"txn_ids": [t.id], "count": 1, "form_ids": []}), created_at=now, updated_at=now))
    mdb.commit()
    login(client, "jr")
    assert client.delete(f"{BOOK}/transactions/{t.id}").status_code == 204
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(Suggestion)) == 0


def test_a_spread_in_a_parent_book_is_recorded(frozen, margaret, mdb, client):
    login(client, "jr")
    a = make_account(mdb)
    t = make_txn(mdb, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    make_txn(mdb, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    client.patch(f"{BOOK}/transactions/{t.id}", json={"category": "home"})
    assert client.post(f"{BOOK}/transactions/{t.id}/spread").json() == {"changed": 1}
    mdb.rollback()
    rows = mdb.scalars(select(ChangeRecord).where(ChangeRecord.action == "txn.spread")).all()
    assert len(rows) == 1 and json.loads(rows[0].after)["count"] == 1


def test_a_note_in_a_parent_book_is_recorded_without_its_words(frozen, margaret, mdb, client):
    login(client, "jr")
    a = make_account(mdb)
    t = make_txn(mdb, a, date(2026, 10, 3), -8000, "OAKHAVEN PHARMACY")
    nid = client.post(f"{BOOK}/transactions/{t.id}/notes", json={"body": "Dr. Alvarez said twice a day"}).json()["id"]
    r = client.delete(f"{BOOK}/transactions/{t.id}/notes/{nid}")
    assert r.status_code == 200 and set(r.json()) == {"undo"}       # its Undo token, never the words
    mdb.rollback()   # end the read snapshot so the requests' writes are seen
    rows = mdb.scalars(select(ChangeRecord).where(ChangeRecord.action.like("txn.note%")).order_by(ChangeRecord.id)).all()
    assert [r.action for r in rows] == ["txn.note_add", "txn.note_remove"]
    assert all("Alvarez" not in (r.after or "") and r.note is None for r in rows)


def test_a_sort_applied_to_matching_in_a_parent_book_records_the_edit_and_the_spread(frozen, margaret, mdb, client):
    login(client, "jr")
    a = make_account(mdb)
    t = make_txn(mdb, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    make_txn(mdb, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    r = client.patch(f"{BOOK}/transactions/{t.id}", json={"category": "home", "apply_to_matching": True})
    assert r.json()["result"]["applied"] == 1
    mdb.rollback()
    assert sorted(c.action for c in mdb.scalars(select(ChangeRecord))) == ["txn.edit", "txn.spread"]
