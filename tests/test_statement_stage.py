"""Staged statements (spec P3-P5, P34, P36): book-wide, seven days from the last change with a day-6 event, a cleared
name for seven more, Remove's ten minutes; row review's operations, bounded, with the gap recomputed; the account
suggestion order."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from steward.db.models import AccountFeed, EventLog, ImportHint, Institution, Source, StatementStage, UndoEntry
from steward.services.statements import stage as S
from tests.factories import make_account

NOW = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)
STATEMENT = {"kind": "card", "institution": "Summit Card Services", "last4": "4417", "period": ["2026-03-01", "2026-03-31"],
             "opening_cents": 10000, "closing_cents": 11000, "sections": [{"title": "PURCHASE", "way": "out",
                                                                          "total_cents": -1000}],
             "unreadable": [], "opening_label": "Previous Balance", "closing_label": "New Balance"}


def _staged(db, now=NOW, sha="a" * 64, rows=None, state="off"):
    s = S.add(db, user_id=1, filename="Statement_0324.pdf", size=1000, sha=sha, now=now)
    s.state, s.pages = state, 2
    s.statement = json.dumps(STATEMENT)
    s.rows = json.dumps(rows if rows is not None else [
        {"date": "2026-03-04", "description": "DUNMORE DELI", "amount_cents": -400, "page": 1, "section": "PURCHASE",
         "state": "read"},
        {"date": "2026-03-09", "description": "QUILLFEATHER BOOKS", "amount_cents": -1000, "page": 2,
         "section": "PURCHASE", "state": "read"}])
    s.gap_cents = S.regap(s)
    db.commit()
    return s


def test_expiry_is_seven_days_from_the_last_change(db, fake_clock):
    s = _staged(db)
    assert s.expires_at == NOW + timedelta(days=7)
    S.sweep(db, NOW + timedelta(days=7) - timedelta(seconds=1))
    assert s.state == "off"
    S.sweep(db, NOW + timedelta(days=7))
    db.commit()
    assert (s.state, s.rows, s.lines, s.statement, s.holdings) == ("cleared", None, None, None, None)
    assert db.scalar(select(EventLog.message).where(EventLog.kind == "import", EventLog.actionable.is_(False))) == \
        "1 statement waiting to import was cleared after a week."


def test_a_change_moves_the_expiry(db):
    s = _staged(db)
    S.touch(s, NOW + timedelta(days=5))
    assert s.expires_at == NOW + timedelta(days=12)


def test_the_day_six_event_comes_once_and_says_the_day(db):
    _staged(db)
    _staged(db, sha="b" * 64)
    S.sweep(db, NOW + timedelta(days=6))
    S.sweep(db, NOW + timedelta(days=6, hours=1))
    db.commit()
    events = db.scalars(select(EventLog).where(EventLog.actionable.is_(True))).all()
    assert [(e.kind, e.message) for e in events] == [("import", "2 statements waiting to import go on Nov 6.")]


def test_a_cleared_name_stays_seven_more_days(db):
    s = _staged(db)
    S.sweep(db, NOW + timedelta(days=7))
    S.sweep(db, NOW + timedelta(days=14) - timedelta(seconds=1))
    db.commit()
    assert db.get(StatementStage, s.id) is not None
    S.sweep(db, NOW + timedelta(days=14))
    db.commit()
    assert db.get(StatementStage, s.id) is None


def test_a_removed_line_goes_after_ten_minutes(db):
    s = _staged(db)
    s.removed_at = NOW
    db.commit()
    S.sweep(db, NOW + timedelta(minutes=9))
    assert db.get(StatementStage, s.id) is not None
    S.sweep(db, NOW + timedelta(minutes=10))
    db.commit()
    assert db.get(StatementStage, s.id) is None


def test_row_ops_recompute_the_gap_and_never_write_undo(db):
    s = _staged(db)
    assert s.gap_cents == -400                          # card: (11000 - 10000) + (-1400) = -400
    before = db.scalar(select(UndoEntry.token).limit(1))
    S.apply_ops(s, [{"op": "remove", "i": 0}], pages=2)
    assert S.regap(s) == 0 and S.rows_of(s)[0]["state"] == "removed"
    S.apply_ops(s, [{"op": "restore", "i": 0}, {"op": "edit", "i": 1, "amount_cents": -600}], pages=2)
    assert S.regap(s) == 0 and S.rows_of(s)[1]["state"] == "edited"
    S.apply_ops(s, [{"op": "add", "date": "2026-03-20", "description": "WIRE FEE", "amount_cents": -100, "page": 2}], pages=2)
    assert S.regap(s) == -100 and S.rows_of(s)[2]["state"] == "added"
    db.commit()
    assert db.scalar(select(UndoEntry.token).limit(1)) == before
    assert S.sections_of(s) == [{"title": "PURCHASE", "rows": 2, "sum_cents": -1000, "total_cents": -1000}]


@pytest.mark.parametrize("ops", [
    [{"op": "remove", "i": 0}] * 2,                                              # an index twice
    [{"op": "edit", "i": 9, "amount_cents": 1}],                                 # out of range
    [{"op": "edit", "i": True, "amount_cents": 1}],
    [{"op": "edit", "i": 0, "date": "2026-05-20"}],                              # outside the period by more than 7 days
    [{"op": "edit", "i": 0, "description": "x" * 201}],
    [{"op": "edit", "i": 0, "description": "  "}],
    [{"op": "edit", "i": 0, "amount_cents": 10**14}],
    [{"op": "add", "date": "2026-03-20", "description": "A", "amount_cents": 1, "page": 3}],   # no page 3
    [{"op": "drop", "i": 0}],
    [{"op": "remove", "i": 0}] + [{"op": "add", "date": "2026-03-20", "description": "A", "amount_cents": 1}] * 100,
    "not a list"])
def test_bad_ops_are_refused_and_change_nothing(db, ops):
    s = _staged(db)
    rows = s.rows
    with pytest.raises(S.OpsRefused):
        S.apply_ops(s, ops, pages=2)
    assert s.rows == rows


def test_rows_never_pass_two_thousand(db):
    s = _staged(db, rows=[{"date": "2026-03-04", "description": "A", "amount_cents": -1, "page": 1, "section": None,
                           "state": "read"}] * 1999)
    S.apply_ops(s, [{"op": "add", "date": "2026-03-04", "description": "B", "amount_cents": -1}], pages=2)
    with pytest.raises(S.OpsRefused):
        S.apply_ops(s, [{"op": "add", "date": "2026-03-04", "description": "C", "amount_cents": -1}], pages=2)


def _accounts(db):
    chase = Institution(name="Summit Card Services", source=Source.simplefin)
    db.add(chase)
    db.flush()
    card = make_account(db, "Mom's card", type="credit", source="simplefin", institution_name="Summit Card Services")
    other = make_account(db, "Checking 4417", type="checking")
    fed = make_account(db, "Travel card", type="credit")
    db.add(AccountFeed(account_id=fed.id, external_id="sfin:1", institution_id=chase.id, name="SUMMIT VISA ...5521"))
    db.commit()
    return card, other, fed


def test_the_suggestion_order_hint_digits_layout_name(db):
    card, other, fed = _accounts(db)
    assert S.hint_key("Summit Card Services", "4417") == "pdf:summit card services:4417"
    db.add(ImportHint(key="pdf:summit card services:4417", account_id=card.id, updated_at=NOW))
    db.commit()
    assert S.suggest(db, "card", "Summit Card Services", "4417", None) == (card.id, "hint")
    assert S.suggest(db, "card", "Summit Card Services", "5521", None) == (fed.id, "digits")        # a feed's name
    assert S.suggest(db, "bank", "Elsewhere", "4417", None) == (other.id, "digits")
    assert S.suggest(db, "card", "Elsewhere", "9999", card.id) == (card.id, "layout")
    assert S.suggest(db, "card", "Summit Card Services", None, None) == (card.id, "name")
    assert S.suggest(db, "bank", "Nobody Bank", None, None) == (None, None)


def test_line_out_says_who_added_it_and_hides_full_numbers(db):
    s = _staged(db, state="ready")
    line = S.line_out(s, {1: "Jane", 2: "JR"}, me=2, imported=None)
    assert (line["name"], line["added_by"], line["state"], line["rows"], line["last4"], line["label"]) == \
        ("Statement_0324.pdf", "Jane", "ready", 2, "4417", "Summit Card Services")
    assert S.line_out(s, {1: "Jane"}, me=1, imported="2026-10-12")["added_by"] is None
    assert S.line_out(s, {1: "Jane"}, me=1, imported="2026-10-12")["imported_before"] == "2026-10-12"
