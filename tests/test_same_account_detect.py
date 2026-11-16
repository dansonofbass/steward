"""Same-account spec, Detecting a duplicate: on sync, a SimpleFIN account this book has no feed for, that looks like
one it has (rules 1 to 4), is held instead: no account, no transactions, no balance, no event. A held feed refreshes
at each sync, and comes in as a new account if the one it looked like goes."""
import json
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from steward.db.models import (Account, AccountFeed, BalanceSnapshot, EventLog, HeldFeed, Institution,
                               Transaction)
from steward.services.same_account import detect
from steward.services.simplefin.client import fetch_accounts
from steward.services.simplefin.sync import categorize_fetched
from steward.services.txn_match import pair_up
from tests.fake_simplefin import make_fake
from tests.same_account_fixtures import (BALANCE, BALANCE_DAY, E, H, LATER, feed_account, jr_login,
                                         linked, sam_login, sync, txns)


def _events(db, name: str) -> int:
    return db.scalar(select(func.count()).select_from(EventLog).where(
        EventLog.message.startswith(f"New account '{name}' from ", autoescape=True)))


def test_matching_is_one_to_one_within_three_days_nearest_first():
    d = date(2026, 10, 23)
    existing = [(1, d, -500), (2, d, -500), (3, d + timedelta(days=2), -1250), (4, d + timedelta(days=5), -999)]
    assert pair_up([(d, -500), (d, -500), (d, -500)], existing) == {0: 1, 1: 2}   # two coffees match two; a third is new
    assert pair_up([(d + timedelta(days=1), -1250)], existing) == {0: 3}          # within 3 days
    assert pair_up([(d, -999)], existing) == {}                                   # 5 days apart
    assert pair_up([(d + timedelta(days=3), -500)], [(7, d + timedelta(days=1), -500), (6, d, -500)]) == {0: 7}


def test_a_second_login_to_a_joint_account_is_held_not_made(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        res = sync(db, http, link, LATER)
    joint = feed_account(db, "sfin:jr-joint")
    sam = db.scalar(select(Institution).where(Institution.simplefin_org_id == "sam"))
    h = db.scalar(select(HeldFeed))
    assert (h.external_id, h.candidate_account_id, h.institution_id, h.name) == ("sfin:sam-joint", joint.id, sam.id,
                                                                                  "Joint Taxable")
    assert (h.balance_cents, h.balance_date, h.first_seen_at, h.last_seen_at) == (BALANCE, BALANCE_DAY, LATER, LATER)
    assert [r["id"] for r in json.loads(h.payload)] == ["sam-0", "sam-1", "sam-2", "sam-3", "sam-4"]
    assert (res.accounts_new, res.accounts_held) == (1, 1)                  # Sam's IRA is new; the joint one waits
    assert {a.name for a in db.scalars(select(Account))} == {"Joint Taxable", "JR IRA", "Sam IRA"}
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.external_id.like("sam-%"))) == 0
    assert feed_account(db, "sfin:sam-joint") is None
    assert db.scalar(select(func.count()).select_from(BalanceSnapshot)) == 3   # JR's two and Sam's IRA
    assert _events(db, "Joint Taxable") == 1 and _events(db, "Sam IRA") == 1   # no second "needs its type" for it


def test_a_reconnected_bank_is_held(db):
    app, state = make_fake()
    state.add_account("b1", "Betterment", "betterment", "old-529", 12_000_00, E(BALANCE_DAY), txns=txns("old"),
                      name="529 Plan")
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        state.accounts.clear()                       # the connection was deleted at SimpleFIN, then added again
        state.add_account("b2", "Betterment", "betterment", "new-529", 12_000_00, E(BALANCE_DAY), txns=txns("new"),
                          name="529 Plan")
        res = sync(db, http, link, LATER)
    assert res.accounts_held == 1
    assert db.scalar(select(HeldFeed.candidate_account_id)) == feed_account(db, "sfin:old-529").id
    assert db.scalar(select(func.count()).select_from(Account)) == 1


def test_two_529s_with_one_name_different_balances_and_no_overlap_are_two_accounts(db):
    app, state = make_fake()
    state.add_account("jr", "Betterment", "betterment", "529-a", 12_000_00, E(BALANCE_DAY), name="529 Plan", txns=[
        ("a-1", E(date(2026, 10, 21)), 250_00, "CONTRIBUTION"), ("a-2", E(date(2026, 10, 24)), 3_10, "DIVIDEND")])
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        state.add_account("sam", "Betterment", "betterment", "529-b", 30_500_00, E(BALANCE_DAY), name="529 Plan", txns=[
            ("b-1", E(date(2026, 10, 22)), 400_00, "CONTRIBUTION"), ("b-2", E(date(2026, 10, 25)), 7_90, "DIVIDEND")])
        res = sync(db, http, link, LATER)
    assert (res.accounts_new, res.accounts_held) == (1, 0)
    assert db.scalar(select(func.count()).select_from(Account).where(Account.name == "529 Plan")) == 2


