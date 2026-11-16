import json

from steward import clock
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import CategorySource, DuplicateKeep, Transaction, TransactionNote, WatchState
from steward.services.review import duplicate_pairs
from tests.factories import make_account, make_txn, make_user


def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_duplicate_pairs_rules(db):
    a = make_account(db, "Card", type="credit")
    b = make_account(db, "Checking")
    synced = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031", external_id="x1")
    manual = make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031")           # same amount, +1 day, no bank id
    x2 = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031", external_id="x2")  # also pairs with the file row
    make_txn(db, a, date(2026, 1, 14), -4_50, "BEAN & LEAF 0031")                    # 4 days off: not a duplicate
    make_txn(db, a, date(2026, 1, 10), -4_51, "BEAN & LEAF 0031")                    # different amount
    make_txn(db, b, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031")                    # other account
    pairs = {(p.id, q.id) for p, q in duplicate_pairs(db)}
    # two bank rows (x1, x2) are never a pair; each pairs with the file-imported row (lower id first)
    assert pairs == {(synced.id, manual.id), (manual.id, x2.id)}  # a.id < b.id


def test_duplicate_pairs_both_manual_and_kept_pairs(db):
    a = make_account(db, "Card", type="credit")
    one = make_txn(db, a, date(2026, 2, 1), -10_00, "TAQUERIA SOL")
    two = make_txn(db, a, date(2026, 2, 2), -10_00, "TAQUERIA SOL")
    assert [(p.id, q.id) for p, q in duplicate_pairs(db)] == [(one.id, two.id)]
    db.add(DuplicateKeep(a_id=one.id, b_id=two.id))
    db.commit()
    assert duplicate_pairs(db) == []


def test_review_includes_duplicates(client, db):
    login(client, db)
    a = make_account(db, "Card", type="credit")
    p = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031", external_id="x1", category="dining")
    q = make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031", category="dining")
    r = client.get("/api/b/ours/review").json()
    assert r["duplicate_count"] == 1 and r["duplicates"][0]["a"]["id"] == p.id and r["duplicates"][0]["b"]["id"] == q.id
    assert set(r["duplicates"][0]["a"]) >= {"id", "posted_at", "amount_cents", "raw_description", "account_name"}
    assert r["duplicates"][0]["a"]["from_bank"] is True and r["duplicates"][0]["b"]["from_bank"] is False


def test_keep_both_hides_pair(client, db):
    login(client, db)
    a = make_account(db, "Card", type="credit")
    p = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031", external_id="x1")
    q = make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031")
    assert client.post("/api/b/ours/review/duplicates/keep", json={"a": q.id, "b": p.id}).status_code == 204  # order-insensitive
    assert client.get("/api/b/ours/review").json()["duplicate_count"] == 0
    assert client.post("/api/b/ours/review/duplicates/keep", json={"a": q.id, "b": p.id}).status_code == 204  # idempotent
    r = client.post("/api/b/ours/review/duplicates/keep", json={"a": q.id, "b": 99999})
    assert r.status_code == 404 and r.json() == {"error": "No such transaction."}


def test_delete_manual_row_only(client, db):
    login(client, db)
    a = make_account(db, "Card", type="credit")
    bank = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031", external_id="x1")
    manual = make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031")
    r = client.delete(f"/api/b/ours/transactions/{bank.id}")
    assert r.status_code == 409 and r.json() == {"error": "This came from the bank, so it can't be removed."}
    assert client.delete(f"/api/b/ours/transactions/{manual.id}").status_code == 204
    assert client.delete(f"/api/b/ours/transactions/{manual.id}").status_code == 404
    assert client.get("/api/b/ours/review").json()["duplicate_count"] == 0


def test_delete_unpairs_transfer_peer_and_drops_keep_rows(client, db):
    login(client, db)
    a = make_account(db, "Checking")
    b = make_account(db, "Savings", type="savings")
    out = make_txn(db, a, date(2026, 3, 1), -100_00, "TRANSFER TO SAVINGS", category="transfer", is_transfer=True)
    inn = make_txn(db, b, date(2026, 3, 1), 100_00, "TRANSFER FROM CHECKING", category="transfer", is_transfer=True)
    out.transfer_peer_id, inn.transfer_peer_id = inn.id, out.id
    twin = make_txn(db, a, date(2026, 3, 2), -100_00, "TRANSFER TO SAVINGS")
    db.add(DuplicateKeep(a_id=min(out.id, twin.id), b_id=max(out.id, twin.id)))
    db.commit()
    assert client.delete(f"/api/b/ours/transactions/{out.id}").status_code == 204
    db.commit()  # end the test session's read snapshot so the API session's writes are visible
    peer = db.get(Transaction, inn.id)
    assert (peer.is_transfer, peer.transfer_peer_id, peer.category) == (False, None, "uncategorized")
    assert db.scalars(select(DuplicateKeep)).all() == []


def test_rollback_of_import_with_keep_record_succeeds(client, db):
    from tests.import_helpers import import_file
    login(client, db)
    a = make_account(db, "Card", type="credit")
    other = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031")
    body = b"Date,Description,Amount\n2026-01-11,BEAN & LEAF 0031,-4.50\n"
    r = import_file(client, "x.csv", a.id, raw=body, include_same=True)
    assert r.status_code == 201
    other_id = other.id
    db.commit()  # end the read snapshot so the import's rows are visible
    imported = db.scalars(select(Transaction).where(Transaction.import_batch_id == r.json()["batch_ids"][0])).one()
    assert client.post("/api/b/ours/review/duplicates/keep", json={"a": other_id, "b": imported.id}).status_code == 204
    r2 = client.post(f"/api/b/ours/import/batches/{r.json()['batch_ids'][0]}/rollback")
    assert r2.status_code == 200 and r2.json() == {"deleted": 1, "kept": []}
    db.commit()
    assert db.scalars(select(DuplicateKeep)).all() == []


def _corrected(db, acct, cat, n, days_ago=1, desc="SHOP"):
    from datetime import timedelta
    from steward.db.models import CategorySource
    from steward.deps import now
    for i in range(n):
        t = make_txn(db, acct, date(2026, 1, 1), -1_00 - i, f"{desc} {cat} {i}", category=cat,
                     category_source=CategorySource.correction)
        t.reviewed_at = now() - timedelta(days=days_ago)
    db.commit()


def test_top_categories_fallback_to_fixed_six(client, db):
    login(client, db)
    assert client.get("/api/b/ours/review").json()["top_categories"] == [
        "groceries", "dining", "shopping", "transport", "subscriptions", "personal"]


def test_top_categories_ranked_filled_and_filtered(client, db):
    login(client, db)
    a = make_account(db)
    _corrected(db, a, "health", 3)
    _corrected(db, a, "kids", 2)
    _corrected(db, a, "dining", 2)           # ties with kids; dining comes first in CATEGORIES order
    _corrected(db, a, "uncategorized", 5)    # excluded
    _corrected(db, a, "transfer", 5)         # excluded
    _corrected(db, a, "travel", 9, days_ago=200)  # too old
    top = client.get("/api/b/ours/review").json()["top_categories"]
    assert top == ["health", "dining", "kids", "groceries", "shopping", "transport"]
    assert len(set(top)) == 6


def test_top_categories_full_six_from_corrections(client, db):
    login(client, db)
    a = make_account(db)
    for i, c in enumerate(["housing", "utilities", "travel", "health", "insurance", "giving", "gifts"]):
        _corrected(db, a, c, 7 - i)
    assert client.get("/api/b/ours/review").json()["top_categories"] == [
        "housing", "utilities", "travel", "health", "insurance", "giving"]


def test_snooze_hides_for_a_week(client, db, monkeypatch):
    from datetime import timedelta
    import steward.api.review as mod
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 1, 5), -9_00, "MYSTERY")
    keep = make_txn(db, a, date(2026, 1, 6), -3_00, "OTHER")
    assert client.post(f"/api/b/ours/review/{t.id}/snooze").status_code == 200
    r = client.get("/api/b/ours/review").json()
    assert r["count"] == 1 and [x["id"] for x in r["uncategorized"]] == [keep.id]
    db.rollback()
    row = db.get(Transaction, t.id)
    assert row.snoozed_until is not None and row.category == "uncategorized" and row.reviewed_at is None
    later = clock.now() + timedelta(days=8)
    monkeypatch.setattr(mod, "now", lambda: later)
    r = client.get("/api/b/ours/review").json()
    assert r["count"] == 2


