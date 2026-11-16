"""The household's category rules (phase 12 decision 2, Rules list): a list with how many rows each covers, a category
change that touches no past row, a removal that leaves past rows, viewers read only, parent books have their own."""
from steward import clock
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import CategorySource, MerchantRule, Transaction
from steward.deps import VIEWER_COPY
from tests.factories import login, make_account, make_person, make_txn, make_user


def signed_in(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    login(client, "jr")


def rule(db, pattern, category, at=datetime(2026, 10, 1, tzinfo=timezone.utc), merchant=None):
    r = MerchantRule(pattern=pattern, merchant=merchant or pattern.title(), category=category, is_business=None,
                     source=CategorySource.correction, created_at=at)
    db.add(r); db.commit()
    return r


def test_the_list_counts_rows_by_pattern_most_rows_first(client, db):
    signed_in(client, db)
    a = make_account(db)
    for raw in ("UNION SERVICE CENTER 1", "UNION SERVICE CENTER 2", "union service center", "HARBOR GRILL 22"):
        make_txn(db, a, date(2026, 10, 1), -100, raw)
    union = rule(db, "UNION SERVICE CENTER", "home")
    grill = rule(db, "HARBOR GRILL", "dining", at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    none = rule(db, "NOWHERE", "gifts")
    r = client.get("/api/b/ours/categorize/rules")
    assert r.status_code == 200
    assert r.json()["rules"] == [
        {"id": union.id, "pattern": "UNION SERVICE CENTER", "merchant": "Union Service Center", "category": "home", "rows": 3,
         "created_at": "2026-10-01T00:00:00+00:00", "amount_cents": None, "nickname": None, "has_note": False},
        {"id": grill.id, "pattern": "HARBOR GRILL", "merchant": "Harbor Grill", "category": "dining", "rows": 1,
         "created_at": "2026-09-01T00:00:00+00:00", "amount_cents": None, "nickname": None, "has_note": False},
        {"id": none.id, "pattern": "NOWHERE", "merchant": "Nowhere", "category": "gifts", "rows": 0,
         "created_at": "2026-10-01T00:00:00+00:00", "amount_cents": None, "nickname": None, "has_note": False}]


def test_changing_a_rule_changes_the_rule_only(client, db):
    signed_in(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -100, "UNION SERVICE CENTER 1", category="home", category_source=CategorySource.rule)
    r = rule(db, "UNION SERVICE CENTER", "home")
    out = client.patch(f"/api/b/ours/categorize/rules/{r.id}", json={"category": "gifts"})
    assert out.status_code == 200 and out.json()["category"] == "gifts" and out.json()["rows"] == 1
    db.rollback()   # ends the test session's read snapshot so it sees what the request committed
    assert r.category == "gifts" and t.category == "home"
    for body, status in (({"category": "uncategorized"}, 422), ({"category": "lambos"}, 422), ({}, 422)):
        res = client.patch(f"/api/b/ours/categorize/rules/{r.id}", json=body)
        assert (res.status_code, res.json()) == (status, {"error": "That isn't one of the categories."}), body
    assert client.patch("/api/b/ours/categorize/rules/999", json={"category": "gifts"}).status_code == 404


def test_removing_a_rule_leaves_past_rows(client, db):
    signed_in(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -100, "UNION SERVICE CENTER 1", category="home", category_source=CategorySource.correction)
    r = rule(db, "UNION SERVICE CENTER", "home")
    assert client.delete(f"/api/b/ours/categorize/rules/{r.id}").status_code == 204
    assert client.delete(f"/api/b/ours/categorize/rules/{r.id}").status_code == 404
    db.rollback()   # ends the test session's read snapshot so it sees what the request committed
    assert db.scalar(select(MerchantRule)) is None and t.category == "home"
    assert client.get("/api/b/ours/categorize/rules").json() == {"rules": []}


def test_a_viewer_reads_the_rules_and_changes_nothing(client, db, ddb, ours):
    r = rule(db, "UNION SERVICE CENTER", "home")
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.get("/api/b/ours/categorize/rules").status_code == 200
    for method, body in (("PATCH", {"category": "gifts"}), ("DELETE", None)):
        res = client.request(method, f"/api/b/ours/categorize/rules/{r.id}", json=body)
        assert (res.status_code, res.json()) == (403, {"error": VIEWER_COPY})


def test_a_parent_book_has_its_own_rules(client, margaret, mdb):
    login(client, "jr")
    r = rule(mdb, "OAKHAVEN PHARMACY", "health")
    assert [x["id"] for x in client.get("/api/b/margaret-ellis/categorize/rules").json()["rules"]] == [r.id]
    assert client.get("/api/b/ours/categorize/rules").json() == {"rules": []}


def test_an_amount_rule_counts_only_its_amount_and_the_plain_rule_the_rest(client, db):
    signed_in(client, db)
    a = make_account(db)
    for cents in (-1399, -1399, -1399, -1399, -999, -500, -500, -200):
        make_txn(db, a, date(2026, 10, 1), cents, "PAYPAL *STUFF")
    plain = rule(db, "PAYPAL", "shopping")
    amount = MerchantRule(pattern="PAYPAL", merchant="PayPal", category="subscriptions", amount_cents=-1399,
                          source=CategorySource.correction, created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    db.add(amount)
    db.commit()
    rows = {x["id"]: x["rows"] for x in client.get("/api/b/ours/categorize/rules").json()["rules"]}
    assert rows == {amount.id: 4, plain.id: 4}


def test_usual_ranks_the_way_review_s_chips_do(client, db, ddb, ours):
    signed_in(client, db)
    fill = ["groceries", "dining", "shopping", "transport", "subscriptions", "personal"]
    assert client.get("/api/b/ours/categorize/usual").json() == {"keys": fill}
    a = make_account(db)
    for i in range(2):
        t = make_txn(db, a, date(2026, 10, 1 + i), -100, f"RENT {i}", category="housing",
                     category_source=CategorySource.correction)
        t.reviewed_at = clock.now()
    db.commit()
    keys = client.get("/api/b/ours/categorize/usual").json()["keys"]
    assert keys[0] == "housing" and len(keys) == 6
    assert keys == client.get("/api/b/ours/review").json()["top_categories"]
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.get("/api/b/ours/categorize/usual").status_code == 200
