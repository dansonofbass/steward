"""PUT /business/transactions/{id} and PATCH /transactions/{id} {is_business} (spec 5, Review Focus 1 and 3)."""
from datetime import date

import pytest
from sqlalchemy import select

from steward.db.models import CategorySource, MerchantRule, Transaction
from tests.factories import login, make_account, make_person, make_txn


def url(tid):
    return f"/api/b/ours/business/transactions/{tid}"


def test_a_split_comes_back_with_its_line_and_keeps_the_category(frozen, signed_in, db):
    t = make_txn(db, make_account(db), date(2026, 10, 1), -10_000, "MOBILE ONE WIRELESS", category="utilities",
                 category_source=CategorySource.rule)
    r = signed_in.put(url(t.id), json={"pct": 40, "line": "utilities"})
    assert r.status_code == 200
    row = r.json()
    assert (row["business_pct"], row["business_line"], row["business_source"], row["is_business"]) == \
        (40, "utilities", "manual", False)
    assert (row["category"], row["category_source"], row["reviewed_at"]) == ("utilities", "rule", None)
    row = signed_in.put(url(t.id), json={"pct": 100}).json()
    assert row["is_business"] is True and row["business_line"] == "utilities"
    db.rollback()
    assert db.scalars(select(MerchantRule)).all() == []


@pytest.mark.parametrize("body", [{"pct": 101}, {"pct": -1}, {"pct": 33.5}, {"pct": True}, {"pct": "50"}, {},
                                  {"pct": 50, "line": "yacht"}])
def test_bad_percents_and_transfers_are_refused(frozen, signed_in, db, body):
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -5_000, "X")
    r = signed_in.put(url(t.id), json=body)
    assert r.status_code == 422 and r.json()["error"] in (
        "Choose a whole percent from 0 to 100.", "That isn't one of the Schedule C lines.")
    x = make_txn(db, a, date(2026, 10, 1), -5_000, "TRANSFER TO SAVINGS", category="transfer", is_transfer=True)
    r = signed_in.put(url(x.id), json={"pct": 100})
    assert r.status_code == 422 and r.json() == {
        "error": "A transfer moves money between your own accounts, so it isn't business or personal."}
    assert signed_in.put(url(999_999), json={"pct": 100}).status_code == 404
    db.rollback()
    assert db.get(Transaction, t.id).business_pct == 0


def test_patch_is_business_tags_without_reviewing_or_writing_a_rule(frozen, signed_in, db):
    t = make_txn(db, make_account(db), date(2026, 10, 1), -9_900, "ADOBE *CC", merchant="Adobe",
                 category="subscriptions")
    row = signed_in.patch(f"/api/b/ours/transactions/{t.id}", json={"is_business": True}).json()
    assert (row["is_business"], row["business_pct"], row["reviewed_at"], row["category_source"]) == \
        (True, 100, None, "none")
    row = signed_in.patch(f"/api/b/ours/transactions/{t.id}", json={"is_business": False}).json()
    assert (row["business_pct"], row["business_source"]) == (0, "manual")
    row = signed_in.patch(f"/api/b/ours/transactions/{t.id}",
                          json={"category": "business_expense", "is_business": True}).json()
    assert row["category"] == "business_expense" and row["business_pct"] == 100 and row["reviewed_at"]


def test_a_viewer_cannot_tag(frozen, client, db, ddb, ours):
    t = make_txn(db, make_account(db), date(2026, 10, 1), -5_000, "X")
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.put(url(t.id), json={"pct": 100}).status_code == 403


def test_parent_books_refuse_is_business(frozen, client, margaret, mdb):
    login(client, "jr")
    t = make_txn(mdb, make_account(mdb, "Checking"), date(2026, 10, 1), -1_000, "COFFEE")
    r = client.patch(f"/api/b/margaret-ellis/transactions/{t.id}", json={"is_business": True})
    assert r.status_code == 422 and r.json() == {"error": "Business or personal is for household books."}
    r = client.put(f"/api/b/margaret-ellis/business/transactions/{t.id}", json={"pct": 100})
    assert r.status_code == 404
    mdb.rollback()
    assert mdb.get(Transaction, t.id).business_pct == 0
