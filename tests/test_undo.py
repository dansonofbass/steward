"""Undo (sorting redesign spec, Undo): an action's rows, the transfer peers pairing touched and the rule are captured
in its own transaction; POST /undo/{token} restores them all or nothing. 409 when a row changed since, 410 when used or
expired, 404 for an unknown token or another person's, 403 for a viewer."""

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

import steward.api.undo as undo_api
from steward import clock
from steward.db.directory_models import User
from steward.db.models import (CategorySource, ChangeRecord, MerchantRule, ReimburseRule, ReimburseSettlement,
                               Reimburser, Transaction, Trip, UndoEntry)
from steward.deps import VIEWER_COPY
from steward.services.category_rules import spread
from steward.services.transactions import apply_correction
from steward.services.undo import CHANGED_SINCE, GONE, NO_UNDO, UndoRefused, capturing, undo
from tests.factories import login, make_account, make_person, make_txn, make_user

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry
D =date(2026, 10, 3)


def _now() -> datetime:
    return clock.now()


def _sort(db, t, category, *, apply=False, user_id=1, at=None):
    """A person's sort as the PATCH route will make it (Task 4): the correction, the rule, and with apply the spread."""
    at = at or _now()
    with capturing(db, user_id, "sort", at) as cap:
        cap.target = t.id
        rule = apply_correction(db, t, None, category, None, at)
        if apply and rule is not None:
            spread(db, rule, at)
    db.commit()
    return cap.token


def test_undo_restores_the_row_every_matching_row_and_removes_a_made_rule(db):
    a = make_account(db)
    t = make_txn(db, a, D, -8000, "UNION SERVICE CENTER 0041")
    others = [make_txn(db, a, date(2026, 9, d), -8000, f"UNION SERVICE CENTER 00{d}", category="shopping",
                       category_source=CategorySource.model) for d in (3, 4)]
    token = _sort(db, t, "home", apply=True)
    assert db.scalar(select(MerchantRule).where(MerchantRule.pattern == "UNION SERVICE CENTER")) is not None
    done = undo(db, token, 1, _now())
    db.commit()
    assert done.count == 3 and done.target.id == t.id
    db.expire_all()
    assert (t.category, t.category_source, t.reviewed_at, t.merchant) == ("uncategorized", CategorySource.none, None, None)
    for o in others:
        assert (o.category, o.category_source, o.reviewed_at, o.merchant) == ("shopping", CategorySource.model, None, None)
    assert db.scalars(select(MerchantRule)).all() == []


def test_undo_puts_a_changed_rule_back(db):
    a = make_account(db)
    db.add(MerchantRule(pattern="HARBOR GRILL", merchant="Harbor Grill", category="dining", is_business=None,
                        source=CategorySource.correction))
    db.commit()
    t = make_txn(db, a, D, -2500, "HARBOR GRILL 22")
    token = _sort(db, t, "entertainment")
    assert db.scalar(select(MerchantRule)).category == "entertainment"
    undo(db, token, 1, _now())
    db.commit()
    db.expire_all()
    r = db.scalar(select(MerchantRule))
    assert (r.category, r.merchant) == ("dining", "Harbor Grill") and t.category == "uncategorized"


def test_undo_unpairs_the_peer_a_transfer_paired(db):
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE EPAY 0042")
    back = make_txn(db, card, date(2026, 10, 7), 40000, "PAYMENT RECEIVED")
    token = _sort(db, out, "transfer")
    db.expire_all()
    assert (out.transfer_peer_id, back.transfer_peer_id, back.category) == (back.id, out.id, "transfer")
    undo(db, token, 1, _now())
    db.commit()
    db.expire_all()
    assert (out.is_transfer, out.transfer_peer_id, out.category) == (False, None, "uncategorized")
    assert (back.is_transfer, back.transfer_peer_id, back.category, back.category_source) == (
        False, None, "uncategorized", CategorySource.none)


def test_undo_restores_the_peer_a_sort_sent_back_to_review(db):
    """unpair_peers writes the peer with a bulk UPDATE, which the session's history never sees (choice 1)."""
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, D, -50000, "TRANSFER TO SAVINGS", category="transfer", is_transfer=True,
                   category_source=CategorySource.rule)
    into = make_txn(db, sav, D, 50000, "TRANSFER FROM CHECKING", category="transfer", is_transfer=True,
                    category_source=CategorySource.rule)
    out.transfer_peer_id, into.transfer_peer_id = into.id, out.id
    db.commit()
    token = _sort(db, out, "groceries")          # not a transfer after all: its other side goes back to Review
    db.expire_all()
    assert (into.transfer_peer_id, into.category) == (None, "uncategorized")
    undo(db, token, 1, _now())
    db.commit()
    db.expire_all()
    assert (out.category, out.transfer_peer_id, out.is_transfer) == ("transfer", into.id, True)
    assert (into.category, into.transfer_peer_id, into.is_transfer, into.category_source) == (
        "transfer", out.id, True, CategorySource.rule)
    assert db.scalars(select(MerchantRule)).all() == []