def test_one_login_with_two_same_named_accounts_makes_both(db):
    """Review Focus 4: two kids' 529s on one login, with one name and the same deposits on the same days."""
    app, state = make_fake()
    for acct in ("529-kid-1", "529-kid-2"):
        state.add_account("jr", "Betterment", "betterment", acct, 12_000_00, E(BALANCE_DAY), name="529 Plan",
                          txns=txns(acct))
    with TestClient(app) as http:
        res = sync(db, http, linked(db, http))
    assert (res.accounts_new, res.accounts_held) == (2, 0)


def test_a_renamed_account_is_found_by_its_original_name(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        feed_account(db, "sfin:jr-joint").name = "Our brokerage"
        db.commit()
        sam_login(state)
        res = sync(db, http, link, LATER)
    assert res.accounts_held == 1


def test_before_an_org_id_is_recorded_the_bank_name_counts(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        db.scalar(select(Institution).where(Institution.simplefin_org_id == "jr")).org_id = None
        db.commit()
        for a in state.accounts:                     # jr's login re-records its org id at the next sync; blank it in the fake
            if a.conn_id == "jr":
                a.org_id = ""
        state.add_account("sam", "  BETTERMENT ", "betterment-2", "sam-joint", BALANCE, E(BALANCE_DAY),
                          txns=txns("sam"), name="joint  taxable")
        res = sync(db, http, link, LATER)
    assert res.accounts_held == 1


def test_two_org_ids_that_differ_are_two_banks_whatever_their_names(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        state.add_account("sam", "Betterment", "wealthfront", "sam-joint", BALANCE, E(BALANCE_DAY),
                          txns=txns("sam"), name="Joint Taxable")
        res = sync(db, http, link, LATER)
    assert (res.accounts_new, res.accounts_held) == (1, 0)


def test_balances_decide_when_there_is_too_little_to_compare(db):
    app, state = make_fake()
    state.add_account("jr", "Betterment", "betterment", "jr-529", 12_000_00, E(BALANCE_DAY), name="529 Plan")
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        # within $1 and 3 days: held; $20 off: a new account
        state.add_account("sam", "Betterment", "betterment", "sam-529", 12_000_50, E(BALANCE_DAY - timedelta(days=2)),
                          name="529 Plan")
        state.add_account("kim", "Betterment", "betterment", "kim-529", 12_020_00, E(BALANCE_DAY), name="529 Plan")
        res = sync(db, http, link, LATER)
    assert (res.accounts_held, res.accounts_new) == (1, 1)
    assert db.scalar(select(HeldFeed.external_id)) == "sfin:sam-529"


def test_a_held_feed_refreshes_at_the_next_sync_and_keeps_its_newest_400_rows(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        sync(db, http, link, LATER)
        h = db.scalar(select(HeldFeed))
        h.payload = json.dumps([{"id": f"old-{i:03}", "posted": "2026-09-01", "amount_cents": -100,
                                 "description": "OLD"} for i in range(400)])
        db.commit()
        sam = next(a for a in state.accounts if a.id == "sam-joint")
        sam.balance_cents, sam.balance_date = BALANCE + 40_00, E(date(2026, 10, 28))
        sam.txns.append(("sam-9", E(date(2026, 10, 27)), -40_00, "WIRE FEE"))
        res = sync(db, http, link, LATER + timedelta(days=1))
    db.refresh(h)
    rows = json.loads(h.payload)
    assert len(rows) == 400 and rows[-1]["id"] == "sam-9" and {"sam-0", "sam-4"} <= {r["id"] for r in rows}
    assert {r["id"] for r in rows if r["id"].startswith("old-")} == {f"old-{i:03}" for i in range(6, 400)}
    assert (h.balance_cents, h.balance_date) == (BALANCE + 40_00, date(2026, 10, 28))
    assert (h.first_seen_at, h.last_seen_at) == (LATER, LATER + timedelta(days=1))
    assert res.accounts_held == 1 and db.scalar(select(func.count()).select_from(Account)) == 3


def test_a_parent_books_sync_keeps_todays_behaviour(db):
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link, household=False)
        sam_login(state)
        res = sync(db, http, link, LATER, household=False)
    assert (res.accounts_new, res.accounts_held) == (2, 0)
    assert db.scalars(select(HeldFeed)).all() == []


def test_categorizing_asks_about_no_row_of_a_held_or_soon_held_feed(db):
    """Privacy: a held feed's rows reach no model, before it is held or after."""
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        next(a for a in state.accounts if a.id == "sam-ira").txns.append(
            ("sam-ira-1", E(date(2026, 10, 25)), 100_00, "CONTRIBUTION"))
        fetched = fetch_accounts(http, link.access_url, start=None, allowed_hosts=H)
        soon = categorize_fetched(db, fetched, None)
        sync(db, http, link, LATER)
        later = categorize_fetched(db, fetched, None)
    assert {a for a, _ in soon} == {"sam-ira"}
    assert not any(a == "sam-joint" for a, _ in later)


def test_a_held_feed_whose_account_went_comes_in_with_its_history(db):
    """Engineering choice 9: nothing a held feed kept is lost when the account it looked like goes."""
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        sync(db, http, link, LATER)
        h = db.scalar(select(HeldFeed))
        h.candidate_account_id = None
        h.payload = json.dumps(json.loads(h.payload) + [
            {"id": "sam-early", "posted": "2026-09-30", "amount_cents": -2_00, "description": "OLD FEE"}])
        db.commit()
        res = sync(db, http, link, LATER + timedelta(hours=6))
    assert res.accounts_new == 1 and db.scalars(select(HeldFeed)).all() == []
    acct = feed_account(db, "sfin:sam-joint")
    assert acct.name == "Joint Taxable" and acct.id != feed_account(db, "sfin:jr-joint").id
    assert set(db.scalars(select(Transaction.external_id).where(Transaction.account_id == acct.id))) == {
        "sam-0", "sam-1", "sam-2", "sam-3", "sam-4", "sam-early"}
    assert _events(db, "Joint Taxable") == 2


def test_an_incoming_name_that_matches_the_accounts_own_name_counts(db):
    """Rule 2: the name in the book counts as well as the feed's. The bank now sends JR's joint account as
    "JT ••1234", and Sam's login sends it as "Joint Taxable", the name JR's account has in the book."""
    app, state = make_fake(); jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        next(a for a in state.accounts if a.id == "jr-joint").name = "JT ••1234"
        sam_login(state)
        res = sync(db, http, link, LATER)
    assert res.accounts_held == 1
    assert db.scalar(select(AccountFeed.name).where(AccountFeed.external_id == "sfin:jr-joint")) == "JT ••1234"


KID_DAYS = [(date(2026, 10, 21), 200_00, "CONTRIBUTION"), (date(2026, 10, 24), 200_00, "CONTRIBUTION")]


def test_two_live_529s_with_the_same_contributions_but_different_balances_are_two_accounts(db):
    """Rule 3: both logins send theirs in this sync and the balances differ, so the coinciding $200s don't count."""
    app, state = make_fake()
    state.add_account("jr", "my529", "my529", "kid-1", 18_400_00, E(BALANCE_DAY), name="my529 Account",
                      txns=txns("k1", KID_DAYS))
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        state.add_account("sam", "my529", "my529", "kid-2", 9_250_00, E(BALANCE_DAY), name="my529 Account",
                          txns=txns("k2", KID_DAYS))
        res = sync(db, http, link, LATER)
    assert (res.accounts_new, res.accounts_held) == (1, 0)
    assert db.scalars(select(HeldFeed)).all() == []


def test_a_reconnect_is_held_even_when_its_balance_moved(db):
    """Rule 3's balance test is for two live feeds only: the old connection is gone, so a new balance can't keep the
    reconnected account apart."""
    app, state = make_fake()
    state.add_account("b1", "Betterment", "betterment", "old-529", 12_000_00, E(BALANCE_DAY - timedelta(days=1)),
                      txns=txns("old"), name="529 Plan")
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        state.accounts.clear()
        state.add_account("b2", "Betterment", "betterment", "new-529", 12_450_00, E(BALANCE_DAY), txns=txns("new"),
                          name="529 Plan")
        res = sync(db, http, link, LATER)
    assert res.accounts_held == 1


def test_two_live_balances_differ_by_more_than_a_dollar_or_half_a_percent():
    d = BALANCE_DAY
    assert not detect.apart_by_balance((d, 1_000_00), (d, 1_000_99))          # within $1
    assert detect.apart_by_balance((d, 1_00), (d, 3_00))                       # $2 on a small balance
    assert not detect.apart_by_balance((d, 1_000_000_00), (d, 1_004_000_00))   # within 0.5% of the larger
    assert detect.apart_by_balance((d, 1_000_000_00), (d, 1_006_000_00))
    assert detect.apart_by_balance((d, -50_000_00), (d, -51_000_00))           # a loan's too
    assert not detect.apart_by_balance((d, 100_00), (d - timedelta(days=4), 900_00))   # not from within 3 days
    assert not detect.apart_by_balance(None, (d, 100_00))
