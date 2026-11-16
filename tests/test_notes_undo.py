"""Removing a note gets an Undo, like every other action (JR: nothing vanishes unseen). DELETE answers a token; POST
/undo/{token} brings the note back as it was: its id when free, its author, words and time, so it returns to its place.
The words and the author's name go to undo_text, never undo_entry (P36), and go when the entry is used or expires."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from steward.db.models import TransactionNote, UndoEntry, UndoText
from steward.services.undo import CHANGED_SINCE, GONE, NO_UNDO
from tests.factories import login, make_account, make_person, make_txn, make_user

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry
D = date(2026, 10, 3)


def setup(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    login(client, "jr")
    t = make_txn(db, make_account(db), D, -8000, "UNION SERVICE CENTER")
    base = f"/api/b/ours/transactions/{t.id}/notes"
    first = client.post(base, json={"body": "Water heater, ask Dana"}).json()   # the fake clock ticks between writes
    second = client.post(base, json={"body": "Paid my half"}).json()
    return t, base, first, second


def notes(client, base):
    return client.get(base).json()["notes"]


def test_remove_answers_a_token_and_undo_brings_the_same_note_back_in_its_place(client, db):
    t, base, first, second = setup(client, db)
    r = client.delete(f"{base}/{first['id']}")
    assert r.status_code == 200 and set(r.json()) == {"undo"}
    assert notes(client, base) == [second]
    db.rollback()                                                   # a fresh read after the client's writes
    entry = db.get(UndoEntry, r.json()["undo"])
    assert entry.action == "note_remove"
    assert "Water heater" not in entry.before + entry.after and "JR" not in entry.before + entry.after
    kept = {(x.field, x.value) for x in db.scalars(select(UndoText).where(UndoText.token == entry.token))}
    assert kept == {("body", "Water heater, ask Dana"), ("author_name", "JR")}
    u = client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    assert u.status_code == 200 and u.json()["undone"] == 1
    assert u.json()["transaction"]["id"] == t.id and u.json()["transaction"]["note_count"] == 2
    assert "Water heater" not in u.text                                # the reply carries a count, not the words
    assert notes(client, base) == [first, second]                    # same id, author, words and time: in its place
    db.rollback()                                                   # a fresh read after the client's writes
    assert db.scalars(select(UndoText).where(UndoText.token == entry.token)).all() == []
    assert (client.post(f"/api/b/ours/undo/{entry.token}").status_code) == 410


def test_undo_takes_a_new_id_when_the_old_one_was_taken_and_keeps_its_place(client, db):
    t, base, first, second = setup(client, db)
    token = client.delete(f"{base}/{second['id']}").json()["undo"]
    third = client.post(base, json={"body": "Third"}).json()        # may reuse the freed id
    assert client.post(f"/api/b/ours/undo/{token}").status_code == 200
    back = notes(client, base)
    assert [n["body"] for n in back] == ["Water heater, ask Dana", "Paid my half", "Third"]
    restored = back[1]
    assert {k: restored[k] for k in ("author_id", "author_name", "body", "created_at")} == \
        {k: second[k] for k in ("author_id", "author_name", "body", "created_at")}
    assert restored["id"] == second["id"] or third["id"] == second["id"]


def test_only_the_person_who_removed_it_can_undo(client, db, ddb, ours):
    t, base, first, _ = setup(client, db)
    token = client.delete(f"{base}/{first['id']}").json()["undo"]
    make_person(ddb, "sam", [(ours.id, "manager")])
    login(client, "sam")
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (404, {"error": NO_UNDO})
    login(client, "jr")
    assert [n["id"] for n in notes(client, base)] != [first["id"]] and len(notes(client, base)) == 1
    assert client.post(f"/api/b/ours/undo/{token}").status_code == 200


def test_undo_is_refused_cleanly_once_the_transaction_is_gone(client, db):
    t, base, first, _ = setup(client, db)
    token = client.delete(f"{base}/{first['id']}").json()["undo"]
    assert client.delete(f"/api/b/ours/transactions/{t.id}").status_code == 204
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (409, {"error": CHANGED_SINCE})
    db.rollback()                                                   # a fresh read after the client's writes
    assert db.scalar(select(TransactionNote)) is None


def test_an_expired_undo_is_refused_and_its_words_are_purged_by_the_next_entry(client, db, fake_clock):
    t, base, first, second = setup(client, db)
    old = client.delete(f"{base}/{first['id']}").json()["undo"]
    fake_clock.advance(timedelta(minutes=16))                       # past UNDO_MINUTES
    r = client.post(f"/api/b/ours/undo/{old}")
    assert (r.status_code, r.json()) == (410, {"error": GONE})
    new = client.delete(f"{base}/{second['id']}").json()["undo"]   # the next entry made sweeps the expired one
    db.rollback()                                                   # a fresh read after the client's writes
    assert db.get(UndoEntry, old) is None
    assert db.scalars(select(UndoText).where(UndoText.token == old)).all() == []
    assert {x.value for x in db.scalars(select(UndoText).where(UndoText.token == new))} == {"Paid my half", "JR"}
