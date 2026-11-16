"""Same-account spec, Detecting a duplicate: a reconnected bank. Deleting a connection at SimpleFIN and adding it again
leaves the old account's feed dead, its balance stopped days ago, and a 529 often has no transactions to compare. Such
a pair is asked about on name and bank alone, at the sync that brings the new feed in, and once more in the book
after the upgrade that brought the rule (JR's kids' 529s, Oct 28)."""
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import (Account, AccountFeed, AccountType, BalanceSnapshot, HeldFeed, Institution,
                               SameAccountAnswer, SimplefinLink, Source, Transaction, WatchState)
from steward.services.same_account import apart, detect, questions
from tests.fake_simplefin import make_fake
from tests.same_account_fixtures import E, JOINT_DAYS, NOW, feed_account, linked, sync, txns

BANK = "New York's 529 College Savings Plan"
CURLY_BANK = "New York’s 529 College Savings Plan"
KIDS = ("Lena S Hale (7-01)", "Theo T Hale (7-02)", "Nora K Hale (7-03)")
OLD_DAY = date(2026, 10, 20)                                    # the old connection's last balance
GONE = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)       # its last good sync
CREATED = datetime(2026, 8, 1, 17, 0, tzinfo=timezone.utc)
SYNCED = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)     # the book's latest sync, after the reconnect
AT = SYNCED + timedelta(hours=1)


def _bank(db, conn_id: str, org_id: str | None, name: str = BANK) -> Institution:
    inst = Institution(name=name, source=Source.simplefin, simplefin_org_id=conn_id, org_id=org_id)
    db.add(inst)
    db.flush()
    return inst


def _plan(db, inst: Institution, key: str, name: str, *, created: datetime, seen: datetime, balance: tuple,
          days=(), type_=AccountType.plan529) -> Account:
    ext = f"sfin:{key}"
    a = Account(institution_id=inst.id, name=name, type=type_, owner="joint", source=Source.simplefin,
                external_id=ext, created_at=created)
    db.add(a)
    db.flush()
    feed = AccountFeed(account_id=a.id, external_id=ext, institution_id=inst.id, name=name, added_at=created,
                       last_seen_at=seen)
    db.add(feed)
    db.flush()
    for i, (d, cents, desc) in enumerate(days):
        db.add(Transaction(account_id=a.id, posted_at=d, amount_cents=cents, raw_description=desc,
                           external_id=f"{key}-{i}", feed_id=feed.id, imported_at=created))
    db.add(BalanceSnapshot(account_id=a.id, as_of=balance[0], balance_cents=balance[1]))
    db.flush()
    return a


def _synced(db, at: datetime = SYNCED) -> None:
    db.add(SimplefinLink(access_url="x", claimed_at=CREATED, last_sync_at=at))
    db.flush()


def _reconnected(db, kids=KIDS, *, old_days=(), new_days=()) -> list[tuple[Account, Account]]:
    """Each kid's 529 under the deleted connection (no org id recorded, last seen Oct 20) and again under the new one
    (seen in the latest sync, untyped), with a balance the market has moved since."""
    old, new = _bank(db, "old-conn", None), _bank(db, "new-conn", "ny529")
    pairs = []
    for i, name in enumerate(kids):
        o = _plan(db, old, f"old-{i}", name, created=CREATED, seen=GONE, balance=(OLD_DAY, 10_000_00 + i * 1_000_00),
                  days=old_days)
        n = _plan(db, new, f"new-{i}", name, created=SYNCED, seen=SYNCED, balance=(SYNCED.date(), 10_412_37 + i * 1_000_00),
                  days=new_days, type_=AccountType.unknown)
        pairs.append((o, n))
    _synced(db)
    db.commit()
    return pairs


def _asked(db) -> set[tuple[int, int]]:
    return {(q.account_id, q.other_account_id) for q in db.scalars(select(SameAccountAnswer).where(
        SameAccountAnswer.answer == "open"))}


