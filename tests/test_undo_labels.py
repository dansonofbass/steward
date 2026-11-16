"""Undo for names and notes (P36): the old text goes to undo_text, keyed by the entry's token, never into undo_entry;
made notes are deleted by id; Undo refuses once the text changed since; a rule the action deleted comes back with its
name and note; undo_text goes when its entry is used or expires."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from steward import clock
from steward.db.models import CategorySource, MerchantRule, TransactionNote, UndoEntry, UndoText
from steward.services.undo import CHANGED_SINCE, UndoRefused, capturing, undo
from tests.factories import make_account, make_txn

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry
SECRETS = ("Disney+", "Old name", "Alvarez", "zorblax")


def setup(db):
    t = make_txn(db, make_account(db), date(2026, 10, 3), -1399, "PAYPAL *DISNEYPLUS", merchant="PayPal")
    rule = MerchantRule(pattern="PAYPAL", merchant="PayPal", category="shopping", source=CategorySource.correction)
    db.add(rule)
    t.nickname = "Old name"
    db.commit()
    return t, rule


def label(db, t, rule, at=None):
    with capturing(db, 1, "label", at or clock.now()) as cap:
        cap.keep_text("txn", t, "nickname", t.nickname, "Disney+")
        t.nickname = "Disney+"
        cap.keep_text("rule", rule, "note", rule.note, "for Dr. Alvarez")
        rule.note = "for Dr. Alvarez"
        db.add(TransactionNote(transaction_id=t.id, author_id=1, author_name="JR", body="zorblax", created_at=clock.now()))
    db.commit()
    return cap.token


def test_text_fields_go_to_undo_text_and_come_back(db):
    t, rule = setup(db)
    token = label(db, t, rule)
    entry = db.get(UndoEntry, token)
    assert not any(s in entry.before + entry.after for s in SECRETS)
    assert sorted((x.model, x.field, x.value, x.written) for x in db.scalars(select(UndoText).where(UndoText.token == token))) == [
        ("rule", "note", None, "for Dr. Alvarez"), ("txn", "nickname", "Old name", "Disney+")]
    undo(db, token, 1, clock.now())
    db.commit()
    db.expire_all()
    assert (t.nickname, rule.note) == ("Old name", None)
    assert db.scalars(select(TransactionNote)).all() == []
    assert db.scalars(select(UndoText).where(UndoText.token == token)).all() == []


def test_undo_refuses_once_a_name_changed_since(db):
    t, rule = setup(db)
    token = label(db, t, rule)
    t.nickname = "Someone else's name"
    db.commit()
    with pytest.raises(UndoRefused) as e:
        undo(db, token, 1, clock.now())
    assert (e.value.status, e.value.message) == (409, CHANGED_SINCE)


def test_a_deleted_names_only_rule_comes_back_with_its_name_and_note(db):
    rule = MerchantRule(pattern="PAYPAL", merchant="PayPal", category=None, amount_cents=-1399, nickname="Disney+",
                        note="for Dr. Alvarez", note_by=1, note_by_name="JR", source=CategorySource.correction)
    db.add(rule)
    db.commit()
    rid = rule.id
    with capturing(db, 1, "label", clock.now()) as cap:
        for f in ("nickname", "note", "note_by", "note_by_name"):
            cap.keep_text("rule", rule, f, getattr(rule, f), None)
        db.delete(rule)
    db.commit()
    assert db.get(MerchantRule, rid) is None
    undo(db, cap.token, 1, clock.now())
    db.commit()
    r = db.get(MerchantRule, rid)
    assert (r.pattern, r.amount_cents, r.category, r.nickname, r.note, r.note_by, r.note_by_name) == (
        "PAYPAL", -1399, None, "Disney+", "for Dr. Alvarez", 1, "JR")


def test_undo_text_goes_when_its_entry_expires(db):
    t, rule = setup(db)
    first = label(db, t, rule)
    with capturing(db, 1, "label", clock.now() + timedelta(minutes=16)) as cap:   # the next entry purges the expired one
        t.merchant = "PayPal Inc"
    db.commit()
    assert db.get(UndoEntry, first) is None
    assert db.scalars(select(UndoText).where(UndoText.token == first)).all() == []
    assert cap.token
