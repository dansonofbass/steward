"""Same-account spec, Ongoing sync for an account with several feeds: a transaction is ingested only when it matches no
existing one from another feed (same amount, within 3 days, one to one) and no alias; the newest balance wins; a lost
feed lets the other carry on."""
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from steward.db.models import AccountFeed, BalanceSnapshot, FeedTxnAlias, Institution, Source, Transaction
from steward.services.accounts import latest_balance
from tests.factories import make_txn
from tests.fake_simplefin import make_fake
from tests.same_account_fixtures import (BALANCE, BALANCE_DAY, E, LATER, NOW, feed_account, jr_login, linked,
                                         sam_login, sync)


def _second_feed(db, account) -> AccountFeed:
    """Sam's login's feed into JR's joint account, as a merge leaves it."""
    inst = Institution(name="Betterment", source=Source.simplefin, simplefin_org_id="sam", org_id="betterment")
    db.add(inst)
    db.flush()
    feed = AccountFeed(account_id=account.id, external_id="sfin:sam-joint", institution_id=inst.id,
                       name="Joint Taxable", added_at=NOW, last_seen_at=NOW)
    db.add(feed)
    db.commit()
    return feed


def _count(db, account, desc=None) -> int:
    q = select(func.count()).select_from(Transaction).where(Transaction.account_id == account.id)
    return db.scalar(q.where(Transaction.raw_description == desc) if desc else q)


def _fake_acct(state, acct_id):
    return next(a for a in state.accounts if a.id == acct_id)


def _two_feeds(db, http, state):
    link = linked(db, http)
    sync(db, http, link)
    joint = feed_account(db, "sfin:jr-joint")
    feed = _second_feed(db, joint)
    sam_login(state)
    res = sync(db, http, link, LATER)
    return link, joint, feed, res


def test_copies_from_a_second_feed_are_dropped_and_remembered(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        _, joint, feed, res = _two_feeds(db, http, state)
    assert res.transactions_new == 0 and _count(db, joint) == 5
    jr = {t.external_id: t.id for t in db.scalars(select(Transaction).where(Transaction.account_id == joint.id))}
    aliases = {a.external_id: a for a in db.scalars(select(FeedTxnAlias))}
    assert set(aliases) == {f"sam-{i}" for i in range(5)}
    assert {(a.account_id, a.feed_id) for a in aliases.values()} == {(joint.id, feed.id)}
    assert aliases["sam-0"].transaction_id == jr["jr-0"] and aliases["sam-4"].transaction_id == jr["jr-4"]
    assert {aliases["sam-1"].transaction_id, aliases["sam-2"].transaction_id} == {jr["jr-1"], jr["jr-2"]}


def test_two_coffees_on_one_day_stay_two_over_several_syncs(db):
    """Review Focus 1: both logins send the day's two $5 coffees, then a third, then one only Sam's login has yet."""
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link, joint, _, _ = _two_feeds(db, http, state)
        jr, sam = _fake_acct(state, "jr-joint"), _fake_acct(state, "sam-joint")
        jr.txns.append(("jr-5", E(date(2026, 10, 27)), -5_00, "COFFEE"))
        sam.txns.append(("sam-5", E(date(2026, 10, 27)), -5_00, "COFFEE"))
        sync(db, http, link, LATER + timedelta(hours=1))
        sync(db, http, link, LATER + timedelta(hours=2))
        assert (_count(db, joint), _count(db, joint, "COFFEE")) == (6, 3)
        sam.txns.append(("sam-6", E(date(2026, 10, 28)), -5_00, "COFFEE"))
        sync(db, http, link, LATER + timedelta(days=1))                  # only Sam's login has it so far: it's new
        assert _count(db, joint, "COFFEE") == 4
        jr.txns.append(("jr-6", E(date(2026, 10, 28)), -5_00, "COFFEE"))
        sync(db, http, link, LATER + timedelta(days=1, hours=6))         # JR's copy of it arrives: dropped
    assert (_count(db, joint), _count(db, joint, "COFFEE")) == (7, 4)


def test_an_alias_holds_after_the_window(db):
    """Review Focus 2: the bank re-dates the advisory fee five days later; its copy was matched once, so it stays out."""
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link, joint, _, _ = _two_feeds(db, http, state)
        sam = _fake_acct(state, "sam-joint")
        sam.txns[3] = ("sam-3", E(date(2026, 10, 29)), -12_50, "ADVISORY FEE")
        sync(db, http, link, LATER + timedelta(days=2))
    assert (_count(db, joint), _count(db, joint, "ADVISORY FEE")) == (5, 1)


def test_a_lost_feed_lets_the_other_carry_on(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link, joint, feed, _ = _two_feeds(db, http, state)
        state.accounts[:] = [a for a in state.accounts if a.conn_id != "sam"]      # Sam's login was deleted
        jr = _fake_acct(state, "jr-joint")
        jr.txns.append(("jr-5", E(date(2026, 10, 28)), -40_00, "WIRE FEE"))
        jr.balance_cents, jr.balance_date = BALANCE - 40_00, E(date(2026, 10, 28))
        sync(db, http, link, LATER + timedelta(days=1))
    db.refresh(feed)
    assert _count(db, joint) == 6 and feed.last_seen_at == LATER
    assert latest_balance(db, joint.id) == (date(2026, 10, 28), BALANCE - 40_00)


def test_the_newest_balance_wins(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        joint = feed_account(db, "sfin:jr-joint")
        _second_feed(db, joint)
        sam_login(state)
        _fake_acct(state, "sam-joint").balance_date = E(BALANCE_DAY - timedelta(days=1))
        _fake_acct(state, "sam-joint").balance_cents = BALANCE - 9_99
        sync(db, http, link, LATER)
        snaps = dict(db.execute(select(BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
                                .where(BalanceSnapshot.account_id == joint.id)).all())
        assert snaps == {BALANCE_DAY: BALANCE}                      # Sam's older balance doesn't write over history
        _fake_acct(state, "sam-joint").balance_date = E(BALANCE_DAY + timedelta(days=1))
        _fake_acct(state, "sam-joint").balance_cents = BALANCE + 1_00
        sync(db, http, link, LATER + timedelta(days=1))
    assert latest_balance(db, joint.id) == (BALANCE_DAY + timedelta(days=1), BALANCE + 1_00)


def test_a_files_rows_are_never_taken_for_copies(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link, joint, _, _ = _two_feeds(db, http, state)
        make_txn(db, joint, date(2026, 10, 27), -40_00, "WIRE FEE")            # imported from a file: no feed
        _fake_acct(state, "sam-joint").txns.append(("sam-9", E(date(2026, 10, 27)), -40_00, "WIRE FEE"))
        sync(db, http, link, LATER + timedelta(hours=1))
    assert _count(db, joint, "WIRE FEE") == 2
