"""Same-account spec, Merging: a held feed into the account it looks like, and an account in the book into another,
with the copies dropped one to one, what a person put on a copy carried over, transfers paired again, every link moved,
and one undo entry for all of it."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from steward.db.models import (Account, AccountFeed, AccountType, AdvisorAlias, BalanceSnapshot, BusinessRule,
                               CategorySource, Child, DuplicateKeep, EventLog, Fact, FeedTxnAlias, Flag, FlagEvent,
                               HeldFeed, Holding, ImportBatch, InventoryItem, MailOutbox, PositionsImport, Reimburser,
                               SameAccountAnswer, SetAside, SetAsideMatch, TaxState, Transaction,
                               TransactionNote, UndoEntry, WatchKnown)
from steward.events import log_event
from steward.watch.store import add_event
from steward.services.home_value import LINK_KEY
from steward.services.same_account.merge import MergeRefused, check, merge, preview
from tests.factories import make_account, make_txn
from tests.fake_simplefin import make_fake
from tests.same_account_fixtures import (BALANCE, BALANCE_DAY, JOINT_DAYS, LATER, NOW, feed_account, held_copy,
                                         in_book_pair, jr_account, jr_login, linked, sam_login, sync, txn)

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry

AT = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
WIRE = (date(2026, 10, 27), -40_00, "WIRE FEE")


def _ids(db, account) -> list[str]:
    return sorted(db.scalars(select(Transaction.external_id).where(Transaction.account_id == account.id)))


def _snaps(db, account) -> dict:
    return dict(db.execute(select(BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
                           .where(BalanceSnapshot.account_id == account.id)).all())


def _merge(db, keep, other):
    m = merge(db, keep.id, other if isinstance(other, HeldFeed) else other.id, user_id=1, now=AT)
    db.commit()
    db.expire_all()
    return m


def test_merging_a_held_feed_adds_its_feed_drops_its_copies_and_keeps_what_is_new(db):
    keep = jr_account(db)
    h = held_copy(db, keep, days=JOINT_DAYS + [WIRE], balance=(date(2026, 10, 28), BALANCE - 40_00))
    m = _merge(db, keep, h)
    assert (m.kept_id, m.kept_name, m.dropped, m.kept_new) == (keep.id, "Joint Taxable", 5, 1)
    assert db.scalars(select(HeldFeed)).all() == []
    feed = db.scalar(select(AccountFeed).where(AccountFeed.external_id == "sfin:sam-joint"))
    assert (feed.account_id, feed.name, feed.added_at, feed.last_seen_at) == (keep.id, "Joint Taxable", AT, LATER)
    assert _ids(db, keep) == ["jr-0", "jr-1", "jr-2", "jr-3", "jr-4", "sam-5"]
    assert txn(db, keep, "sam-5").feed_id == feed.id
    assert sorted(db.scalars(select(FeedTxnAlias.external_id))) == [f"sam-{i}" for i in range(5)]
    assert _snaps(db, keep) == {BALANCE_DAY: BALANCE, date(2026, 10, 28): BALANCE - 40_00}
    e = db.scalar(select(UndoEntry))
    assert (e.action, e.user_id, e.token, e.expires_at) == ("merge", 1, m.undo, AT + timedelta(minutes=15))


def test_a_held_balance_older_than_the_kept_accounts_is_not_recorded(db):
    keep = jr_account(db)
    _merge(db, keep, held_copy(db, keep, balance=(date(2026, 10, 25), 1)))
    assert _snaps(db, keep) == {BALANCE_DAY: BALANCE}


def test_after_a_merge_the_next_syncs_bring_no_copies(db):
    app, state = make_fake()
    jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        sync(db, http, link, LATER)
        keep = feed_account(db, "sfin:jr-joint")
        _merge(db, keep, db.scalar(select(HeldFeed)))
        sync(db, http, link, LATER + timedelta(hours=1))
        sync(db, http, link, LATER + timedelta(hours=2))
    assert _ids(db, keep) == ["jr-0", "jr-1", "jr-2", "jr-3", "jr-4"]


def test_merging_two_accounts_drops_the_copies_moves_the_rest_and_deletes_the_other(db):
    keep, other = in_book_pair(db, other_days=JOINT_DAYS + [WIRE])
    oid = other.id
    m = _merge(db, keep, other)
    assert (m.dropped, m.kept_new) == (5, 1)
    assert db.get(Account, oid) is None
    assert sorted(f.external_id for f in db.scalars(select(AccountFeed).where(AccountFeed.account_id == keep.id))) == [
        "sfin:jr-joint", "sfin:sam-joint"]
    assert _ids(db, keep) == ["jr-0", "jr-1", "jr-2", "jr-3", "jr-4", "sam-5"]
    aliases = db.scalars(select(FeedTxnAlias).order_by(FeedTxnAlias.external_id)).all()
    assert [a.external_id for a in aliases] == [f"sam-{i}" for i in range(5)]
    assert {a.account_id for a in aliases} == {keep.id}
    assert db.scalar(select(UndoEntry.action)) == "merge"


def test_one_to_one_keeps_both_coffees_and_drops_both_copies(db):
    """Review Focus 1: Sam's login also has a third coffee that day, which is new."""
    keep, other = in_book_pair(db, other_days=JOINT_DAYS + [(date(2026, 10, 23), -5_00, "COFFEE")])
    m = _merge(db, keep, other)
    assert (m.dropped, m.kept_new) == (5, 1)
    assert db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.account_id == keep.id, Transaction.raw_description == "COFFEE")) == 3