def test_a_reconnect_with_no_transactions_and_a_stale_balance_is_asked(db):
    [(old, new)] = _reconnected(db, KIDS[:1])
    assert apart.check_book(db, AT) == 1
    assert _asked(db) == {(old.id, new.id)}                     # the old one, typed and with its history, is kept


def test_three_kids_are_three_questions_never_crossed(db):
    pairs = _reconnected(db)
    assert apart.check_book(db, AT) == 3
    assert _asked(db) == {(o.id, n.id) for o, n in pairs}


def test_a_reconnect_whose_transactions_overlap_is_still_asked(db):
    [(old, new)] = _reconnected(db, KIDS[:1], old_days=JOINT_DAYS, new_days=JOINT_DAYS)
    assert apart.check_book(db, AT) == 1
    assert db.scalar(select(SameAccountAnswer.match_count)) == len(JOINT_DAYS)


def test_a_reconnect_whose_transactions_differ_is_left_to_them(db):
    """Enough rows to compare, and none match: the transactions decide, not the dead feed."""
    _reconnected(db, KIDS[:1], old_days=JOINT_DAYS,
                 new_days=[(date(2026, 10, 22), 400_00, "CONTRIBUTION"), (date(2026, 10, 25), 7_90, "DIVIDEND")])
    assert apart.check_book(db, AT) == 0


def test_two_live_529_twins_with_different_balances_are_not_asked(db):
    a_bank, b_bank = _bank(db, "jr", "ny529"), _bank(db, "sam", "ny529")
    _plan(db, a_bank, "jr-529", "529 Plan", created=CREATED, seen=SYNCED, balance=(SYNCED.date(), 12_000_00))
    _plan(db, b_bank, "sam-529", "529 Plan", created=SYNCED, seen=SYNCED, balance=(SYNCED.date(), 30_500_00),
          type_=AccountType.unknown)
    _synced(db)
    db.commit()
    assert apart.check_book(db, AT) == 0


def test_a_dead_feed_newer_than_the_live_one_is_not_a_reconnect(db):
    """A second login added and later deleted: its account is the newer one, so nothing replaced it."""
    a_bank, b_bank = _bank(db, "jr", "ny529"), _bank(db, "sam", None)
    _plan(db, a_bank, "jr-529", "529 Plan", created=CREATED, seen=SYNCED, balance=(SYNCED.date(), 12_000_00))
    _plan(db, b_bank, "sam-529", "529 Plan", created=GONE - timedelta(days=5), seen=GONE,
          balance=(OLD_DAY, 30_500_00))
    _synced(db)
    db.commit()
    assert apart.check_book(db, AT) == 0


def test_a_reconnect_on_the_same_connection_is_two_accounts(db):
    """Rule 4 still holds: one login's two accounts with one name are two, dead feed or not."""
    inst = _bank(db, "conn", "ny529")
    _plan(db, inst, "old-0", KIDS[0], created=CREATED, seen=GONE, balance=(OLD_DAY, 10_000_00))
    _plan(db, inst, "new-0", KIDS[0], created=SYNCED, seen=SYNCED, balance=(SYNCED.date(), 10_412_37),
          type_=AccountType.unknown)
    _synced(db)
    db.commit()
    assert apart.check_book(db, AT) == 0


def test_a_reconnect_answered_different_is_not_asked_again(db):
    _reconnected(db, KIDS[:1])
    assert apart.check_book(db, AT) == 1
    apart.keep_apart(db, db.scalar(select(SameAccountAnswer)), 1, AT)
    db.commit()
    assert apart.check_book(db, AT + timedelta(days=1)) == 0


def test_a_curly_apostrophe_and_a_straight_one_are_one_bank():
    inst = Institution(name=CURLY_BANK, source=Source.simplefin, org_id=None)
    assert detect.same_bank(inst, "ny529", BANK)
    assert detect.norm("Lena S Hale’s 529") == detect.norm("lena s hale's  529")


