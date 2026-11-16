"""Remembered layouts (spec P14): listed under Import, edited against the stored header, forgotten with Undo through
the journal (plan Engineering choice 1: Forget is a soft delete), per book."""
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from steward import clock
from steward.db.directory_models import User
from steward.db.models import Account, ImportLayout, Transaction, UndoEntry, UndoText
from steward.deps import NOT_IN_THIS_BOOK
from steward.services.undo import TTL
from tests.factories import login, make_account, make_person, make_txn
from tests.import_helpers import import_file, stage

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")
L = "/api/b/ours/import/layouts"


@pytest.fixture
def remembered(client, db, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    card = make_account(db, "Amex", type="credit")
    assert import_file(client, "amex-basic.csv", card.id, negate=True).status_code == 201
    [lay] = client.get(L).json()["layouts"]
    return lay


def test_the_list_after_a_commit(client, remembered):
    assert {k: remembered[k] for k in ("label", "header", "mapping", "negate", "date_format", "uses")} == {
        "label": "Amex", "header": ["Date", "Description", "Amount"], "mapping": {"date": 0, "description": 1, "amount": 2},
        "negate": True, "date_format": "%m/%d/%Y", "uses": 1}
    assert remembered["last_used_at"].startswith("2026-10-30")


def test_edit_is_checked_against_the_stored_header_and_undoes(client, db, remembered):
    url = f"{L}/{remembered['id']}"
    for body, error in (({"mapping": {"date": 0, "description": 1}}, "Choose an amount column, or both a money-out and a money-in column."),
                        ({"mapping": {"date": 0, "description": 1, "amount": 3}}, "That column mapping wasn't understood."),
                        ({"date_format": "%Q"}, "That request wasn't understood."),
                        ({"negate": "yes"}, "That request wasn't understood."),
                        ({"label": "x" * 61}, "Give it a name, up to 60 characters.")):
        r = client.patch(url, json=body)
        assert (r.status_code, r.json()) == (422, {"error": error}), body
    r = client.patch(url, json={"label": "Amex Gold", "negate": False, "date_format": "%d/%m/%Y"})
    assert r.status_code == 200
    assert {k: r.json()["layout"][k] for k in ("label", "negate", "date_format")} == \
        {"label": "Amex Gold", "negate": False, "date_format": "%d/%m/%Y"}
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    [back] = client.get(L).json()["layouts"]
    assert (back["label"], back["negate"], back["date_format"]) == ("Amex", True, "%m/%d/%Y")


def test_editing_to_money_out_and_money_in_columns_drops_negate(client, db, remembered):
    """The columns say the sign once Edit maps them, so a kept negate would import the next file backwards. (The Amex
    layout has three columns, too few for both; this one has four.)"""
    card = remembered["account_id"]
    head = "Date,Description,Amount,Credit\n"
    assert import_file(client, "four.csv", card, raw=(head + "10/01/2024,LUNCH,12.00,\n").encode(),
                       negate=True).status_code == 201
    [four] = [x for x in client.get(L).json()["layouts"] if x["header"] == ["Date", "Description", "Amount", "Credit"]]
    assert four["negate"] is True
    r = client.patch(f"{L}/{four['id']}", json={"mapping": {"date": 0, "description": 1, "debit": 2, "credit": 3},
                                                 "negate": True})
    assert (r.status_code, r.json()["layout"]["negate"]) == (200, False)
    raw = (head + "10/14/2024,COFFEE,45.67,\n10/15/2024,PAYROLL,,2100.00\n").encode()
    assert import_file(client, "four-2.csv", card, raw=raw).status_code == 201
    db.rollback()
    got = dict(db.execute(select(Transaction.raw_description, Transaction.amount_cents)
                          .where(Transaction.raw_description.in_(("COFFEE", "PAYROLL")))).all())
    assert got == {"COFFEE": -4567, "PAYROLL": 210000}


def test_forget_hides_the_layout_and_undo_brings_it_back_once(client, remembered):
    r = client.delete(f"{L}/{remembered['id']}")
    assert r.status_code == 200
    assert client.get(L).json()["layouts"] == []
    assert stage(client, "amex-basic.csv").json()["files"][0]["state"] == "new"
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    assert [x["id"] for x in client.get(L).json()["layouts"]] == [remembered["id"]]
    assert stage(client, "amex-basic.csv").json()["files"][0]["state"] == "remembered"
    again = client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    assert (again.status_code, again.json()) == (410, {"error": "Undo is no longer available for that."})


def test_a_forgotten_layout_goes_for_good_after_its_undo_has_passed(client, db, remembered, fake_clock):
    client.delete(f"{L}/{remembered['id']}")
    fake_clock.advance(timedelta(minutes=16))
    client.get(L)                                            # a read never deletes
    db.rollback()
    assert db.get(ImportLayout, remembered["id"]) is not None
    other = make_account(db, "Card", type="credit")
    assert import_file(client, "first-cu.csv", other.id).status_code == 201
    [mine] = client.get(L).json()["layouts"]
    client.patch(f"{L}/{mine['id']}", json={"label": "First CU"})
    db.rollback()
    assert db.get(ImportLayout, remembered["id"]) is None


def test_saving_the_same_key_after_forget_reuses_the_row_and_a_late_undo_refuses(client, db, remembered):
    r = client.delete(f"{L}/{remembered['id']}")
    card = remembered["account_id"]
    assert import_file(client, "amex-basic.csv", card, negate=False).status_code == 201
    [back] = client.get(L).json()["layouts"]
    assert (back["id"], back["negate"], back["uses"]) == (remembered["id"], False, 2)
    late = client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    assert (late.status_code, late.json()) == (409, {"error": "That changed since, so it can't be undone."})


def test_an_edited_label_is_journaled_as_text_and_a_later_rename_refuses_undo(client, db, remembered):
    """The label is a bank's or an account's name: undo_text keeps it, undo_entry never does (P36)."""
    url = f"{L}/{remembered['id']}"
    r = client.patch(url, json={"label": "Amex Gold"})
    db.rollback()
    entry = db.get(UndoEntry, r.json()["undo"])
    assert "Amex" not in entry.before + entry.after
    [text] = db.scalars(select(UndoText).where(UndoText.token == entry.token)).all()
    assert (text.model, text.row_key, text.field, text.value, text.written) == \
        ("layout", str(remembered["id"]), "label", "Amex", "Amex Gold")
    client.patch(url, json={"label": "Amex Platinum"})
    late = client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    assert (late.status_code, late.json()) == (409, {"error": "That changed since, so it can't be undone."})
    assert client.get(L).json()["layouts"][0]["label"] == "Amex Platinum"


def test_a_merchant_that_shares_a_layouts_label_may_be_journaled(client, db, remembered):
    """The label guard reads a layout's own journal fields: a snoozed row whose merchant is "Amex" keeps its merchant
    in the entry (a merchant is no name), though the Amex layout is labelled "Amex"."""
    db.rollback()
    t = make_txn(db, db.get(Account, remembered["account_id"]), date(2026, 10, 20), -1200, "AMEX FEE", merchant="Amex")
    db.commit()
    r = client.post(f"/api/b/ours/review/{t.id}/snooze")
    assert r.status_code == 200
    db.rollback()
    entry = db.get(UndoEntry, r.json()["undo"])
    assert '"Amex"' in entry.before


def test_undo_of_a_rename_alone_puts_the_label_back(client, remembered):
    r = client.patch(f"{L}/{remembered['id']}", json={"label": "Amex Gold"})
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    assert client.get(L).json()["layouts"][0]["label"] == "Amex"


def test_an_entry_from_before_with_the_label_inline_still_undoes(client, db, ddb, remembered, undo_entries_hold_no_text):
    """Entries written before the label moved to undo_text kept it in before and after: they still compare and
    restore it."""
    undo_entries_hold_no_text.update({"Amex", "Amex Gold"})      # the old format, planted on purpose
    lid = str(remembered["id"])
    db.rollback()
    row = db.get(ImportLayout, remembered["id"])
    t = clock.now()
    old = {"label": "Amex", "mapping": row.mapping, "negate": True, "date_format": "%m/%d/%Y",
           "account_id": row.account_id, "forgotten_at": None}
    db.add(UndoEntry(token="old-layout-entry", user_id=ddb.scalar(select(User.id).where(User.username == "jr")), action="layout", created_at=t,
                     expires_at=t + TTL, before=json.dumps({"target": None, "txns": {}, "layouts": {lid: old}}),
                     after=json.dumps({"txns": {}, "layouts": {lid: {**old, "label": "Amex Gold", "negate": False}}})))
    row.label, row.negate = "Amex Gold", False
    db.commit()
    assert client.post("/api/b/ours/undo/old-layout-entry").status_code == 200
    [back] = client.get(L).json()["layouts"]
    assert (back["label"], back["negate"]) == ("Amex", True)


def test_a_missing_layout_is_404(client, remembered):
    for r in (client.patch(f"{L}/99999", json={"label": "X"}), client.delete(f"{L}/99999")):
        assert (r.status_code, r.json()) == (404, {"error": "That layout isn't here anymore."})


def test_layouts_are_per_book(client, books, ddb, remembered):
    from steward.books.service import add_membership, create_book
    from steward.db.directory_models import User
    book = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret"])
    add_membership(ddb, ddb.scalar(select(User.id).where(User.username == "jr")), book.id, "manager", by=None)
    ddb.commit()
    assert client.get(f"/api/b/{book.slug}/import/layouts").json() == {"layouts": []}


def test_viewers_dont_see_layouts(client, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    assert client.get(L).status_code == 404
    assert client.delete(f"{L}/1").status_code == 404


IMPORT_ROUTES = [
    ("POST", "/files", None), ("DELETE", "/files/tok", None), ("GET", "/batch/b_any", None),
    ("POST", "/batch/preview", {}), ("POST", "/batch/commit", {}), ("GET", "/batches", None),
    ("POST", "/sets/1/rollback", None), ("POST", "/batches/1/rollback", None), ("GET", "/layouts", None),
    ("PATCH", "/layouts/1", {"label": "x"}), ("DELETE", "/layouts/1", None),
    ("POST", "/statements", None), ("GET", "/statements", None), ("PATCH", "/statements/1", {"anyway": True}),
    ("POST", "/statements/1/layout", {"answer": "right"}), ("POST", "/statements/1/rows", {"ops": []}),
    ("POST", "/statements/1/retry", None), ("DELETE", "/statements/1", None), ("POST", "/statements/1/restore", None),
    ("DELETE", "/statement-layouts/1", None),
]


def test_a_viewer_gets_404_on_every_import_route_and_a_manager_gets_their_own_answer(client, ddb, ours):
    """Spec: viewers do not see Import. The write guard 403 must not answer first, on any route."""
    make_person(ddb, "val", [(ours.id, "viewer")])
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "val")
    for method, path, body in IMPORT_ROUTES:
        r = client.request(method, f"/api/b/ours/import{path}", json=body)
        assert (r.status_code, r.json()) == (404, {"error": NOT_IN_THIS_BOOK}), (method, path, r.text)
    login(client, "jr")
    for method, path, body in IMPORT_ROUTES:
        r = client.request(method, f"/api/b/ours/import{path}", json=body)
        assert r.status_code not in (403, 500) and r.json().get("error") != NOT_IN_THIS_BOOK, (method, path, r.text)