def test_expired_entries_go_when_the_next_one_is_made(db):
    a = make_account(db)
    t1, t2 = make_txn(db, a, D, -100, "ONE SHOP"), make_txn(db, a, D, -100, "TWO SHOP")
    old = _sort(db, t1, "home", at=_now() - timedelta(minutes=20))
    new = _sort(db, t2, "gifts")
    assert db.get(UndoEntry, old) is None and [e.token for e in db.scalars(select(UndoEntry))] == [new]


def test_snooze_and_ignore_answer_an_undo_token_and_undo_puts_the_row_back(client, db):
    make_user(db)
    login(client, "jr")
    t = make_txn(db, make_account(db), D, -900, "MYSTERY")
    r = client.post(f"/api/b/ours/review/{t.id}/snooze")
    assert r.status_code == 200 and set(r.json()) == {"undo", "until"}
    db.rollback()
    assert r.json()["until"] == db.get(Transaction, t.id).snoozed_until.astimezone(clock.household_tz()).date().isoformat()
    u = client.post(f"/api/b/ours/undo/{r.json()['undo']}")
    assert u.status_code == 200 and u.json()["undone"] == 1 and u.json()["transaction"]["id"] == t.id
    db.rollback()
    assert db.get(Transaction, t.id).snoozed_until is None
    r = client.post(f"/api/b/ours/review/{t.id}/ignore")
    assert r.status_code == 200 and set(r.json()) == {"undo"}
    assert client.post(f"/api/b/ours/undo/{r.json()['undo']}").status_code == 200
    db.rollback()
    assert db.get(Transaction, t.id).reviewed_at is None


def test_undo_is_all_or_nothing_and_409_when_a_row_changed_since(client, db):
    jr = make_user(db)
    login(client, "jr")
    a = make_account(db)
    t = make_txn(db, a, D, -8000, "UNION SERVICE CENTER 0041")
    o = make_txn(db, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    token = _sort(db, t, "home", apply=True, user_id=jr.id)
    o.category = "gifts"                                        # someone changed one of the matching rows since
    db.commit()
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (409, {"error": CHANGED_SINCE})
    db.rollback()
    assert t.category == "home" and o.category == "gifts" and db.scalar(select(MerchantRule)) is not None
    assert db.get(UndoEntry, token).used_at is None


def test_a_second_undo_is_410_and_restores_nothing_twice(client, db):
    """Review Focus 1: a double tap, or a second tab, after the first already restored."""
    jr = make_user(db)
    login(client, "jr")
    t = make_txn(db, make_account(db), D, -2500, "HARBOR GRILL 22")
    token = _sort(db, t, "dining", user_id=jr.id)
    assert client.post(f"/api/b/ours/undo/{token}").status_code == 200
    db.rollback()
    _sort(db, db.get(Transaction, t.id), "gifts", user_id=jr.id)  # sorted again meanwhile
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (410, {"error": GONE})
    db.rollback()
    assert db.get(Transaction, t.id).category == "gifts"


def test_an_expired_undo_is_410_and_an_unknown_or_someone_elses_is_404(client, db, monkeypatch):
    jr = make_user(db)
    login(client, "jr")
    a = make_account(db)
    t1, t2 = make_txn(db, a, D, -100, "ONE SHOP"), make_txn(db, a, D, -100, "TWO SHOP")
    late = _sort(db, t1, "home", user_id=jr.id)
    theirs = _sort(db, t2, "gifts", user_id=jr.id + 1000)
    monkeypatch.setattr(undo_api, "now", lambda: _now() + timedelta(minutes=16))
    assert client.post(f"/api/b/ours/undo/{late}").status_code == 410
    monkeypatch.undo()
    for token in ("nope", "x" * 200, theirs):
        r = client.post(f"/api/b/ours/undo/{token}")
        assert (r.status_code, r.json()) == (404, {"error": NO_UNDO}), token


def test_a_viewer_cannot_undo(client, db, ddb, ours):
    t = make_txn(db, make_account(db), D, -100, "ONE SHOP")
    token = _sort(db, t, "home")
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    r = client.post(f"/api/b/ours/undo/{token}")
    assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY})