def test_notes_a_category_a_business_answer_and_a_reimbursable_mark_carry_onto_the_match(db):
    keep, other = in_book_pair(db)
    payer = Reimburser(name="Acme")
    db.add(payer)
    db.flush()
    d = txn(db, other, "sam-3")
    d.category, d.category_source, d.merchant, d.reviewed_at = "fees", CategorySource.correction, "Betterment", NOW
    d.business_pct, d.is_business, d.business_source, d.business_answered_at = 100, True, "manual", NOW
    d.reimburser_id, d.reimburse_source = payer.id, "manual"
    db.add(TransactionNote(transaction_id=d.id, author_id=1, author_name="JR", body="the Q3 fee", created_at=NOW))
    # a copy whose match has its own note: notes are a thread, so the copy's moves over beside it (nothing is lost)
    db.add_all([TransactionNote(transaction_id=txn(db, other, "sam-0").id, author_id=2, author_name="Sam",
                                body="Sam's note", created_at=NOW),
                TransactionNote(transaction_id=txn(db, keep, "jr-0").id, author_id=1, author_name="JR",
                                body="JR's note", created_at=NOW)])
    db.commit()
    match_id, first_id = txn(db, keep, "jr-3").id, txn(db, keep, "jr-0").id
    _merge(db, keep, other)
    m = db.get(Transaction, match_id)
    assert (m.category, m.category_source, m.merchant, m.reviewed_at) == ("fees", CategorySource.correction,
                                                                          "Betterment", NOW)
    assert (m.business_pct, m.is_business, m.business_source, m.business_answered_at) == (100, True, "manual", NOW)
    assert (m.reimburser_id, m.reimburse_source) == (payer.id, "manual")
    notes: dict[int, list[str]] = {}
    for n in db.scalars(select(TransactionNote).order_by(TransactionNote.id)):
        notes.setdefault(n.transaction_id, []).append(n.body)
    assert {k: sorted(v) for k, v in notes.items()} == {match_id: ["the Q3 fee"], first_id: ["JR's note", "Sam's note"]}


def test_a_dropped_copys_nickname_carries_onto_a_match_that_has_none(db):
    keep, other = in_book_pair(db)
    txn(db, other, "sam-3").nickname = "Betterment fee"
    db.commit()
    match_id = txn(db, keep, "jr-3").id
    _merge(db, keep, other)
    assert db.get(Transaction, match_id).nickname == "Betterment fee"


def test_the_matchs_own_nickname_stands(db):
    keep, other = in_book_pair(db)
    txn(db, other, "sam-3").nickname = "Sam's name for it"
    txn(db, keep, "jr-3").nickname = "JR's name for it"
    db.commit()
    match_id = txn(db, keep, "jr-3").id
    _merge(db, keep, other)
    assert db.get(Transaction, match_id).nickname == "JR's name for it"