def test_snooze_and_ignore_404(client, db):
    login(client, db)
    for verb in ("snooze", "ignore"):
        r = client.post(f"/api/b/ours/review/99999/{verb}")
        assert r.status_code == 404 and r.json() == {"error": "No such transaction."}


def test_ignore_leaves_review_for_good_and_keeps_category(client, db):
    login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 1, 5), -9_00, "MYSTERY")
    assert client.post(f"/api/b/ours/review/{t.id}/ignore").status_code == 200
    r = client.get("/api/b/ours/review").json()
    assert r["count"] == 0 and r["uncategorized"] == []
    db.rollback()
    row = db.get(Transaction, t.id)
    assert row.reviewed_at is not None and row.category == "uncategorized"
    assert client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "gifts"}).status_code == 200


def test_removing_a_file_row_leaves_a_line_in_the_log(client, db):
    """The confirmation says the log keeps a line saying it was removed (Argon's review of p09-confirmations): it
    does, in every book, without the row's description."""
    login(client, db)
    a = make_account(db, "Card", type="credit")
    manual = make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031")
    assert client.delete(f"/api/b/ours/transactions/{manual.id}").status_code == 204
    lines = [e["message"] for e in client.get("/api/b/ours/events").json()["events"] if e["kind"] == "import"]
    assert lines == ["Removed a transaction that came from a file"]


