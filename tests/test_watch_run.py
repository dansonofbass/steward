"""The checks run after every sync and import over transactions not checked before (spec 4.1). Spec 11: Expected
silences repeats, and a changed threshold never rechecks old transactions. Rulings 2 (no flood) and 15."""
import json
from datetime import timedelta

from sqlalchemy import func, select

from steward.db.models import EventLog, FlagEvent, InventoryItem, MailOutbox, Transaction, WatchKnown
from steward.inventory.accounts import parent_hook
from steward.watch.run import run_watch
from steward.watch.store import LARGE, LAST_RUN, get_state, set_state
from tests.factories import login
from tests.watch_helpers import NOW, TODAY, account, flags, history, txn

BOOK = "/api/b/margaret-ellis"


def test_one_flag_per_transaction_with_what_else_matched(margaret, mdb):
    a = account(mdb)
    history(mdb, a)
    txn(mdb, a, 30, -2347, "CVS/PHARMACY #04411 BREA CA", watched=True)
    gift = txn(mdb, a, 2, -50_000, "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA", category="shopping")
    out = run_watch(mdb, TODAY, NOW, after="sync")
    mdb.commit()
    [f] = flags(mdb)
    assert (f.check, f.severity, f.status, f.transaction_id) == ("scam", "urgent", "open", gift.id)
    assert (f.summary, f.title) == ("$500.00 gift card at CVS Pharmacy", "$500.00 gift card at CVS Pharmacy")
    assert json.loads(f.also) == [{"check": "large", "detail": "$500.00 or more"}]
    facts = json.loads(f.facts)
    assert facts["account"] == "Joint checking" and facts["raw"] == "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA"
    assert facts["posted_at"] == "2026-10-17" and facts["amount_cents"] == 50_000 and facts["payee"] == "CVS Pharmacy"
    assert f.account_id == a.id and f.item_id == mdb.scalar(select(InventoryItem.id).where(InventoryItem.account_id == a.id))
    [event] = mdb.scalars(select(FlagEvent)).all()
    assert (event.kind, json.loads(event.detail)) == ("flagged", {"after": "sync"})
    [mail] = mdb.scalars(select(MailOutbox)).all()
    assert (mail.kind, mail.flag_id, mail.status, mail.next_try_at) == ("urgent", f.id, "pending", NOW)
    assert (out.checked, out.accounts, out.flags) == (1, 1, [f.id])
    assert json.loads(get_state(mdb, LAST_RUN)) == {"at": NOW.isoformat(), "after": "sync", "transactions": 1,
                                                    "accounts": 1}


def test_checks_never_run_twice_and_a_new_threshold_applies_to_new_transactions(margaret, mdb):
    a = account(mdb)
    history(mdb, a)
    txn(mdb, a, 100, -1000, "BREA FAMILY DENTAL", category="health", watched=True)
    old = txn(mdb, a, 5, -20_000, "BREA FAMILY DENTAL", category="health")
    run_watch(mdb, TODAY, NOW, after="sync")
    mdb.commit()
    assert flags(mdb) == []
    mdb.refresh(old)
    assert old.watched_at == NOW
    set_state(mdb, LARGE, "10000", NOW)                    # $100.00
    run_watch(mdb, TODAY, NOW + timedelta(hours=1), after="sync")
    mdb.commit()
    assert flags(mdb) == []                               # the $200 already seen is not checked again
    new = txn(mdb, a, 1, -20_000, "BREA FAMILY DENTAL", category="health")
    run_watch(mdb, TODAY, NOW + timedelta(hours=2), after="sync")
    mdb.commit()
    assert [(f.transaction_id, f.check, f.summary) for f in flags(mdb)] == [(new.id, "large", "$200.00 to Brea Family Dental")]


