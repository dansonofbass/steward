import re

import pytest
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import CategorySource, MerchantRule, UndoEntry
from steward.services.transactions import normalize
from tests.factories import make_account, make_txn, make_user

TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_normalize():
    assert normalize("COSTCO WHSE #0482  10/03") == "COSTCO WHSE"
    assert normalize("  amazon.com*2K4L9  ") == "AMAZON.COM"
    assert normalize("Zelle payment to Jane Doe 12345") == "ZELLE PAYMENT TO JANE DOE"


def test_list_filters_and_search(client, db):
    login(client, db)
    chk = make_account(db, "Checking")
    card = make_account(db, "Sapphire", type="credit", owner="joint")
    make_txn(db, chk, date(2026, 10, 1), -5000, "COSTCO WHSE #0482", merchant="Costco", category="groceries")
    make_txn(db, card, date(2026, 10, 2), -1200, "STARBUCKS 123", merchant="Starbucks", category="dining")
    make_txn(db, card, date(2026, 10, 3), -9900, "ADOBE *CC", merchant="Adobe", category="business_expense", is_business=True)
    r = client.get("/api/b/ours/transactions").json()
    assert [t["merchant"] for t in r["transactions"]] == ["Adobe", "Starbucks", "Costco"]
    assert client.get(f"/api/b/ours/transactions?account_id={card.id}").json()["transactions"].__len__() == 2
    assert client.get("/api/b/ours/transactions?q=star").json()["transactions"][0]["merchant"] == "Starbucks"
    assert client.get("/api/b/ours/transactions?business=true").json()["transactions"][0]["merchant"] == "Adobe"
    assert client.get("/api/b/ours/transactions?category=groceries").json()["transactions"][0]["merchant"] == "Costco"
    assert client.get("/api/b/ours/transactions?from=2026-10-02&to=2026-10-02").json()["transactions"][0]["merchant"] == "Starbucks"


def test_pagination_cursor(client, db):
    login(client, db)
    a = make_account(db)
    for i in range(7):
        make_txn(db, a, date(2026, 9, 1 + i), -100 * i, f"T{i}")
    p1 = client.get("/api/b/ours/transactions?limit=3").json()
    assert len(p1["transactions"]) == 3 and p1["next_cursor"]
    p2 = client.get(f"/api/b/ours/transactions?limit=3&cursor={p1['next_cursor']}").json()
    p3 = client.get(f"/api/b/ours/transactions?limit=3&cursor={p2['next_cursor']}").json()
    ids = [t["id"] for p in (p1, p2, p3) for t in p["transactions"]]
    assert len(ids) == 7 and len(set(ids)) == 7 and p3["next_cursor"] is None


def test_patch_writes_rule_and_review_queue(client, db):
    login(client, db)
    a = make_account(db)
    t1 = make_txn(db, a, date(2026, 10, 1), -5000, "COSTCO WHSE #0482")
    t2 = make_txn(db, a, date(2026, 10, 2), -4000, "COSTCO WHSE #0911")
    make_txn(db, a, date(2026, 10, 2), -4000, "TRANSFER TO SAVINGS", is_transfer=True, category="transfer")
    q = client.get("/api/b/ours/review").json()
    assert q["count"] == 2 and [x["id"] for x in q["uncategorized"]] == [t1.id, t2.id]
    r = client.patch(f"/api/b/ours/transactions/{t1.id}", json={"merchant": "Costco", "category": "groceries"})
    assert r.status_code == 200 and r.json()["category_source"] == "correction" and r.json()["reviewed_at"]
    db.rollback()  # end the read snapshot so we see the request's commit
    rule = db.scalars(select(MerchantRule)).one()
    assert rule.pattern == "COSTCO WHSE" and rule.category == "groceries" and rule.merchant == "Costco"
    assert client.get("/api/b/ours/review").json()["count"] == 1
    # imported fields untouched
    assert r.json()["raw_description"] == "COSTCO WHSE #0482" and r.json()["amount_cents"] == -5000


