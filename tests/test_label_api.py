"""GET and PUT /transactions/{tid}/label (P31-P41): a note and a name on the row, the rows like it (narrowed to the
same amount for a generic payee) and future ones, in one action with one Undo; plain refusals; household only."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from steward.db.models import CategorySource, MerchantRule, Transaction, TransactionNote, UndoEntry
from steward.deps import VIEWER_COPY
from tests.factories import login, make_account, make_person, make_txn

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry


def paypal(db):
    chk = make_account(db, "Checking")
    rows = [make_txn(db, chk, date(2026, 10, d), cents, f"PAYPAL *{tail}", merchant="PayPal")
            for d, cents, tail in ((1, -1399, "DISNEYPLUS"), (2, -1399, "DISNEYPLUS"), (3, -1399, "DISNEY"), (4, -999, "EBAY"))]
    k401 = make_account(db, "401(k)", type="k401", owner="jr")
    make_txn(db, k401, date(2026, 10, 5), -1399, "PAYPAL *X", merchant="PayPal")            # an investment account: never reached
    boxes = [make_txn(db, chk, date(2026, 10, d), -799, "STREAMBOX", merchant="StreamBox", category=c)
             for d, c in ((6, "subscriptions"), (7, "uncategorized"))]
    return rows, boxes


def put(client, t, body):
    return client.put(f"/api/b/ours/transactions/{t.id}/label", json=body)


def fresh(db):
    db.rollback()
    db.expire_all()


def test_get_label_says_how_far_also_reaches(frozen, signed_in, db):
    rows, boxes = paypal(db)
    assert signed_in.get(f"/api/b/ours/transactions/{rows[0].id}/label").json() == {
        "nickname": None, "reach": {"others": 2, "payee": "PayPal", "amount_cents": -1399, "generic": True}, "rule": None}
    assert signed_in.get(f"/api/b/ours/transactions/{boxes[0].id}/label").json()["reach"] == {
        "others": 1, "payee": "StreamBox", "amount_cents": None, "generic": False}
    assert signed_in.get("/api/b/ours/transactions/99999/label").status_code == 404


def test_note_and_name_also_and_future_in_one_action_with_one_undo(frozen, signed_in, db):
    rows, _ = paypal(db)
    r = put(signed_in, rows[0], {"note": "Disney+ subscription", "nickname": "Disney+", "also": True, "future": True})
    assert r.status_code == 200
    body = r.json()
    assert (body["rows"], body["notes_added"], body["named"]) == (3, 3, 3) and body["rule_id"] and body["undo"]
    fresh(db)
    assert [db.get(Transaction, t.id).nickname for t in rows] == ["Disney+", "Disney+", "Disney+", None]   # $9.99 untouched
    notes = db.scalars(select(TransactionNote)).all()
    assert sorted(n.transaction_id for n in notes) == sorted(t.id for t in rows[:3])
    assert {(n.author_name, n.body) for n in notes} == {("JR", "Disney+ subscription")}
    rule = db.get(MerchantRule, body["rule_id"])
    assert (rule.pattern, rule.amount_cents, rule.category, rule.nickname, rule.note, rule.note_by_name, rule.source) == (
        "PAYPAL", -1399, None, "Disney+", "Disney+ subscription", "JR", CategorySource.correction)
    assert signed_in.get(f"/api/b/ours/transactions/{rows[1].id}/label").json()["rule"] == {
        "id": rule.id, "nickname": "Disney+", "note": "Disney+ subscription", "has_category": False}
    assert signed_in.post(f"/api/b/ours/undo/{body['undo']}").status_code == 200
    fresh(db)
    assert all(t.nickname is None for t in db.scalars(select(Transaction)))
    assert db.scalars(select(TransactionNote)).all() == [] and db.get(MerchantRule, body["rule_id"]) is None


def test_the_journal_never_holds_the_note_or_the_name(frozen, signed_in, db):
    rows, _ = paypal(db)
    token = put(signed_in, rows[0], {"note": "for Dr. Alvarez", "nickname": "zorblax", "also": True, "future": True}).json()["undo"]
    fresh(db)
    entry = db.get(UndoEntry, token)
    assert "Alvarez" not in entry.before + entry.after and "zorblax" not in entry.before + entry.after


def test_note_only_name_only_and_the_refusals(frozen, signed_in, db):
    rows, boxes = paypal(db)
    r = put(signed_in, boxes[0], {"note": "Family plan"}).json()
    assert (r["rows"], r["notes_added"], r["named"], r["rule_id"]) == (1, 1, 0, None)
    r = put(signed_in, boxes[0], {"nickname": "  StreamBox family ", "also": True}).json()
    assert (r["rows"], r["notes_added"], r["named"]) == (2, 0, 2)                      # the same pattern, no amount
    fresh(db)
    assert {db.get(Transaction, b.id).nickname for b in boxes} == {"StreamBox family"}
    for body, message in (({}, "Add a note or a name."), ({"note": "  ", "nickname": ""}, "Add a note or a name."),
                          ({"nickname": "x" * 41}, "A name is 1 to 40 characters."),
                          ({"note": "x" * 1001}, "A note is 1 to 1,000 characters."),
                          ({"note": "ok", "also": "yes"}, "That request wasn't understood."),
                          ({"note": 5}, "A note is 1 to 1,000 characters.")):
        r = put(signed_in, rows[3], body)
        assert r.status_code == 422 and r.json() == {"error": message}


def test_future_keeps_an_existing_rules_category_and_unticking_clears_its_label(frozen, signed_in, db):
    rows, _ = paypal(db)
    db.add(MerchantRule(pattern="PAYPAL", merchant="PayPal", category="subscriptions", amount_cents=-1399,
                        source=CategorySource.correction))
    db.commit()
    rule_id = put(signed_in, rows[0], {"nickname": "Disney+", "future": True}).json()["rule_id"]
    fresh(db)
    rule = db.get(MerchantRule, rule_id)
    assert (rule.category, rule.nickname, rule.note, rule.note_by) == ("subscriptions", "Disney+", None, None)   # no note: no author
    put(signed_in, rows[1], {"note": "renewed", "future": False})
    fresh(db)
    assert (db.get(MerchantRule, rule_id).category, db.get(MerchantRule, rule_id).nickname) == ("subscriptions", None)


def test_unticking_future_on_a_names_only_rule_removes_it_and_undo_brings_it_back(frozen, signed_in, db):
    rows, _ = paypal(db)
    rule_id = put(signed_in, rows[0], {"nickname": "Disney+", "future": True}).json()["rule_id"]
    token = put(signed_in, rows[1], {"note": "renewed", "future": False}).json()["undo"]
    fresh(db)
    assert db.get(MerchantRule, rule_id) is None
    assert signed_in.post(f"/api/b/ours/undo/{token}").status_code == 200
    fresh(db)
    assert (db.get(MerchantRule, rule_id).nickname, db.get(MerchantRule, rule_id).amount_cents) == ("Disney+", -1399)


def test_undo_restores_a_deleted_rule_with_its_original_created_at(frozen, fake_clock, signed_in, db):
    rows, _ = paypal(db)
    rule_id = put(signed_in, rows[0], {"nickname": "Disney+", "future": True}).json()["rule_id"]
    fresh(db)
    made = db.get(MerchantRule, rule_id).created_at
    fake_clock.advance(timedelta(minutes=3))
    token = put(signed_in, rows[1], {"note": "renewed", "future": False}).json()["undo"]
    fresh(db)
    assert db.get(MerchantRule, rule_id) is None
    assert signed_in.post(f"/api/b/ours/undo/{token}").status_code == 200
    fresh(db)
    assert db.get(MerchantRule, rule_id).created_at == made


def test_also_over_500_rows_is_refused(frozen, signed_in, db):
    _, boxes = paypal(db)
    db.add_all([Transaction(account_id=boxes[0].account_id, posted_at=date(2026, 9, 1), amount_cents=-799,
                            raw_description="STREAMBOX", merchant="StreamBox", category="subscriptions",
                            category_source=CategorySource.none) for _ in range(500)])
    db.commit()
    r = put(signed_in, boxes[0], {"nickname": "StreamBox", "also": True})
    assert r.status_code == 422 and r.json() == {"error": "That's more than 500 rows. Narrow it with the amount."}
    fresh(db)
    assert all(t.nickname is None for t in db.scalars(select(Transaction)))
    assert put(signed_in, boxes[0], {"nickname": "StreamBox"}).status_code == 200      # without Also, the one row


def test_rows_carry_their_name_and_search_finds_it(frozen, signed_in, db):
    rows, _ = paypal(db)
    put(signed_in, rows[0], {"nickname": "Disney+", "also": True})
    found = signed_in.get("/api/b/ours/transactions", params={"q": "Disney+"}).json()["transactions"]
    assert sorted(t["id"] for t in found) == sorted(t.id for t in rows[:3])
    assert {t["nickname"] for t in found} == {"Disney+"}


def test_a_viewer_reads_the_reach_but_cannot_save(frozen, client, db, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    rows, _ = paypal(db)
    login(client, "vee")
    assert client.get(f"/api/b/ours/transactions/{rows[0].id}/label").status_code == 200
    r = client.put(f"/api/b/ours/transactions/{rows[0].id}/label", json={"nickname": "x"})
    assert r.status_code == 403 and r.json() == {"error": VIEWER_COPY}


def test_parent_books_have_no_labels(frozen, client, margaret):
    login(client, "jr")                                  # the margaret fixture makes jr a manager of both books
    assert client.get("/api/b/margaret-ellis/transactions/1/label").status_code == 404
    assert client.put("/api/b/margaret-ellis/transactions/1/label", json={"nickname": "x"}).status_code == 404