def test_transfers_are_paired_again_with_the_match(db):
    keep, other = in_book_pair(db)
    chk = make_account(db, "Checking")
    x = make_txn(db, chk, date(2026, 10, 21), -500_00, "TRANSFER TO BETTERMENT", category="transfer",
                 is_transfer=True, category_source=CategorySource.rule)
    dep = txn(db, other, "sam-0")
    x.transfer_peer_id, dep.transfer_peer_id = dep.id, x.id
    dep.category, dep.is_transfer, dep.category_source = "transfer", True, CategorySource.rule
    db.commit()
    jr_dep, xid = txn(db, keep, "jr-0").id, x.id
    _merge(db, keep, other)
    x, d = db.get(Transaction, xid), db.get(Transaction, jr_dep)
    assert (x.transfer_peer_id, d.transfer_peer_id, x.category, d.category) == (jr_dep, xid, "transfer", "transfer")


def test_the_other_accounts_links_follow_it(db):
    keep, other = in_book_pair(db)
    oid = other.id
    db.add_all([
        ImportBatch(account_id=oid, filename="sam.csv", format="generic", row_count=0, imported_at=NOW, imported_by=1),
        Holding(account_id=oid, as_of=BALANCE_DAY, symbol="VTI", name="Total Stock", shares_milli=1000,
                market_value_cents=50_000),
        Flag(check="large", severity="normal", status="open", account_id=oid, summary="$9,000 out", title="Large"),
        BusinessRule(kind="account", account_id=oid, pct=100, label="Everything in it is business"),
        SetAside(name="Fees", kind="one_off", amount_cents=10_000, due_year=2027, due_month=1,
                 first_month=date(2026, 11, 1), account_id=oid),
        Fact(key=LINK_KEY, value=str(oid), as_of=BALANCE_DAY),
        AdvisorAlias(kind="account", target=str(oid), alias="Account 7"),
        HeldFeed(external_id="sfin:kim-joint", institution_id=other.institution_id, name="Joint Taxable",
                 currency="USD", candidate_account_id=oid, balance_cents=1, balance_date=BALANCE_DAY, payload="[]",
                 first_seen_at=NOW, last_seen_at=NOW)])
    db.commit()
    _merge(db, keep, other)
    for model in (ImportBatch, Holding, Flag, BusinessRule, SetAside):
        assert db.scalar(select(model.account_id)) == keep.id, model.__name__
    assert db.scalar(select(Fact.value).where(Fact.key == LINK_KEY)) == str(keep.id)
    assert db.scalar(select(AdvisorAlias.target)) == str(keep.id)
    assert db.scalar(select(HeldFeed.candidate_account_id)) == keep.id


def test_the_kept_accounts_own_advisor_alias_stays_and_the_others_goes(db):
    keep, other = in_book_pair(db)
    db.add_all([AdvisorAlias(kind="account", target=str(keep.id), alias="Account 1"),
                AdvisorAlias(kind="account", target=str(other.id), alias="Account 2")])
    db.commit()
    _merge(db, keep, other)
    assert [(a.target, a.alias) for a in db.scalars(select(AdvisorAlias))] == [(str(keep.id), "Account 1")]


def test_a_child_link_moves_only_when_the_kept_account_has_none(db):
    keep, other = in_book_pair(db)
    kid = Child(label="Kid 2", birth_year=2015, cost_level="in_state_public", account_id=other.id)
    db.add(kid)
    db.commit()
    _merge(db, keep, other)
    assert db.get(Child, kid.id).account_id == keep.id


def test_when_both_have_a_child_or_an_item_the_others_link_is_dropped(db):
    keep, other = in_book_pair(db)
    mine = Child(label="Kid 1", birth_year=2013, cost_level="in_state_public", account_id=keep.id)
    theirs = Child(label="Kid 2", birth_year=2015, cost_level="in_state_public", account_id=other.id)
    items = [InventoryItem(kind="account", name=n, owner="joint", status="confirmed", account_id=a.id)
             for n, a in (("JR's", keep), ("Sam's", other))]
    db.add_all([mine, theirs, *items])
    db.commit()
    _merge(db, keep, other)
    assert (db.get(Child, mine.id).account_id, db.get(Child, theirs.id).account_id) == (keep.id, None)
    assert [db.get(InventoryItem, i.id).account_id for i in items] == [keep.id, None]


