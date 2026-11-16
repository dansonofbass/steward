"""Came from (JR, Oct 31; binding): one quiet line from data that already exists: the SimpleFIN feed (institution
and last sync), the import file (its name, when and by whom), or neither (typed in). "Show all N from this file" lists
the file's rows; a manager can undo the file; a viewer sees the line without Undo."""
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import AccountFeed, ImportBatch, Institution, Source, Transaction
from tests.factories import login, make_account, make_person, make_txn
from tests.import_helpers import import_file

SYNCED = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


def _came(client, tid, slug="ours"):
    r = client.get(f"/api/b/{slug}/transactions/{tid}/came-from")
    assert r.status_code == 200
    return r.json()["came_from"]


def test_a_file_row_names_the_file_when_and_who(client, db, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    card = make_account(db, "Card", type="credit")
    c = import_file(client, "chase-card.csv", card.id).json()
    db.rollback()
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == c["batch_ids"][0]).limit(1))
    came = _came(client, tid)
    assert {k: came[k] for k in ("kind", "label", "batch_id", "by", "count", "undoable")} == {
        "kind": "file", "label": "chase-card.csv", "batch_id": c["batch_ids"][0], "by": "Jr", "count": 5, "undoable": True}
    assert came["at"].startswith("2026-10-30")


def test_a_viewer_sees_the_line_without_undo(client, db, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "jr")
    card = make_account(db, "Card", type="credit")
    bid = import_file(client, "chase-card.csv", card.id).json()["batch_ids"][0]
    db.rollback()
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == bid).limit(1))
    login(client, "val")
    came = _came(client, tid)
    assert (came["kind"], came["undoable"]) == ("file", False)
    assert client.get(f"/api/b/ours/import/batches/{bid}").json()["undoable"] is False


def test_a_simplefin_row_names_its_feeds_institution_and_last_sync(signed_in, db):
    chase = Institution(name="Chase", source=Source.simplefin, last_sync_at=SYNCED)
    db.add(chase)
    db.flush()
    a = make_account(db, "Joint checking", source="simplefin", institution_name="Chase")
    feed = AccountFeed(account_id=a.id, external_id="sfin:acct-1", institution_id=chase.id, name="CHASE CHECKING")
    db.add(feed)
    db.flush()
    t = make_txn(db, a, date(2026, 10, 11), -500, "GREENLEAF MARKET", external_id="sfin-t1")
    t.feed_id = feed.id
    old = make_txn(db, a, date(2026, 9, 1), -100, "OLDER ROW", external_id="sfin-t0")    # synced before feeds
    db.commit()
    assert _came(signed_in, t.id) == {"kind": "simplefin", "label": "Chase", "at": SYNCED.isoformat()}
    assert _came(signed_in, old.id) == {"kind": "simplefin", "label": "Chase", "at": SYNCED.isoformat()}


def test_a_bank_row_whose_account_has_no_institution_still_answers(signed_in, db):
    """A bank id, no feed, and the account's institution gone (a dangling id): the account's name, never a 500."""
    a = make_account(db, "Joint checking", source="simplefin", institution_name="Gone Bank")
    t = make_txn(db, a, date(2026, 9, 1), -100, "OLDER ROW", external_id="sfin-t0")
    db.commit()
    raw = db.get_bind().raw_connection()
    try:
        raw.driver_connection.execute("PRAGMA foreign_keys = OFF")
        raw.driver_connection.execute("UPDATE account SET institution_id = 99999 WHERE id = ?", (a.id,))
        raw.driver_connection.execute("PRAGMA foreign_keys = ON")
    finally:
        raw.close()
    assert _came(signed_in, t.id) == {"kind": "simplefin", "label": "Joint checking", "at": None}


def test_a_row_a_person_typed_reads_typed_in(signed_in, db):
    t = make_txn(db, make_account(db, "Cash box"), date(2026, 10, 1), -2000, "FARMERS MARKET")
    assert _came(signed_in, t.id) == {"kind": "typed", "label": None, "at": None}
    assert signed_in.get("/api/b/ours/transactions/999999/came-from").status_code == 404


def test_a_removed_member_and_a_legacy_file(signed_in, db):
    """Review focus 5: an importer who left the book has no name; a file from before batches still reads."""
    a = make_account(db, "Card", type="credit")
    b = ImportBatch(account_id=a.id, filename="october.csv", format="chase_card", row_count=1, imported_by=99999,
                    imported_at=datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc))
    db.add(b)
    db.flush()
    t = make_txn(db, a, date(2026, 9, 1), -100, "SHOP")
    t.import_batch_id = b.id
    db.commit()
    came = _came(signed_in, t.id)
    assert (came["kind"], came["label"], came["by"], came["count"], came["undoable"]) == ("file", "october.csv", None, 1, True)


def test_show_all_from_this_file_filters_the_list_server_side(client, db, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    card = make_account(db, "Card", type="credit")
    make_txn(db, card, date(2024, 10, 20), -100, "NOT FROM THE FILE")
    bid = import_file(client, "chase-card.csv", card.id).json()["batch_ids"][0]
    rows = client.get("/api/b/ours/transactions", params={"batch": bid, "limit": 500}).json()["transactions"]
    assert len(rows) == 5 and "NOT FROM THE FILE" not in {r["raw_description"] for r in rows}
    one = client.get(f"/api/b/ours/import/batches/{bid}").json()
    assert {k: one[k] for k in ("id", "filename", "rows_in", "undoable", "rolled_back_at")} == \
        {"id": bid, "filename": "chase-card.csv", "rows_in": 5, "undoable": True, "rolled_back_at": None}
    assert client.get("/api/b/ours/import/batches/999999").json() == {"error": "That import doesn't exist."}
