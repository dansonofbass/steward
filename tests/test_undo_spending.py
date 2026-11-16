"""The undo journal learns spending targets (kind, target, check_after; a made row is deleted) and set-asides with
their matches (made rows are deleted, matches first). Entries keep ids and figures, never a set-aside's name."""
import json
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward import clock
from steward.db.models import EventLog, SetAside, SetAsideMatch, SpendingTarget, UndoEntry
from steward.events import log_event, resolve_event
from steward.services.undo import MADE, capturing, undo
from tests.factories import make_account, make_txn

AT = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)


def test_a_changed_and_a_made_target_go_back(db):
    db.add(SpendingTarget(category="dining", kind="everyday", monthly_cents=30_000, updated_at=AT, updated_by=1))
    db.commit()
    with capturing(db, 1, "target_check", clock.now()) as cap:
        db.get(SpendingTarget, "dining").check_after = date(2027, 1, 1)
        db.add(SpendingTarget(category="giving", kind="fixed", monthly_cents=None, updated_at=AT, updated_by=1))
    db.commit()
    undo(db, cap.token, 1, clock.now())
    db.commit()
    assert db.get(SpendingTarget, "dining").check_after is None
    assert db.get(SpendingTarget, "giving") is None


def test_made_set_asides_and_their_matches_are_deleted_and_the_entry_holds_no_name(db):
    chk = make_account(db, "Checking")
    t = make_txn(db, chk, date(2026, 5, 12), -138_000, "BIG MUTUAL INS", merchant="Big Mutual", category="insurance")
    with capturing(db, 1, "set_asides", clock.now()) as cap:
        sa = SetAside(name="Zorblax insurance", kind="yearly", amount_cents=138_000, due_month=5, due_day=12,
                      first_month=date(2026, 11, 1), payee_key="BIG MUTUAL", category="insurance")
        db.add(sa)
        db.flush()
        db.add(SetAsideMatch(transaction_id=t.id, set_aside_id=sa.id, due_on=date(2026, 5, 12), how="auto"))
    db.commit()
    entry = db.get(UndoEntry, cap.token)
    assert "Zorblax" not in entry.before + entry.after
    assert json.loads(entry.before)["set_asides"] and json.loads(entry.before)["sa_matches"]
    undo(db, cap.token, 1, clock.now())
    db.commit()
    assert db.scalars(select(SetAside)).all() == [] and db.scalars(select(SetAsideMatch)).all() == []


def test_no_undo_deletes_an_event_log_row(db):
    """Audit log: an action's log lines stay through its Undo, and an event it resolved is reopened, not deleted. An
    entry written while events still counted as made rows (before["events"][id] is None) deletes nothing either."""
    assert EventLog not in MADE
    old = log_event(db, "warn", "sync", "Big Bank needs you to sign in again at SimpleFIN", actionable=True)
    db.commit()
    with capturing(db, 1, "target_check", clock.now()) as cap:
        db.add(SpendingTarget(category="giving", kind="fixed", monthly_cents=None, updated_at=AT, updated_by=1))
        line = log_event(db, "info", "spending", "JR changed Spending: Giving.")
        resolve_event(db, old.id, clock.now())
    db.commit()
    assert json.loads(db.get(UndoEntry, cap.token).before)["events"] == {str(old.id): {"resolved_at": None}}
    undo(db, cap.token, 1, clock.now())
    db.commit()
    assert db.get(SpendingTarget, "giving") is None
    assert db.get(EventLog, line.id) is not None and db.get(EventLog, old.id).resolved_at is None
    with capturing(db, 1, "set_asides", clock.now()) as cap:
        legacy = log_event(db, "info", "setaside", "JR set aside 1: Plumbing")
    db.commit()
    entry = db.get(UndoEntry, cap.token)
    before, after = json.loads(entry.before), json.loads(entry.after)
    before["events"], after["events"] = {str(legacy.id): None}, {str(legacy.id): {"resolved_at": None}}
    entry.before, entry.after = json.dumps(before), json.dumps(after)
    db.commit()
    undo(db, cap.token, 1, clock.now())
    db.commit()
    assert db.get(EventLog, legacy.id) is not None