def test_the_other_accounts_newer_snapshots_are_copied_and_its_own_go(db):
    keep, other = in_book_pair(db, other_balance=(date(2026, 10, 29), BALANCE + 7_00))
    db.add(BalanceSnapshot(account_id=other.id, as_of=date(2026, 10, 20), balance_cents=1))
    db.commit()
    oid = other.id
    _merge(db, keep, other)
    assert _snaps(db, keep) == {BALANCE_DAY: BALANCE, date(2026, 10, 29): BALANCE + 7_00}
    assert db.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == oid)).all() == []


def test_a_dropped_copys_keep_both_set_aside_match_flag_and_tax_mark_go_with_it(db):
    keep, other = in_book_pair(db)
    d, kept = txn(db, other, "sam-3"), txn(db, keep, "jr-1")
    sa = SetAside(name="Fees", kind="one_off", amount_cents=1_250, due_year=2026, due_month=10,
                  first_month=date(2026, 10, 1))
    db.add(sa)
    db.flush()
    db.add_all([DuplicateKeep(a_id=kept.id, b_id=d.id),
                SetAsideMatch(transaction_id=d.id, set_aside_id=sa.id, due_on=date(2026, 10, 24), how="hand"),
                Flag(check="large", severity="normal", status="open", transaction_id=d.id, summary="fee", title="Fee"),
                TaxState(key=f"payment:{d.id}", value="estimate")])
    db.flush()
    flag = db.scalar(select(Flag))
    add_event(db, flag.id, "flagged", NOW)
    db.add_all([WatchKnown(payee_key="betterment", payee_name="Betterment", check="large", flag_id=flag.id,
                           added_by=1),
                MailOutbox(kind="urgent", flag_id=flag.id, status="pending", next_try_at=NOW)])
    db.commit()
    did = d.id
    _merge(db, keep, other)
    assert db.get(Transaction, did) is None
    assert db.scalars(select(DuplicateKeep)).all() == [] and db.scalars(select(SetAsideMatch)).all() == []
    assert db.scalars(select(Flag)).all() == [] and db.get(TaxState, f"payment:{did}") is None
    assert db.scalars(select(FlagEvent)).all() == []
    assert db.scalar(select(WatchKnown.flag_id)) is None and db.scalar(select(MailOutbox.flag_id)) is None


def test_the_others_new_account_event_is_resolved_and_its_questions_go(db):
    keep, other = in_book_pair(db)
    log_event(db, "info", "system", "New account 'Joint Taxable' from Betterment needs its type and owner set in "
              "Settings", actionable=True)
    db.add(SameAccountAnswer(account_id=keep.id, other_account_id=other.id, answer="open", match_count=5,
                             created_at=NOW))
    db.commit()
    _merge(db, keep, other)
    assert db.scalar(select(EventLog.resolved_at)) == AT
    assert db.scalars(select(SameAccountAnswer)).all() == []


def test_when_both_still_need_a_type_only_the_newer_event_goes(db):
    keep, other = in_book_pair(db)
    keep.type = AccountType.unknown
    for _ in range(2):
        log_event(db, "info", "system", "New account 'Joint Taxable' from Betterment needs its type and owner set in "
                  "Settings", actionable=True)
    db.commit()
    _merge(db, keep, other)
    assert [e.resolved_at for e in db.scalars(select(EventLog).order_by(EventLog.id))] == [None, AT]


def test_a_file_row_both_accounts_share_is_dropped_too(db):
    """Engineering choice 13: the unique bank id per account forbids moving it."""
    keep, other = in_book_pair(db)
    make_txn(db, keep, date(2026, 9, 15), -9_99, "FILE ROW", external_id="csv-77")
    make_txn(db, other, date(2026, 9, 15), -9_99, "FILE ROW", external_id="csv-77")
    assert _merge(db, keep, other).dropped == 6


def test_preview_counts_what_merge_into_would_do_and_changes_nothing(db):
    keep, other = in_book_pair(db, other_days=JOINT_DAYS + [WIRE])
    assert preview(db, keep.id, other.id) == (5, 1)
    assert len(_ids(db, other)) == 6 and db.scalars(select(UndoEntry)).all() == []


