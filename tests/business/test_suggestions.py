"""Review's business questions (spec 5; ruling 5): money out the model thinks is likely business, in household books
with a business, until someone answers (Review Focus 3)."""
from datetime import date

from steward.business.settings import update_settings
from steward.db.models import Transaction, TransactionNote
from tests.factories import login, make_account, make_txn


def business_on(db, frozen):
    update_settings(db, {"type": "sole_prop"}, year=2026, this_year=2026, periods=2, user_id=1, at=frozen)
    db.commit()


def test_likely_business_rows_are_asked_and_answers_stick(frozen, signed_in, db):
    business_on(db, frozen)
    card = make_account(db, "Rewards Card", type="credit")
    ask = make_txn(db, card, date(2026, 10, 3), -2_900, "NOTEFLOW PRO", category="subscriptions", business_hint=85)
    make_txn(db, card, date(2026, 10, 3), -2_900, "MAYBE APP", category="subscriptions", business_hint=59)
    make_txn(db, card, date(2026, 10, 3), 2_900, "REFUND", category="subscriptions", business_hint=90)
    make_txn(db, card, date(2024, 12, 3), -2_900, "OLD APP", category="subscriptions", business_hint=90)
    make_txn(db, card, date(2026, 10, 3), -2_900, "ALREADY", category="subscriptions", business_hint=90, is_business=True)
    second = make_txn(db, card, date(2025, 2, 3), -9_000, "COWORK DAY", category="business_expense", business_hint=95)
    q = signed_in.get("/api/b/ours/review").json()
    assert q["business_count"] == 2 and [t["id"] for t in q["business"]] == [second.id, ask.id]
    r = signed_in.post(f"/api/b/ours/business/suggestions/{ask.id}", json={"answer": "business"})
    assert r.status_code == 200 and (r.json()["business_pct"], r.json()["business_source"]) == (100, "manual")
    assert r.json()["category"] == "subscriptions"
    r = signed_in.post(f"/api/b/ours/business/suggestions/{second.id}", json={"answer": "personal"})
    assert (r.json()["business_pct"], r.json()["business_source"]) == (0, "manual")
    assert signed_in.get("/api/b/ours/review").json()["business_count"] == 0
    db.rollback()
    assert db.get(Transaction, second.id).business_answered_at is not None
    r = signed_in.post(f"/api/b/ours/business/suggestions/{ask.id}", json={"answer": "maybe"})
    assert r.status_code == 422 and r.json() == {"error": "Answer business or personal."}


def test_a_business_question_carries_its_note_count_not_its_notes(frozen, signed_in, db):
    business_on(db, frozen)
    card = make_account(db, "Rewards Card", type="credit")
    ask = make_txn(db, card, date(2026, 10, 3), -2_900, "NOTEFLOW PRO", category="subscriptions", business_hint=85)
    db.add_all([TransactionNote(transaction_id=ask.id, author_id=1, author_name="JR", body="Client deck tool"),
                TransactionNote(transaction_id=ask.id, author_id=2, author_name="Sam", body="Ask Dana")])
    db.commit()
    q = signed_in.get("/api/b/ours/review").json()
    assert [(t["id"], t["note_count"]) for t in q["business"]] == [(ask.id, 2)]
    assert "Client deck tool" not in str(q) and "Dana" not in str(q)


def test_parent_books_and_households_without_a_business_get_no_suggestions(frozen, client, db, margaret, mdb):
    login(client, "jr")
    card = make_account(db, "Rewards Card", type="credit")
    make_txn(db, card, date(2026, 10, 3), -2_900, "NOTEFLOW PRO", category="subscriptions", business_hint=85)
    q = client.get("/api/b/ours/review").json()
    assert (q["business"], q["business_count"]) == ([], 0)            # type is still "none"
    make_txn(mdb, make_account(mdb, "Checking"), date(2026, 10, 3), -2_900, "NOTEFLOW PRO",
             category="subscriptions", business_hint=85)
    q = client.get("/api/b/margaret-ellis/review").json()
    assert (q["business"], q["business_count"]) == ([], 0)
    assert client.post("/api/b/margaret-ellis/business/suggestions/1", json={"answer": "business"}).status_code == 404
