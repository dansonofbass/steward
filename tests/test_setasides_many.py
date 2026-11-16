"""POST /setasides/many (P26): up to 50 set-asides in one write and one Undo, all or nothing, matched for the new ones
only; Undo deletes them and the matches made for them, and refuses once something newer points at one."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import EventLog, SetAside, SetAsideMatch
from tests.factories import make_account, make_txn

OCT_25 = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)
PROPERTY = {"name": "Property tax", "kind": "twice_yearly", "amount_cents": 421_000, "due_month": 4, "due_day": 10,
            "second_month": 10, "second_day": 10, "payee_key": "COUNTY TAX COLLECTOR", "category": "taxes"}
MUTUAL = {"name": "Big Mutual", "kind": "yearly", "amount_cents": 138_000, "due_month": 5, "due_day": 12,
          "payee_key": "BIG MUTUAL", "category": "insurance"}


@pytest.fixture
def oct25(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: OCT_25)


def book(db):
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 4, 10), -421_000, "COUNTY TAX COLLECTOR", merchant="County Tax Collector", category="taxes")
    make_txn(db, chk, date(2025, 5, 9), -132_000, "BIG MUTUAL INS", merchant="Big Mutual", category="insurance")
    make_txn(db, chk, date(2026, 5, 12), -138_000, "BIG MUTUAL INS", merchant="Big Mutual", category="insurance")
    return chk


def fresh(db):
    db.rollback()
    db.expire_all()


def test_many_makes_them_all_with_one_event_and_one_undo(oct25, signed_in, db):
    book(db)
    r = signed_in.post("/api/b/ours/setasides/many", json={"items": [PROPERTY, MUTUAL]})
    assert r.status_code == 201
    body = r.json()
    assert len(body["ids"]) == 2 and body["monthly_cents"] == 70_167 + 11_500 and body["undo"]
    fresh(db)
    assert sorted(s.name for s in db.scalars(select(SetAside))) == ["Big Mutual", "Property tax"]
    assert len(db.scalars(select(SetAsideMatch)).all()) == 3          # April's county payment, and both Big Mutual years
    assert [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside"))] == [
        "JR set aside 2: Property tax, $4,210 twice a year, Apr 10 and Oct 10; Big Mutual, $1,380 a year, due May 12; "
        "matched 3 payments"]
    assert signed_in.post(f"/api/b/ours/undo/{body['undo']}").status_code == 200
    fresh(db)
    assert db.scalars(select(SetAside)).all() == [] and db.scalars(select(SetAsideMatch)).all() == []


def test_many_is_all_or_nothing_and_capped_at_50(oct25, signed_in, db):
    book(db)
    post = lambda body: signed_in.post("/api/b/ours/setasides/many", json=body)   # noqa: E731
    r = post({"items": [PROPERTY, {**MUTUAL, "due_month": 13}]})
    assert r.status_code == 422 and r.json() == {"error": "Choose a month from 1 to 12."}
    r = post({"items": [{**MUTUAL, "account_id": 999}]})
    assert r.status_code == 422 and r.json() == {"error": "Choose a checking or savings account."}
    r = post({"items": [MUTUAL] * 51})
    assert r.status_code == 422 and r.json() == {"error": "Set aside up to 50 at a time."}
    for body in ({}, {"items": []}, {"items": "x"}):
        assert post(body).status_code == 422
    fresh(db)
    assert db.scalars(select(SetAside)).all() == []


def test_undoing_many_after_a_hand_match_is_refused(oct25, signed_in, db):
    chk = book(db)
    plumber = make_txn(db, chk, date(2026, 9, 20), -40_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    r = signed_in.post("/api/b/ours/setasides/many", json={"items": [
        {"name": "Plumbing", "kind": "yearly", "amount_cents": 40_000, "due_month": 9, "due_day": 25}]})
    sa_id = r.json()["ids"][0]
    m = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": plumber.id, "set_aside_id": sa_id})
    assert m.status_code == 200
    u = signed_in.post(f"/api/b/ours/undo/{r.json()['undo']}")
    assert u.status_code == 409 and u.json() == {"error": "That changed since, so it can't be undone."}
    fresh(db)
    assert db.get(SetAside, sa_id) is not None


def test_many_matches_the_new_set_asides_only(oct25, signed_in, db):
    """An older set-aside's open installment isn't filled by this write, so Undo can't take a match it was owed."""
    book(db)
    db.add(SetAside(name="Old county", kind="yearly", amount_cents=421_000, due_month=4, due_day=10,
                    first_month=date(2026, 1, 1), payee_key="COUNTY TAX COLLECTOR", category="taxes",
                    created_at=OCT_25, updated_at=OCT_25))
    db.commit()
    r = signed_in.post("/api/b/ours/setasides/many", json={"items": [MUTUAL]})
    assert r.status_code == 201
    fresh(db)
    old = db.scalar(select(SetAside).where(SetAside.name == "Old county"))
    assert db.scalars(select(SetAsideMatch).where(SetAsideMatch.set_aside_id == old.id)).all() == []


def test_undoing_many_leaves_its_log_line(oct25, signed_in, db):
    book(db)
    r = signed_in.post("/api/b/ours/setasides/many", json={"items": [PROPERTY, MUTUAL]})
    fresh(db)
    lines = [(e.id, e.message) for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside"))]
    assert len(lines) == 1
    assert signed_in.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    fresh(db)
    assert db.scalars(select(SetAside)).all() == []
    assert [(e.id, e.message) for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside"))] == lines