def test_merge_into_refuses_what_it_cannot_merge(db):
    keep, other = in_book_pair(db)
    house = make_account(db, "House", type="property")
    for k, o, error, status in ((keep, keep, "Choose another account to merge into.", 422),
                                (keep, house, "Only two accounts that come from a bank can be merged here.", 422),
                                (other, keep, "Choose an account of the same type.", 422),   # into Type not set
                                (keep, None, "No such account.", 404)):
        with pytest.raises(MergeRefused, match=error) as e:
            check(db, k, o)
        assert e.value.status == status
    check(db, keep, other)                       # the one merged away has no type yet: the kept account's stands
    other.type = AccountType.roth_ira
    with pytest.raises(MergeRefused, match="Choose an account of the same type."):
        check(db, keep, other)                   # two types that are known and differ
    other.type, other.is_active = AccountType.brokerage_taxable, False
    with pytest.raises(MergeRefused, match="Choose an account that's still open."):
        check(db, keep, other)
    other.is_active = True
    check(db, keep, other)                                    # two active bank accounts of one type: fine


def _holding(account_id, day, symbol, cents, import_id=None):
    return Holding(account_id=account_id, as_of=day, symbol=symbol, name=symbol, shares_milli=1000,
                   market_value_cents=cents, import_id=import_id)


def test_holdings_follow_a_day_at_a_time_and_the_kept_accounts_day_stands(db):
    """Investment views with same account: both accounts can hold VTI on one day. For a day the kept account has, its
    positions stand and the other's go; the other's other days move over, with the positions import that wrote them."""
    keep, other = in_book_pair(db)
    kid, oid = keep.id, other.id
    imp = PositionsImport(account_id=oid, as_of=date(2026, 10, 20), filename="sam.csv", row_count=1, imported_at=NOW,
                          imported_by=1)
    db.add(imp)
    db.flush()
    db.add_all([_holding(kid, BALANCE_DAY, "VTI", 50_000), _holding(oid, BALANCE_DAY, "VTI", 49_000),
                _holding(oid, BALANCE_DAY, "BND", 1_000), _holding(oid, date(2026, 10, 20), "VTI", 48_000, imp.id)])
    db.commit()
    _merge(db, keep, other)
    rows = db.execute(select(Holding.as_of, Holding.symbol, Holding.market_value_cents, Holding.import_id)
                      .where(Holding.account_id == kid).order_by(Holding.as_of)).all()
    assert [tuple(r) for r in rows] == [(date(2026, 10, 20), "VTI", 48_000, imp.id), (BALANCE_DAY, "VTI", 50_000, None)]
    assert db.scalar(select(func.count()).select_from(Holding)) == 2
    assert db.scalar(select(PositionsImport.account_id)) == kid


@pytest.mark.parametrize("keep_type, vehicle_loan", [(AccountType.brokerage_taxable, None), (AccountType.loan, "keep")])
def test_the_kept_account_takes_the_others_investment_fields_where_it_has_none(db, keep_type, vehicle_loan):
    keep, other = in_book_pair(db)
    keep.type = keep_type
    seen_old, seen_new = NOW - timedelta(days=3), NOW
    keep.sends_holdings, keep.holdings_seen_at = False, seen_old
    keep.sends_transactions, keep.transactions_seen_at = True, seen_new
    other.advisory_fee_bp, other.sends_holdings, other.holdings_seen_at = 25, True, seen_new
    other.sends_transactions, other.transactions_seen_at = False, seen_old
    car = make_account(db, "Subaru", type=AccountType.vehicle)
    car.loan_id = other.id
    db.commit()
    kid, car_id = keep.id, car.id
    _merge(db, keep, other)
    k = db.get(Account, kid)
    assert (k.advisory_fee_bp, k.loan_id) == (25, None)
    assert (k.sends_holdings, k.holdings_seen_at) == (True, seen_new)          # either sends: it sends
    assert (k.sends_transactions, k.transactions_seen_at) == (True, seen_new)  # its own, the later already
    assert db.get(Account, car_id).loan_id == (kid if vehicle_loan == "keep" else None)


def test_the_kept_accounts_own_fee_stands(db):
    keep, other = in_book_pair(db)
    keep.advisory_fee_bp, other.advisory_fee_bp = 15, 25
    db.commit()
    kid = keep.id
    _merge(db, keep, other)
    assert db.get(Account, kid).advisory_fee_bp == 15