def test_each_row_says_why_it_is_here_and_carries_its_guess(client, db):
    login(client, db)
    a = make_account(db)
    zelle = make_txn(db, a, date(2026, 10, 1), -4000, "ZELLE TO SAM", merchant="Zelle")
    unsure = make_txn(db, a, date(2026, 10, 2), -8000, "UNION SERVICE CENTER")
    unsure.guess_category, unsure.guess_pct, unsure.model_asked_at = "home", 45, datetime(2026, 10, 2, tzinfo=timezone.utc)
    unknown = make_txn(db, a, date(2026, 10, 3), -900, "POS PURCHASE")
    unknown.model_asked_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
    waiting = make_txn(db, a, date(2026, 10, 4), -500, "NEW CAFE")
    db.commit()
    rows = {r["id"]: r for r in client.get("/api/b/ours/review").json()["uncategorized"]}
    assert (rows[zelle.id]["reason"], rows[zelle.id]["guess"]) == ("p2p", None)
    assert (rows[unsure.id]["reason"], rows[unsure.id]["guess"]) == ("unsure", "home")
    assert (rows[unknown.id]["reason"], rows[unknown.id]["guess"]) == ("unknown", None)
    assert (rows[waiting.id]["reason"], rows[waiting.id]["guess"]) == ("no_rule", None)    # no gateway (INS-21)


def test_a_row_waits_for_the_model_only_when_a_categorizer_is_coming(client, db, app, monkeypatch):
    from steward.services.categorizer_client import HttpModelClient
    login(client, db)
    t = make_txn(db, make_account(db), date(2026, 10, 4), -500, "NEW CAFE")
    db.commit()
    paired = HttpModelClient("http://gateway:8430/v1/categorize", 5, token="t")
    monkeypatch.setattr(app.state, "model", paired)
    app.state.advisor.monitor.health = {"categorizer": True}
    assert client.get("/api/b/ours/review").json()["uncategorized"][0]["reason"] == "waiting"
    app.state.advisor.monitor.health = {"categorizer": False}
    row = client.get("/api/b/ours/review").json()["uncategorized"][0]
    assert (row["id"], row["reason"]) == (t.id, "no_rule")
    paired.close()


def test_the_sorted_count_and_the_background_block(client, db):
    login(client, db)
    a = make_account(db)
    for i in range(3):
        make_txn(db, a, date(2026, 10, 1), -500, f"BEAN CAFE {i}", category="dining", category_source=CategorySource.model)
    checked = make_txn(db, a, date(2026, 10, 1), -500, "BEAN CAFE 9", category="dining", category_source=CategorySource.model)
    checked.reviewed_at = datetime(2026, 10, 2, tzinfo=timezone.utc)
    make_txn(db, a, date(2026, 10, 1), -500, "COSTCO", category="groceries", category_source=CategorySource.rule)
    pending = [make_txn(db, a, date(2026, 10, 3), -900, f"POS PURCHASE {i}") for i in range(2)]
    db.commit()
    r = client.get("/api/b/ours/review").json()
    assert r["sorted_count"] == 3
    assert r["background"] == {"pending": 2, "done": 0, "waiting": True, "expected": False}     # no gateway in tests
    pending[0].model_asked_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
    db.add(WatchState(key="catchup_wave", value="2026-10-03T00:00:00+00:00"))
    db.commit()
    assert client.get("/api/b/ours/review").json()["background"] == {"pending": 1, "done": 1, "waiting": True,
                                                                     "expected": False}


