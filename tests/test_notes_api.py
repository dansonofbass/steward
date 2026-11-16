"""Transaction notes (phase 12 decision 18): add, list newest last, delete your own only, viewers read, search finds
note text, a note goes with its transaction, and the row carries a count."""
from datetime import date

from sqlalchemy import select

from steward.db.models import TransactionNote
from steward.deps import VIEWER_COPY
from tests.factories import login, make_account, make_person, make_txn, make_user


def jr(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    login(client, "jr")


def test_add_list_and_count(frozen, client, db):
    jr(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    r = client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "  The water heater, half paid by Sam  "})
    assert r.status_code == 201
    first = r.json()
    assert first == {"id": first["id"], "author_id": first["author_id"], "author_name": "JR",
                     "body": "The water heater, half paid by Sam", "created_at": "2026-10-13T19:00:00+00:00"}
    client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "Second"})
    notes = client.get(f"/api/b/ours/transactions/{t.id}/notes").json()["notes"]
    assert [n["body"] for n in notes] == ["The water heater, half paid by Sam", "Second"]
    row = client.get("/api/b/ours/transactions?q=UNION").json()["transactions"][0]
    assert row["note_count"] == 2
    assert client.get("/api/b/ours/transactions/99999/notes").status_code == 404


def test_a_note_is_1_to_1000_characters_after_trimming(client, db):
    """Review Focus 5."""
    jr(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    for body in ({"body": "   "}, {"body": ""}, {"body": "x" * 1001}, {"body": 3}, {}):
        r = client.post(f"/api/b/ours/transactions/{t.id}/notes", json=body)
        assert (r.status_code, r.json()) == (422, {"error": "A note is 1 to 1,000 characters."}), body
    assert client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": " " + "y" * 1000 + " "}).status_code == 201


def test_only_the_author_deletes_a_note(client, db, ddb, ours):
    jr(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    mine = client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "Mine"}).json()["id"]
    make_person(ddb, "sam", [(ours.id, "manager")])
    login(client, "sam")
    theirs = client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "Sam's"}).json()["id"]
    r = client.delete(f"/api/b/ours/transactions/{t.id}/notes/{mine}")
    assert (r.status_code, r.json()) == (403, {"error": "Only the person who wrote a note can remove it."})
    assert client.delete(f"/api/b/ours/transactions/{t.id}/notes/{theirs}").status_code == 200   # with its Undo token
    assert client.delete(f"/api/b/ours/transactions/{t.id}/notes/{theirs}").status_code == 404
    login(client, "jr")
    assert client.delete(f"/api/b/ours/transactions/{t.id}/notes/{mine}").status_code == 200
    assert client.get(f"/api/b/ours/transactions/{t.id}/notes").json() == {"notes": []}


def test_a_viewer_reads_notes_and_cannot_add_one(client, db, ddb, ours):
    """Review Focus 5."""
    jr(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    nid = client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "Mine"}).json()["id"]
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert [n["body"] for n in client.get(f"/api/b/ours/transactions/{t.id}/notes").json()["notes"]] == ["Mine"]
    r = client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "Viewer"})
    assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY})
    assert client.delete(f"/api/b/ours/transactions/{t.id}/notes/{nid}").status_code == 403


def test_search_finds_note_text_and_a_removed_transaction_takes_its_notes(client, db):
    jr(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    other = make_txn(db, a, date(2026, 10, 3), -900, "POS PURCHASE")
    client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "Water heater"})
    found = client.get("/api/b/ours/transactions?q=heater").json()["transactions"]
    assert [x["id"] for x in found] == [t.id]
    assert [x["id"] for x in client.get("/api/b/ours/transactions?q=POS").json()["transactions"]] == [other.id]
    assert client.delete(f"/api/b/ours/transactions/{t.id}").status_code == 204
    db.expire_all()
    assert db.scalar(select(TransactionNote)) is None


def test_a_patch_keeps_the_note_count_on_the_row(client, db):
    jr(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    client.post(f"/api/b/ours/transactions/{t.id}/notes", json={"body": "One"})
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"})
    assert r.status_code == 200
    assert r.json()["note_count"] == 1


def test_search_treats_percent_and_underscore_as_plain_characters(client, db):
    jr(client, db)
    a = make_account(db)
    coffee = make_txn(db, a, date(2026, 10, 3), -400, "COFFEE")
    client.post(f"/api/b/ours/transactions/{coffee.id}/notes", json={"body": "lunch"})
    for q in ("%", "_"):
        assert client.get("/api/b/ours/transactions", params={"q": q}).json()["transactions"] == []
    db.rollback()
    half = make_txn(db, a, date(2026, 10, 4), -500, "SALE 50% OFF")
    assert [x["id"] for x in client.get("/api/b/ours/transactions", params={"q": "50%"}).json()["transactions"]] == [half.id]


def test_a_note_is_reached_only_through_its_own_transaction(client, db):
    jr(client, db)
    a = make_account(db)
    t1 = make_txn(db, a, date(2026, 10, 3), -400, "ONE")
    t2 = make_txn(db, a, date(2026, 10, 4), -500, "TWO")
    nid = client.post(f"/api/b/ours/transactions/{t1.id}/notes", json={"body": "Mine"}).json()["id"]
    r = client.delete(f"/api/b/ours/transactions/{t2.id}/notes/{nid}")
    assert (r.status_code, r.json()) == (404, {"error": "No such note."})
    assert [n["id"] for n in client.get(f"/api/b/ours/transactions/{t1.id}/notes").json()["notes"]] == [nid]


def test_a_transaction_id_from_another_book_is_not_found(margaret, client, db):
    login(client, "jr")
    t = make_txn(db, make_account(db), date(2026, 10, 3), -400, "ONE")
    other = "/api/b/margaret-ellis"
    assert client.get(f"{other}/transactions/{t.id}/notes").status_code == 404
    assert client.post(f"{other}/transactions/{t.id}/notes", json={"body": "x"}).status_code == 404