def test_a_known_payee_silences_repeats_within_its_band(margaret, mdb):
    a = account(mdb)
    history(mdb, a)
    txn(mdb, a, 100, -1000, "BREA FAMILY DENTAL", category="health", watched=True)
    mdb.add(WatchKnown(payee_key="BREA FAMILY DENTAL", payee_name="Brea Family Dental", low_cents=48_000,
                       high_cents=80_000, check="large", added_at=NOW, added_by=1))
    mdb.commit()
    txn(mdb, a, 3, -64_000, "BREA FAMILY DENTAL", category="health")
    run_watch(mdb, TODAY, NOW, after="sync")
    assert flags(mdb) == []
    big = txn(mdb, a, 1, -90_000, "BREA FAMILY DENTAL", category="health")
    run_watch(mdb, TODAY, NOW, after="sync")
    assert [(f.transaction_id, f.check) for f in flags(mdb)] == [(big.id, "large")]


def test_a_backfill_raises_nothing_for_old_transactions(margaret, mdb):
    a = account(mdb)
    history(mdb, a, 400)
    old = txn(mdb, a, 90, -60_000, "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA")
    out = run_watch(mdb, TODAY, NOW, after="import")
    mdb.commit()
    assert flags(mdb) == [] and out.checked == 0
    mdb.refresh(old)
    assert old.watched_at == NOW                          # marked checked, never looked at again


def test_a_young_book_waits_before_calling_anyone_new(margaret, mdb):
    a = account(mdb)
    txn(mdb, a, 40, 100_000, "OPENING DEPOSIT", category="income")
    txn(mdb, a, 3, -15_000, "ZELLE TO ROSA DELGADO ON 10/16")
    run_watch(mdb, TODAY, NOW, after="sync")
    assert flags(mdb) == []
    txn(mdb, a, 2, -2500, "GOOGLE PLAY GIFT CARD 123")    # a scam needs no history
    run_watch(mdb, TODAY, NOW, after="sync")
    assert [f.check for f in flags(mdb)] == ["scam"]


def test_a_transaction_dated_after_today_waits_for_its_day(margaret, mdb):
    a = account(mdb)
    history(mdb, a)
    later = txn(mdb, a, -2, -2500, "GOOGLE PLAY GIFT CARD 123")
    run_watch(mdb, TODAY, NOW, after="sync")
    mdb.commit()
    mdb.refresh(later)
    assert flags(mdb) == [] and later.watched_at is None
    run_watch(mdb, TODAY + timedelta(days=2), NOW + timedelta(days=2), after="daily")
    assert [f.transaction_id for f in flags(mdb)] == [later.id]


def test_the_parent_hook_runs_the_checks_after_a_sync(frozen, margaret, mdb):
    a = account(mdb)
    history(mdb, a)
    txn(mdb, a, 8, -2500, "GOOGLE PLAY GIFT CARD 123")    # Oct 11, before the frozen today (Oct 13)
    parent_hook("parent")(mdb)
    mdb.commit()
    assert [f.check for f in flags(mdb)] == ["scam"]


def test_a_failing_check_run_is_logged_and_keeps_the_inventory_update(frozen, margaret, mdb, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr("steward.watch.run.run_watch", boom)
    account(mdb, item=False)                              # the inventory half of the hook adds its item
    parent_hook("parent")(mdb)
    mdb.commit()
    assert mdb.scalar(select(func.count()).select_from(InventoryItem)) == 1
    assert mdb.scalar(select(EventLog.message).where(EventLog.level == "error")) == "Couldn't run the checks after this sync."


def test_an_import_runs_the_checks(frozen, margaret, mdb, client):
    from tests.import_helpers import import_file
    a = account(mdb)
    history(mdb, a)
    login(client, "jr")
    csv = ("Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
           "DEBIT,10/10/2026,CVS/PHARMACY #09812 GIFT CARD FULLERTON CA,-500.00,DEBIT_CARD,9000.00,\n")
    r = import_file(client, "chase.csv", a.id, raw=csv.encode(), slug="margaret-ellis")
    assert r.status_code == 201
    mdb.rollback()                                      # end the test session's old snapshot to see the route's commit
    [f] = flags(mdb)
    assert f.check == "scam" and json.loads(f.facts)["posted_at"] == "2026-10-10"
    [event] = mdb.scalars(select(FlagEvent)).all()
    assert json.loads(event.detail) == {"after": "import"}
    assert mdb.scalar(select(func.count()).select_from(Transaction).where(Transaction.watched_at.is_(None))) == 0