def test_waiting_follows_the_gateways_health(client, db, app):
    login(client, db)
    a = make_account(db)
    make_txn(db, a, date(2026, 10, 3), -900, "POS PURCHASE")
    db.commit()
    app.state.advisor.monitor.health = {"categorizer": True}
    assert client.get("/api/b/ours/review").json()["background"]["waiting"] is False
    app.state.advisor.monitor.health = {"categorizer": False}
    assert client.get("/api/b/ours/review").json()["background"]["waiting"] is True
    app.state.advisor.monitor.health = None
    assert client.get("/api/b/ours/review").json()["background"]["waiting"] is True


def test_a_categorizer_is_expected_only_from_a_paired_gateway_not_known_to_lack_one(client, db, app, monkeypatch):
    """Install gate INS-21: no gateway, or one that answers without a local model, never promises to categorize."""
    from steward.services.categorizer_client import HttpModelClient
    login(client, db)
    make_txn(db, make_account(db), date(2026, 10, 3), -900, "POS PURCHASE")
    db.commit()
    expected = lambda: client.get("/api/b/ours/review").json()["background"]["expected"]     # noqa: E731
    app.state.advisor.monitor.health = {"categorizer": True}
    assert expected() is False                                     # no paired gateway: health alone promises nothing
    paired = HttpModelClient("http://gateway:8430/v1/categorize", 5, token="t")
    monkeypatch.setattr(app.state, "model", paired)
    assert expected() is True
    app.state.advisor.monitor.health = None                        # away: it may come back with its model
    assert expected() is True
    app.state.advisor.monitor.health = {"categorizer": False}      # answers with no local model
    assert expected() is False
    paired.close()


def test_each_row_carries_how_many_other_rows_a_rule_would_reach(client, db):
    login(client, db)
    a = make_account(db)
    union = [make_txn(db, a, date(2026, 10, d), -8000, f"UNION SERVICE CENTER 00{d}") for d in (1, 2, 3)]
    lone = make_txn(db, a, date(2026, 10, 4), -500, "HARBOR GRILL 22")
    star = make_txn(db, a, date(2026, 10, 5), -100, "*ABC")
    rows = {r["id"]: r["matching"] for r in client.get("/api/b/ours/review").json()["uncategorized"]}
    assert rows == {union[0].id: 2, union[1].id: 2, union[2].id: 2, lone.id: 0, star.id: None}


def test_review_says_whether_the_book_has_any_transactions(client, db):
    """Phase 17 (spec 2.7): only a book with no transactions at all is empty; one whose rows are all transfers, or all
    sorted, is All caught up."""
    login(client, db)
    assert client.get("/api/b/ours/review").json()["empty"] is True
    a = make_account(db, "Checking")
    make_txn(db, a, date(2026, 1, 10), -50_00, "TRANSFER TO SAVINGS", is_transfer=True)
    r = client.get("/api/b/ours/review").json()
    assert r["empty"] is False and r["count"] == 0
    make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031", category="dining")
    assert client.get("/api/b/ours/review").json()["empty"] is False


def test_each_row_carries_its_note_count_never_the_notes(client, db):
    """Review cards show notes written anywhere (the transaction page, an earlier visit, the other person), so each
    queue row and each duplicate side carries its real note_count. Counts only: no note text, no author."""
    login(client, db)
    a = make_account(db, "Card", type="credit")
    noted = make_txn(db, a, date(2026, 10, 1), -4000, "PLUMBER CASH")
    plain = make_txn(db, a, date(2026, 10, 2), -900, "POS PURCHASE")
    synced = make_txn(db, a, date(2026, 1, 10), -4_50, "BEAN & LEAF 0031", category="dining", external_id="x1")
    manual = make_txn(db, a, date(2026, 1, 11), -4_50, "BEAN & LEAF 0031", category="dining")
    db.add_all([TransactionNote(transaction_id=noted.id, author_id=1, author_name="JR", body="Water heater, ask Dana"),
                TransactionNote(transaction_id=noted.id, author_id=2, author_name="Sam", body="Paid my half"),
                TransactionNote(transaction_id=manual.id, author_id=2, author_name="Sam", body="Typed in by hand")])
    db.commit()
    r = client.get("/api/b/ours/review").json()
    assert {t["id"]: t["note_count"] for t in r["uncategorized"]} == {noted.id: 2, plain.id: 0}
    assert [(p["a"]["id"], p["a"]["note_count"], p["b"]["id"], p["b"]["note_count"]) for p in r["duplicates"]] == \
        [(synced.id, 0, manual.id, 1)]
    text = json.dumps(r)
    assert not any(w in text for w in ("Water heater", "Dana", "Paid my half", "Typed in by hand", "author", "Sam"))
