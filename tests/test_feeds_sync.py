"""Same-account spec, Data and Ongoing sync: sync finds accounts by their SimpleFIN feeds, records each feed's own
name and when it was last seen, the bank's org id, and the feed each new row came through."""
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from steward.db.models import Account, AccountFeed, EventLog, Institution, Transaction
from steward.services.simplefin.sync import run_sync
from tests.fake_simplefin import make_fake
from tests.test_sync import NOW, E, H, _household, _link


def _sync(db, http, link, at=NOW):
    res = run_sync(db, http, link, at, model=None, allowed_hosts=H)
    db.commit()
    return res


def test_a_first_sync_gives_each_account_its_feed_and_each_row_its_feed(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        _sync(db, http, _link(db, http))
    feeds = {f.external_id: f for f in db.scalars(select(AccountFeed))}
    assert set(feeds) == {"sfin:chk", "sfin:sav", "sfin:hy"}
    chk = db.scalar(select(Account).where(Account.external_id == "sfin:chk"))
    big = db.scalar(select(Institution).where(Institution.simplefin_org_id == "big"))
    f = feeds["sfin:chk"]
    assert (f.account_id, f.institution_id, f.name, f.added_at, f.last_seen_at) == (chk.id, big.id, "chk", NOW, NOW)
    assert {t.external_id: t.feed_id for t in db.scalars(select(Transaction))} == {
        "t1": f.id, "t2": f.id, "t3": feeds["sfin:sav"].id}
    assert big.org_id == "bigbank"


def test_the_next_sync_refreshes_the_feeds_name_and_last_seen_but_keeps_a_persons_rename(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        _sync(db, http, link)
        chk = db.scalar(select(Account).where(Account.external_id == "sfin:chk"))
        chk.name = "Our checking"; db.commit()
        state.accounts[0].name = "Everyday Checking"
        _sync(db, http, link, NOW + timedelta(hours=6))
    f = db.scalar(select(AccountFeed).where(AccountFeed.external_id == "sfin:chk"))
    assert (f.name, f.last_seen_at) == ("Everyday Checking", NOW + timedelta(hours=6))
    db.refresh(chk)
    assert chk.name == "Our checking"


def test_sync_finds_an_account_by_its_feed_not_by_its_external_id(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        _sync(db, http, link)
        chk = db.scalar(select(Account).where(Account.external_id == "sfin:chk"))
        chk.external_id = "imported-once"; db.commit()
        state.accounts[0].txns.append(("t9", E(2026, 10, 11), -12_34, "BEAN & LEAF 0031"))
        res = _sync(db, http, link, NOW + timedelta(hours=6))
    assert res.accounts_new == 0
    assert db.scalar(select(func.count()).select_from(Account)) == 3
    assert db.scalar(select(Transaction).where(Transaction.external_id == "t9")).account_id == chk.id


def test_an_account_made_outside_sync_is_given_its_feed_instead_of_a_second_account(db):
    from tests.factories import make_account
    app, state = make_fake(); _household(state)
    acct = make_account(db, "Checking", type="checking", source="simplefin", institution_name="Big Bank")
    acct.external_id = "sfin:chk"
    acct.institution.simplefin_org_id = "big"
    db.commit()
    with TestClient(app) as http:
        res = _sync(db, http, _link(db, http))
    assert res.accounts_new == 2                     # sav and hy; chk was already here
    f = db.scalar(select(AccountFeed).where(AccountFeed.external_id == "sfin:chk"))
    assert f.account_id == acct.id and f.last_seen_at == NOW
    assert db.scalar(select(func.count()).select_from(Account).where(Account.name == "Checking")) == 1


def test_an_empty_org_id_never_overwrites_a_recorded_one(db):
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        _sync(db, http, link)
        for a in state.accounts:
            if a.conn_id == "big":
                a.org_id = ""
        _sync(db, http, link, NOW + timedelta(hours=6))
    assert db.scalar(select(Institution.org_id).where(Institution.simplefin_org_id == "big")) == "bigbank"


def test_a_sign_in_problem_warns_when_only_a_feed_depends_on_the_connection(db):
    """Review Focus 5: after a merge, Marcus's login may only feed an account that belongs to another institution.
    Its sign-in problem still warns on Home."""
    app, state = make_fake(); _household(state)
    with TestClient(app) as http:
        link = _link(db, http)
        _sync(db, http, link)
        big = db.scalar(select(Institution).where(Institution.simplefin_org_id == "big"))
        hy = db.scalar(select(Account).where(Account.external_id == "sfin:hy"))
        hy.institution_id = big.id; db.commit()     # as a merge leaves it: the account is Big Bank's, its feed Marcus's
        state.fail_conn = "marcus"
        res = _sync(db, http, link, NOW + timedelta(hours=6))
    assert res.errors == ["Marcus needs you to sign in again at SimpleFIN"]
    assert db.scalar(select(EventLog.id).where(EventLog.message == "Marcus needs you to sign in again at SimpleFIN",
                                               EventLog.resolved_at.is_(None))) is not None


def test_holdings_and_what_was_sent_go_on_the_account_a_feed_resolves_to_and_never_a_held_ones(db):
    """Investment views with same account: a held feed's holdings wait with it; once it joins an account, the account
    sends holdings if either of its feeds does, whichever the sync reaches first."""
    from steward.db.models import HeldFeed, Holding
    from steward.services.same_account.merge import merge
    from tests.same_account_fixtures import BALANCE_DAY, LATER, feed_account, jr_login, linked, sam_login, sync
    app, state = make_fake()
    jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        state.holdings["sam-joint"] = [{"id": "h1", "symbol": "VTI", "description": "Total Stock", "shares": "10",
                                        "market_value": "2500"}]
        sync(db, http, link, LATER)
        keep = feed_account(db, "sfin:jr-joint")
        assert feed_account(db, "sfin:sam-joint") is None                 # held
        assert db.scalars(select(Holding)).all() == []
        assert (keep.sends_holdings, keep.holdings_seen_at) == (False, None)
        merge(db, keep.id, db.scalar(select(HeldFeed)), user_id=1, now=LATER + timedelta(minutes=1))
        db.commit()
        # Now the feed the sync reaches first sends them and the other doesn't: the account still sends holdings.
        state.holdings["jr-joint"] = state.holdings.pop("sam-joint")
        at = LATER + timedelta(hours=1)
        sync(db, http, link, at)
    db.expire_all()
    keep = feed_account(db, "sfin:jr-joint")
    assert (keep.sends_holdings, keep.holdings_seen_at, keep.sends_transactions) == (True, at, True)
    assert [(h.account_id, h.as_of, h.symbol) for h in db.scalars(select(Holding))] == [(keep.id, BALANCE_DAY, "VTI")]