def test_an_undo_in_a_parent_book_is_recorded(margaret, mdb, client, ddb):
    jr = ddb.scalar(select(User.id).where(User.username == "jr"))
    login(client, "jr")
    t = make_txn(mdb, make_account(mdb), D, -8000, "OAKHAVEN PHARMACY")
    token = _sort(mdb, t, "health", user_id=jr)
    assert client.post(f"/api/b/margaret-ellis/undo/{token}").status_code == 200
    mdb.rollback()
    assert [r.action for r in mdb.scalars(select(ChangeRecord))] == ["txn.undo"]
    row = client.get("/api/b/margaret-ellis/changes", params={"kind": "transactions"}).json()["changes"][0]
    assert row["text"] == "undid a change to a transaction"


def _payers(db):
    acme, globex = Reimburser(name="Acme"), Reimburser(name="Globex")
    db.add_all([acme, globex])
    db.commit()
    return acme, globex


def test_undo_restores_the_reimbursable_columns(db):
    acme, _ = _payers(db)
    trip = Trip(name="Chicago trip", start=D, end=D, reimburser_id=acme.id)
    db.add(trip)
    db.commit()
    t = make_txn(db, make_account(db), D, -40_000, "HILTON CHICAGO IL")
    with capturing(db, 1, "trip", _now()) as cap:
        t.reimburser_id, t.trip_id, t.reimburse_source = acme.id, trip.id, "manual"
    db.commit()
    assert undo(db, cap.token, 1, _now()).count == 1
    db.commit()
    db.expire_all()
    assert (t.reimburser_id, t.trip_id, t.reimburse_source) == (None, None, "none")


def test_undo_removes_what_the_action_made_and_puts_a_changed_rule_back(db):
    acme, globex = _payers(db)
    kept = ReimburseRule(pattern="HILTON", reimburser_id=acme.id)
    db.add(kept)
    db.commit()
    with capturing(db, 1, "settle", _now()) as cap:
        db.add(ReimburseSettlement(reimburser_id=acme.id, amount_cents=6_035, category="travel", settled_at=_now()))
        db.add(ReimburseRule(pattern="UNITED AIRLINES", reimburser_id=acme.id))
        kept.reimburser_id = globex.id
    db.commit()
    assert undo(db, cap.token, 1, _now()).count == 0
    db.commit()
    db.expire_all()
    assert db.scalars(select(ReimburseSettlement)).all() == []
    assert [(r.pattern, r.reimburser_id) for r in db.scalars(select(ReimburseRule))] == [("HILTON", acme.id)]


def test_a_reimburse_rule_changed_since_is_409_and_nothing_changes(db):
    acme, globex = _payers(db)
    t = make_txn(db, make_account(db), D, -40_000, "UNITED AIRLINES")
    with capturing(db, 1, "sort", _now()) as cap:
        t.reimburser_id = acme.id
        db.add(ReimburseRule(pattern="UNITED AIRLINES", reimburser_id=acme.id))
    db.commit()
    db.scalar(select(ReimburseRule)).reimburser_id = globex.id
    db.commit()
    with pytest.raises(UndoRefused) as e:
        undo(db, cap.token, 1, _now())
    assert e.value.status == 409
    db.rollback()
    db.expire_all()
    assert t.reimburser_id == acme.id and db.scalar(select(ReimburseRule)).reimburser_id == globex.id


def test_an_entry_from_before_the_new_columns_still_undoes(db):
    """Choice 9: the compare and the restore cover the fields an entry recorded, so a sort made just before the deploy
    can still be undone after it."""
    t = make_txn(db, make_account(db), D, -100, "ONE SHOP")
    token = _sort(db, t, "home")
    e = db.get(UndoEntry, token)
    before, after = json.loads(e.before), json.loads(e.after)
    for side in (before["txns"], after["txns"]):
        for vals in side.values():
            for f in ("reimburser_id", "trip_id", "reimburse_source"):
                vals.pop(f)
    for side in (before, after):
        side.pop("reimburse_rules")
        side.pop("settlements")
    e.before, e.after = json.dumps(before), json.dumps(after)
    db.commit()
    undo(db, token, 1, _now())
    db.commit()
    db.expire_all()
    assert t.category == "uncategorized"