def test_patch_rejects_unknown_category(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -1, "X")
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "lambos"})
    assert r.status_code == 422


def test_normalize_keeps_distinct_star_merchants():
    blue, red = normalize("SQ *BLUE BOTTLE"), normalize("SQ *RED BOTTLE")
    assert blue != red and "  " not in blue and "  " not in red


def test_patch_category_transfer_writes_a_rule_and_pairs(client, db):
    """Phase 12 ruling 11: a Transfer a person chooses is a rule like any other, and the row pairs with its other side."""
    login(client, db)
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE EPAY 0042")
    back = make_txn(db, card, date(2026, 10, 7), 40000, "PAYMENT RECEIVED")
    r = client.patch(f"/api/b/ours/transactions/{out.id}", json={"category": "transfer"})
    assert r.status_code == 200 and r.json()["is_transfer"] is True and "also" not in r.json()
    assert {k: r.json()["result"][k] for k in ("category", "applied", "rule")} == {"category": "transfer", "applied": 0, "rule": "made"}
    db.rollback()                 # end the read snapshot so the API's commit is visible
    rule = db.scalar(select(MerchantRule).where(MerchantRule.pattern == "CHASE EPAY"))
    assert rule is not None and rule.category == "transfer"
    assert out.transfer_peer_id == back.id and back.is_transfer and back.category == "transfer"


def test_moving_a_paired_row_off_transfer_sends_its_other_side_back_to_review(client, db):
    """The other side was a transfer only as this row's pair: left as one, it would hide from Review and every spread."""
    login(client, db)
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    a = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE EPAY 0042")
    b = make_txn(db, card, date(2026, 10, 7), 40000, "PAYMENT RECEIVED")
    db.commit()
    b_id = b.id
    assert client.patch(f"/api/b/ours/transactions/{a.id}", json={"category": "transfer"}).status_code == 200
    db.rollback()
    assert a.transfer_peer_id == b_id and b.transfer_peer_id == a.id
    db.rollback()
    r = client.patch(f"/api/b/ours/transactions/{a.id}", json={"category": "dining"})
    assert r.status_code == 200 and r.json()["is_transfer"] is False
    db.rollback()
    assert (a.category, a.is_transfer, a.transfer_peer_id) == ("dining", False, None)
    assert (b.category, b.category_source, b.is_transfer, b.transfer_peer_id, b.model_asked_at) == (
        "uncategorized", CategorySource.none, False, None, None)
    db.rollback()
    assert b_id in [t["id"] for t in client.get("/api/b/ours/review").json()["uncategorized"]]


def test_unpairing_leaves_a_side_a_person_sorted_as_they_sorted_it(client, db):
    login(client, db)
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    b = make_txn(db, card, date(2026, 10, 7), 40000, "PAYMENT RECEIVED")
    db.commit()
    client.patch(f"/api/b/ours/transactions/{b.id}", json={"category": "transfer"})      # no other side yet
    db.rollback()
    assert b.transfer_peer_id is None
    a = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE EPAY 0042")
    db.commit()
    client.patch(f"/api/b/ours/transactions/{a.id}", json={"category": "transfer"})      # pairs with b
    db.rollback()
    assert a.transfer_peer_id == b.id and b.transfer_peer_id == a.id
    db.rollback()
    client.patch(f"/api/b/ours/transactions/{a.id}", json={"category": "dining"})
    db.rollback()
    assert (b.category, b.category_source, b.is_transfer, b.transfer_peer_id) == (
        "transfer", CategorySource.correction, True, None)


def test_patch_other_category_clears_transfer_and_writes_rule(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -4000, "ZELLE JANE", is_transfer=True, category="transfer")
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "giving"})
    assert r.json()["is_transfer"] is False
    db.rollback()  # end the read snapshot so we see the request's commit
    assert db.scalars(select(MerchantRule)).one().category == "giving"


def test_patch_empty_pattern_skips_rule(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -100, "*ABC")
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "fees"})
    assert r.status_code == 200 and r.json()["category"] == "fees" and r.json()["reviewed_at"]
    assert db.scalars(select(MerchantRule)).all() == []


