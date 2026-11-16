"""Missing deposits and missed premiums (spec 4.1; decision 6; ruling 3). Weekday facts: Oct 10, 2026 and Oct 3 are
Saturdays; Nov 1 is a Sunday; Feb 28, 2026 is a Saturday; Sep 10 is a Thursday."""
import json
from datetime import date, datetime, timezone

from sqlalchemy import select

from steward.db.models import BalanceSnapshot, Flag, FlagEvent, Institution, InventoryItem, SimplefinLink, Transaction
from steward.services.accounts import record_balance
from steward.watch.due import check_missed, due_date, latest_due, settle
from steward.watch.run import run_daily
from tests.watch_helpers import NOW, account


def test_due_dates_move_off_weekends():
    assert due_date(2026, 10, 10) == date(2026, 10, 12)
    assert due_date(2026, 10, 3) == date(2026, 10, 5)
    assert due_date(2026, 11, 1) == date(2026, 11, 2)
    assert due_date(2026, 2, 31) == date(2026, 3, 2)          # the 28th, a Saturday
    assert due_date(2026, 9, 10) == date(2026, 9, 10)
    assert latest_due(10, date(2026, 10, 17)) == (date(2026, 10, 10), date(2026, 10, 12))
    assert latest_due(10, date(2026, 10, 16)) == (date(2026, 9, 10), date(2026, 9, 10))


def pay(db, acct, day: date, cents: int, raw: str) -> Transaction:
    t = Transaction(account_id=acct.id, posted_at=day, amount_cents=cents, raw_description=raw, watched_at=NOW)
    db.add(t)
    db.commit()
    return t


def _setup(db, *, feed=True, synced=NOW, match="EVERGREEN MUTUAL", frequency="monthly", institution="Evergreen Mutual"):
    chk = account(db, "Joint checking", feed=feed)
    acct_item = db.scalar(select(InventoryItem).where(InventoryItem.account_id == chk.id))
    ltc = InventoryItem(kind="insurance", name="Long-term care", owner="margaret", institution=institution,
                        status="needs_checking", data_source="manual", details=json.dumps({
                            "type": "long_term_care", "amount_cents": 21_200, "frequency": frequency, "usual_day": 10,
                            "paid_from_id": acct_item.id, **({"match_text": match} if match else {})}))
    ss = InventoryItem(kind="income", name="Social Security", owner="margaret",
                       institution="Social Security Administration", status="confirmed", data_source="feed",
                       details=json.dumps({"source": "social_security", "amount_cents": 214_000, "frequency": "monthly",
                                           "usual_day": 3, "lands_in_id": acct_item.id, "match_text": "SSA TREAS 310"}))
    db.add_all([ltc, ss])
    if feed:
        db.get(Institution, chk.institution_id).last_sync_at = synced
        record_balance(db, chk.id, synced.date(), 100_000)
        db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=NOW, last_sync_at=synced))
    db.commit()
    for m in (7, 8, 9):
        pay(db, chk, date(2026, m, 10), -21_200, "EVERGREEN MUTUAL LTC PREM")
        pay(db, chk, date(2026, m, 3), 214_000, "SSA TREAS 310 XXSOC SEC")
    pay(db, chk, date(2026, 10, 2), 214_000, "SSA TREAS 310 XXSOC SEC")      # Oct 3 is a Saturday: paid Friday
    return chk, ltc, ss


def test_a_missed_premium_is_urgent_five_days_after_its_due_date(margaret, mdb):
    chk, ltc, _ = _setup(mdb)
    assert check_missed(mdb, date(2026, 10, 16), NOW) == []                  # due Mon Oct 12; not yet 5 days
    [fid] = check_missed(mdb, date(2026, 10, 17), NOW)
    f = mdb.get(Flag, fid)
    assert (f.check, f.severity, f.item_id, f.account_id, f.due_on) == ("premium", "urgent", ltc.id, chk.id, date(2026, 10, 12))
    assert f.summary == "the Evergreen Mutual long-term care premium hasn't left Joint checking"
    assert f.title == "Long-term care premium hasn't left"
    facts = json.loads(f.facts)
    assert (facts["nominal"], facts["due"], facts["weekend"], facts["amount_cents"], facts["as_of"]) == (
        "2026-10-10", "2026-10-12", "Saturday", 21_200, "2026-10-17")
    assert check_missed(mdb, date(2026, 10, 18), NOW) == []                  # one flag per due date


def test_a_payment_up_to_ten_days_early_counts(margaret, mdb):
    chk, _, _ = _setup(mdb)
    pay(mdb, chk, date(2026, 9, 30), -21_200, "EVERGREEN MUTUAL LTC PREM")
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []


def test_eleven_days_early_is_not_this_months_payment(margaret, mdb):
    chk, _, _ = _setup(mdb)
    pay(mdb, chk, date(2026, 9, 29), -21_200, "EVERGREEN MUTUAL LTC PREM")
    assert len(check_missed(mdb, date(2026, 10, 17), NOW)) == 1


def test_no_flag_without_data_past_the_grace_days(margaret, mdb):
    _setup(mdb, synced=datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc))   # last sync Oct 15
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []


def test_a_feed_account_that_did_not_come_back_is_not_checked_on_the_books_latest_sync(margaret, mdb):
    _setup(mdb, synced=datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc))
    # another bank synced today, so the book's latest sync is recent, but this account's bank didn't come back
    other = account(mdb, "Other savings", "savings", feed=True, institution="Other Bank")
    mdb.get(Institution, other.institution_id).last_sync_at = NOW
    for link in mdb.scalars(select(SimplefinLink)):
        link.last_sync_at = NOW
    mdb.commit()
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []


def test_a_dropped_account_is_not_checked_when_its_bank_came_back_without_it(margaret, mdb):
    chk, _, _ = _setup(mdb)
    # the bank synced today, but this account sent no balance in the sync
    for snap in mdb.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == chk.id)):
        mdb.delete(snap)
    mdb.commit()
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []
    record_balance(mdb, chk.id, date(2026, 10, 15), 100_000)                 # a stale balance does not count either
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []
    record_balance(mdb, chk.id, date(2026, 10, 17), 100_000)
    assert len(check_missed(mdb, date(2026, 10, 17), NOW)) == 1


def test_a_statement_account_needs_a_later_transaction(margaret, mdb):
    chk, _, _ = _setup(mdb, feed=False)
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []
    pay(mdb, chk, date(2026, 10, 18), -4500, "STATER BROS 123")
    assert [mdb.get(Flag, i).check for i in check_missed(mdb, date(2026, 10, 18), NOW)] == ["premium"]


def test_a_yearly_item_is_not_checked(margaret, mdb):
    _setup(mdb, frequency="yearly")
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []


def test_an_item_with_no_match_text_or_institution_is_not_checked(margaret, mdb):
    _setup(mdb, match=None, institution="")
    assert check_missed(mdb, date(2026, 10, 17), NOW) == []


def test_a_missing_deposit_closes_itself_when_it_arrives(margaret, mdb):
    chk, _, ss = _setup(mdb)
    mdb.delete(mdb.scalar(select(Transaction).where(Transaction.posted_at == date(2026, 10, 2))))
    mdb.commit()
    [fid] = [i for i in check_missed(mdb, date(2026, 10, 12), NOW) if mdb.get(Flag, i).check == "deposit"]
    f = mdb.get(Flag, fid)
    assert (f.summary, f.title, f.due_on) == ("the Social Security deposit, $2,140.00, hasn't arrived in Joint checking",
                                              "Social Security deposit hasn't arrived", date(2026, 10, 5))
    pay(mdb, chk, date(2026, 10, 14), 214_000, "SSA TREAS 310 XXSOC SEC")
    settle(mdb, date(2026, 10, 14), NOW)
    assert (f.status, f.resolved_by) == ("arrived", None) and f.resolved_at == NOW
    event = mdb.scalar(select(FlagEvent).where(FlagEvent.kind == "arrived"))
    assert json.loads(event.detail) == {"posted_at": "2026-10-14", "amount_cents": 214_000, "late_days": 9}


def test_a_missed_premium_stays_open_after_a_late_payment(margaret, mdb):
    chk, _, _ = _setup(mdb)
    [fid] = check_missed(mdb, date(2026, 10, 17), NOW)
    pay(mdb, chk, date(2026, 10, 19), -21_200, "EVERGREEN MUTUAL LTC PREM")
    settle(mdb, date(2026, 10, 19), NOW)
    settle(mdb, date(2026, 10, 20), NOW)
    f = mdb.get(Flag, fid)
    assert f.status == "open" and f.resolved_at is None
    [event] = mdb.scalars(select(FlagEvent).where(FlagEvent.kind == "paid")).all()
    assert json.loads(event.detail) == {"posted_at": "2026-10-19", "amount_cents": 21_200, "late_days": 7}


def test_the_morning_run_flags_missed_money(margaret, mdb):
    _setup(mdb)
    out = run_daily(mdb, date(2026, 10, 17), NOW)
    assert [mdb.get(Flag, i).check for i in out.flags] == ["premium"]


def test_next_months_deposit_does_not_close_a_deposit_that_never_came(margaret, mdb):
    chk, _, _ = _setup(mdb)
    mdb.delete(mdb.scalar(select(Transaction).where(Transaction.posted_at == date(2026, 10, 2))))
    mdb.commit()
    [fid] = [i for i in check_missed(mdb, date(2026, 10, 12), NOW) if mdb.get(Flag, i).check == "deposit"]
    pay(mdb, chk, date(2026, 11, 3), 214_000, "SSA TREAS 310 XXSOC SEC")      # November's, 31 days later
    settle(mdb, date(2026, 11, 3), NOW)
    f = mdb.get(Flag, fid)
    assert f.status == "open" and f.resolved_at is None
    assert mdb.scalar(select(FlagEvent.id).where(FlagEvent.kind == "arrived")) is None


def test_next_months_premium_is_not_a_late_payment_of_this_months(margaret, mdb):
    chk, _, _ = _setup(mdb)
    [fid] = check_missed(mdb, date(2026, 10, 17), NOW)
    pay(mdb, chk, date(2026, 11, 10), -21_200, "EVERGREEN MUTUAL LTC PREM")
    settle(mdb, date(2026, 11, 10), NOW)
    assert mdb.scalar(select(FlagEvent.id).where(FlagEvent.flag_id == fid, FlagEvent.kind == "paid")) is None