def test_a_reconnect_at_sync_is_held_on_name_and_bank_alone(db):
    """JR's case as it happens: the old connection synced, was deleted, and came back a week later with each kid's 529
    under a new connection, no transactions, and balances the market has moved."""
    app, state = make_fake()
    for i, name in enumerate(KIDS):
        state.add_account("old-conn", CURLY_BANK, "ny529", f"old-{i}", 10_000_00 + i, E(NOW.date()), name=name)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        db.scalar(select(Institution).where(Institution.simplefin_org_id == "old-conn")).org_id = None
        db.commit()
        state.accounts.clear()
        week = NOW + timedelta(days=7)
        for i, name in enumerate(reversed(KIDS)):
            state.add_account("new-conn", BANK, "ny529", f"new-{i}", 10_412_37 + i, E(week.date()), name=name)
        res = sync(db, http, link, week)
    assert (res.accounts_new, res.accounts_held) == (0, 3)
    held = {h.name: h.candidate_account_id for h in db.scalars(select(HeldFeed))}
    assert held == {name: feed_account(db, f"sfin:old-{i}").id for i, name in enumerate(KIDS)}


def test_two_live_529_twins_at_sync_with_no_transactions_are_two_accounts(db):
    app, state = make_fake()
    state.add_account("jr", BANK, "ny529", "529-a", 12_000_00, E(NOW.date()), name="529 Plan")
    state.add_account("sam", BANK, "ny529", "529-b", 30_500_00, E(NOW.date()), name="529 Plan")
    with TestClient(app) as http:
        link = linked(db, http)
        res = sync(db, http, link)
        res2 = sync(db, http, link, NOW + timedelta(days=1))
    assert (res.accounts_new, res.accounts_held, res2.accounts_held) == (2, 0, 0)
    assert apart.check_book(db, NOW + timedelta(days=1)) == 0


def test_a_reconnect_with_overlapping_transactions_at_sync_is_held(db):
    app, state = make_fake()
    state.add_account("old-conn", BANK, "ny529", "old-0", 10_000_00, E(NOW.date()), name=KIDS[0], txns=txns("o"))
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        state.accounts.clear()
        week = NOW + timedelta(days=7)
        state.add_account("new-conn", BANK, "ny529", "new-0", 10_412_37, E(week.date()), name=KIDS[0], txns=txns("n"))
        res = sync(db, http, link, week)
    assert res.accounts_held == 1
    assert questions.open_questions(db)[0]["matches"] == len(JOINT_DAYS)   # the rows decided, not the dead feed


def _deployed_before_this_check(db) -> None:
    """A book as JR's was before this deploy: upgraded to feeds and checked then, with no mark of this version."""
    if (mark := db.get(WatchState, apart.CHECK_KEY)) is not None:
        db.delete(mark)
    db.commit()


def test_the_check_runs_once_more_for_the_reconnect_rule(db, engine):
    _reconnected(db)
    _deployed_before_this_check(db)
    assert apart.check_once(engine, "0027", AT) == 3            # past the feeds upgrade, but not past this rule
    assert apart.check_once(engine, "0027", AT) == 0
    db.rollback()
    assert questions.open_count(db) == 3
    for q in db.scalars(select(SameAccountAnswer)):
        db.delete(q)
    db.commit()
    assert apart.check_once(engine, "0027", AT) == 0            # once: it doesn't run again at the next start-up


def test_a_new_book_is_marked_without_a_check(db, engine):
    _reconnected(db)
    _deployed_before_this_check(db)
    assert apart.check_once(engine, None, AT) == 0
    assert apart.check_once(engine, "0027", AT) == 0


def test_start_up_raises_the_reconnected_pairs_once(books, ours):
    with Session(books.engine_for(ours)) as s:
        _reconnected(s)
        _deployed_before_this_check(s)
    books.upgrade_all()
    with Session(books.engine_for(ours)) as s:
        assert questions.open_count(s) == 3
    books.upgrade_all()
    with Session(books.engine_for(ours)) as s:
        assert s.scalar(select(func.count()).select_from(SameAccountAnswer)) == 3