def test_bad_cursor_is_422(client, db):
    login(client, db)
    r = client.get("/api/b/ours/transactions?cursor=garbage")
    assert r.status_code == 422 and r.json() == {"error": "That page marker isn't valid."}


def test_patch_merchant_too_long_is_422(client, db):
    login(client, db)
    t = make_txn(db, make_account(db), date(2026, 10, 1), -1, "X")
    assert client.patch(f"/api/b/ours/transactions/{t.id}", json={"merchant": "m" * 201}).status_code == 422


@pytest.mark.parametrize("body", [{"is_business": True}, {"merchant": "X"}])
def test_patch_without_category_on_uncategorized_row_is_not_a_review(client, db, body):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -5000, "COSTCO WHSE #0482")
    assert client.get("/api/b/ours/review").json()["count"] == 1
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json=body)
    assert r.status_code == 200 and r.json()["reviewed_at"] is None
    k, v = next(iter(body.items()))
    assert r.json()[k] == v and r.json()["category"] == "uncategorized"
    assert client.get("/api/b/ours/review").json()["count"] == 1
    assert db.scalars(select(MerchantRule)).all() == []


def test_patch_category_on_uncategorized_row_reviews_and_writes_rule(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -5000, "COSTCO WHSE #0482")
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "groceries"})
    assert r.json()["reviewed_at"] and r.json()["category_source"] == "correction"
    db.rollback()  # end the read snapshot so we see the request's commit
    assert db.scalars(select(MerchantRule)).one().category == "groceries"


def test_sorting_a_row_clears_its_guess(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    t.guess_category, t.guess_pct = "home", 45
    db.commit()
    assert client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"}).status_code == 200
    db.rollback()  # end the read snapshot so we see the request's commit
    assert (t.guess_category, t.guess_pct, t.category) == (None, None, "home")


def test_a_sort_applied_to_matching_sets_the_rows_in_one_go_and_says_how_many(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041", merchant="Union Service Center")
    others = [make_txn(db, a, date(2026, 9, d), -8000, f"UNION SERVICE CENTER 00{d}") for d in (3, 4)]
    already = make_txn(db, a, date(2026, 9, 5), -8000, "UNION SERVICE CENTER 0005", category="home",
                       category_source=CategorySource.rule)
    assert client.get(f"/api/b/ours/transactions/{t.id}/matching").json() == {"count": 3}
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home", "apply_to_matching": True})
    res = r.json()["result"]
    assert {k: res[k] for k in ("category", "applied", "rule")} == {"category": "home", "applied": 2, "rule": "made"}
    assert TOKEN.match(res["undo"]) and "also" not in r.json()
    db.rollback()
    for o in others:
        assert (o.category, o.category_source, o.merchant) == ("home", CategorySource.correction, "Union Service Center")
    assert already.category_source == CategorySource.rule     # already Home: not counted, not changed


def test_without_apply_only_the_row_changes(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    o = make_txn(db, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    assert client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"}).json()["result"]["applied"] == 0
    db.rollback()
    assert o.category == "uncategorized"


def test_the_result_says_whether_the_rule_was_made_kept_or_changed(client, db):
    login(client, db)
    a = make_account(db)
    one = make_txn(db, a, date(2026, 10, 3), -2500, "HARBOR GRILL 22")
    two = make_txn(db, a, date(2026, 10, 4), -2500, "HARBOR GRILL 23")
    word = lambda t, c: client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": c}).json()["result"]["rule"]
    assert word(one, "dining") == "made"
    assert word(two, "dining") == "kept"
    assert word(two, "entertainment") == "changed"
    assert word(one, "uncategorized") == "none"
    assert "result" not in client.patch(f"/api/b/ours/transactions/{one.id}", json={"merchant": "Harbor"}).json()


def test_the_result_s_undo_puts_the_row_the_matching_rows_and_the_rule_back(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    o = make_txn(db, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040", category="shopping",
                 category_source=CategorySource.model)
    token = client.patch(f"/api/b/ours/transactions/{t.id}",
                         json={"category": "home", "apply_to_matching": True}).json()["result"]["undo"]
    r = client.post(f"/api/b/ours/undo/{token}")
    assert r.status_code == 200 and r.json()["undone"] == 2 and r.json()["transaction"]["category"] == "uncategorized"
    db.rollback()
    assert (t.category, t.reviewed_at) == ("uncategorized", None)
    assert (o.category, o.category_source) == ("shopping", CategorySource.model)
    assert db.scalars(select(MerchantRule)).all() == []


def test_a_refused_business_tag_changes_nothing_and_leaves_no_undo(client, db):
    login(client, db)
    t = make_txn(db, make_account(db), date(2026, 10, 3), -40000, "CHASE EPAY 0042")
    r = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "transfer", "is_business": True})
    assert r.status_code == 422
    db.rollback()
    assert t.category == "uncategorized" and db.scalars(select(UndoEntry)).all() == []


def test_an_unnormalizable_description_sorts_without_a_rule_and_still_undoes(client, db):
    """Review Focus 3."""
    login(client, db)
    t = make_txn(db, make_account(db), date(2026, 10, 1), -100, "*ABC")
    res = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "fees", "apply_to_matching": True}).json()["result"]
    assert (res["applied"], res["rule"]) == (0, "none")
    assert client.post(f"/api/b/ours/undo/{res['undo']}").status_code == 200
    db.rollback()
    assert (t.category, t.reviewed_at) == ("uncategorized", None)


def test_spread_sets_the_other_rows_and_answers_how_many(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    others = [make_txn(db, a, date(2026, 9, i), -8000, f"UNION SERVICE CENTER 00{i}") for i in (3, 4)]
    client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"})
    r = client.post(f"/api/b/ours/transactions/{t.id}/spread")
    assert (r.status_code, r.json()) == (200, {"changed": 2})
    db.rollback()                 # end the read snapshot so the API's commit is visible
    for o in others:
        assert (o.category, o.category_source, o.merchant) == ("home", CategorySource.correction, "Union Service Center")
        assert o.reviewed_at is not None
    assert client.post(f"/api/b/ours/transactions/{t.id}/spread").json() == {"changed": 0}


def test_a_spread_leaves_a_row_sorted_after_the_offer_alone(client, db):
    """Review Focus 1: the offer said 2; a person sorts one of them before Apply is tapped. The other person's
    sort is set straight in the db (a PATCH would rewrite the shared rule and the category check would refuse)."""
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    one = make_txn(db, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    two = make_txn(db, a, date(2026, 8, 3), -8000, "UNION SERVICE CENTER 0039")
    assert client.get(f"/api/b/ours/transactions/{t.id}/matching").json() == {"count": 2}
    client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"})
    db.rollback()                 # end the read snapshot before writing as the other person
    at = t.reviewed_at
    one.category, one.category_source, one.reviewed_at = "gifts", CategorySource.correction, at   # not the rule's
    db.commit()
    assert client.post(f"/api/b/ours/transactions/{t.id}/spread").json() == {"changed": 1}
    db.rollback()                 # end the read snapshot so the API's commit is visible
    assert (one.category, one.reviewed_at) == ("gifts", at)
    assert two.category == "home" and two.category_source == CategorySource.correction


def test_spread_refuses_when_the_rule_went_or_the_category_changed(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"})
    db.rollback()
    rule = db.scalar(select(MerchantRule).where(MerchantRule.pattern == "UNION SERVICE CENTER"))
    rule.category = "gifts"                                                               # changed in Settings since
    db.commit()
    r = client.post(f"/api/b/ours/transactions/{t.id}/spread")
    assert (r.status_code, r.json()) == (409, {"error": "This transaction's category changed since, so nothing else changed."})
    db.delete(rule)
    db.commit()
    r = client.post(f"/api/b/ours/transactions/{t.id}/spread")
    assert (r.status_code, r.json()) == (409, {"error": "That rule was removed, so nothing else changed."})
    assert client.post("/api/b/ours/transactions/99999/spread").status_code == 404


def test_a_description_with_percent_or_underscore_is_not_a_wildcard(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "50%_OFF SHOP 1")
    make_txn(db, a, date(2026, 9, 3), -8000, "50%_OFF SHOP 2")
    make_txn(db, a, date(2026, 9, 4), -8000, "50XXOFF SHOP 3")
    assert client.get(f"/api/b/ours/transactions/{t.id}/matching").json() == {"count": 1}


def test_sorted_filter_finds_the_models_rows_and_its_guesses(client, db):
    login(client, db)
    a = make_account(db)
    model = make_txn(db, a, date(2026, 10, 1), -500, "BEAN CAFE", category="dining", category_source=CategorySource.model)
    checked = make_txn(db, a, date(2026, 10, 2), -500, "BEAN CAFE 2", category="dining", category_source=CategorySource.model)
    checked.reviewed_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
    unsure = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER")
    unsure.guess_category, unsure.guess_pct = "home", 45
    db.commit()
    ids = lambda r: [t["id"] for t in r.json()["transactions"]]
    assert ids(client.get("/api/b/ours/transactions?sorted=steward")) == [model.id]
    assert ids(client.get("/api/b/ours/transactions?sorted=unsure")) == [unsure.id]
    assert client.get("/api/b/ours/transactions?sorted=maybe").status_code == 422


def test_matching_answers_the_count_the_detail_offers(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041", category="home",
                 category_source=CategorySource.correction)
    make_txn(db, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    make_txn(db, a, date(2026, 9, 4), -8000, "UNION SERVICE CENTER 0039", category="dining",
             category_source=CategorySource.model)
    star = make_txn(db, a, date(2026, 9, 5), -100, "*ABC")
    assert client.get(f"/api/b/ours/transactions/{t.id}/matching").json() == {"count": 2}
    assert client.get(f"/api/b/ours/transactions/{star.id}/matching").json() == {"count": 0}
    r = client.get("/api/b/ours/transactions/99999/matching")
    assert (r.status_code, r.json()) == (404, {"error": "No such transaction."})


BETTERMENT = "BETTERMENT SEC TRANSFER\n{code}\nWEB ID: {web}"


def test_the_monthly_betterment_transfers_sort_together_and_next_months_takes_the_rule(client, db):
    """JR's case: each month's checking-to-Betterment row carries its own code and WEB ID, so before smarter patterns
    every row was its own pattern and none could be sorted with the others or caught by the rule."""
    from steward.deps import now
    from steward.services.importers.base import ParsedRow
    from steward.services.ingest import ingest_rows
    login(client, db)
    a = make_account(db)
    rows = [make_txn(db, a, date(2026, m, 2), -50000, BETTERMENT.format(code=code, web=web))
            for m, code, web in ((8, "ST-A1B2C3D4E5", "1234567890"), (9, "ST-K9J8H7G6F5", "1234567890"),
                                 (10, "ST-Q1W2E3R4T5", "9876543210"))]
    first = rows[-1]
    assert client.get(f"/api/b/ours/transactions/{first.id}/matching").json() == {"count": 2}
    r = client.patch(f"/api/b/ours/transactions/{first.id}",
                     json={"category": "transfer", "merchant": "Betterment", "apply_to_matching": True})
    assert r.status_code == 200 and r.json()["result"]["applied"] == 2
    db.rollback()
    assert [(t.category, t.merchant) for t in rows] == [("transfer", "Betterment")] * 3
    assert db.scalar(select(MerchantRule.pattern)) == "BETTERMENT SEC TRANSFER"
    (nov,) = ingest_rows(db, a, [ParsedRow(date(2026, 11, 2), -50000,
                                           BETTERMENT.format(code="ST-Z9X8C7V6B5", web="5550001111"), "nov")],
                         batch=None, now=now(), model=None)
    db.commit()
    # The household's rule answered (no built-in names Betterment); a transfer row is always rule-sourced at ingest.
    assert (nov.category, nov.merchant, nov.is_transfer, nov.reviewed_at) == ("transfer", "Betterment", True, None)
