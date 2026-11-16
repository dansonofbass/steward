"""Same-account spec, Undo: a merge is undone all or nothing within 15 minutes, through the same undo() every Undo
uses. It puts every table back exactly, and refuses (409) once anything the merge left has changed since."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from steward.db.models import (Account, AccountFeed, AdvisorAlias, FeedTxnAlias, CategorySource, Child, DuplicateKeep, Fact,
                               HeldFeed, Holding, SameAccountAnswer, SetAside, SetAsideMatch, StatementLayout, TaxState, Transaction,
                               TransactionNote, UndoEntry, UndoText)
from steward.events import log_event
from steward.services.home_value import LINK_KEY
from steward.services.same_account import journal
from steward.services.same_account.merge import merge
from steward.services.undo import CHANGED_SINCE, GONE, NO_UNDO, UndoRefused, capturing, undo
from tests.factories import make_account, make_txn
from tests.fake_simplefin import make_fake
from tests.same_account_fixtures import (BALANCE, BALANCE_DAY, JOINT_DAYS, LATER, NOW, feed_account, held_copy,
                                         in_book_pair, jr_account, jr_login, linked, sam_login, snapshot, sync, txn)

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")   # P36: no note or name in an undo entry

AT = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
SOON = AT + timedelta(minutes=5)
WIRE = (date(2026, 10, 27), -40_00, "WIRE FEE")


def _decorated_pair(db):
    """A pair with something on every kind of row a merge moves, drops, carries or pairs again."""
    keep, other = in_book_pair(db, other_days=JOINT_DAYS + [WIRE], other_balance=(date(2026, 10, 29), BALANCE + 7_00))
    oid = other.id
    d = txn(db, other, "sam-3")
    d.category, d.category_source, d.reviewed_at = "fees", CategorySource.correction, NOW
    db.add(TransactionNote(transaction_id=d.id, author_id=1, author_name="JR", body="the Q3 fee", created_at=NOW))
    chk = make_account(db, "Checking")
    x = make_txn(db, chk, date(2026, 10, 21), -500_00, "TRANSFER TO BETTERMENT", category="transfer",
                 is_transfer=True, category_source=CategorySource.rule)
    dep = txn(db, other, "sam-0")
    x.transfer_peer_id, dep.transfer_peer_id = dep.id, x.id
    dep.category, dep.is_transfer, dep.category_source = "transfer", True, CategorySource.rule
    sa = SetAside(name="Fees", kind="one_off", amount_cents=1_250, due_year=2026, due_month=10,
                  first_month=date(2026, 10, 1), account_id=oid)
    db.add(sa)
    db.flush()
    paid = txn(db, other, "sam-4")
    db.add_all([SetAsideMatch(transaction_id=paid.id, set_aside_id=sa.id, due_on=date(2026, 10, 26), how="hand"),
                DuplicateKeep(a_id=txn(db, keep, "jr-1").id, b_id=txn(db, other, "sam-2").id),
                TaxState(key=f"payment:{paid.id}", value="other"),
                Holding(account_id=oid, as_of=BALANCE_DAY, symbol="VTI", name="Total Stock", shares_milli=1000,
                        market_value_cents=50_000),
                Child(label="Kid 2", birth_year=2015, cost_level="in_state_public", account_id=oid),
                Fact(key=LINK_KEY, value=str(oid), as_of=BALANCE_DAY),
                AdvisorAlias(kind="account", target=str(oid), alias="Account 2"),
                SameAccountAnswer(account_id=keep.id, other_account_id=oid, answer="open", match_count=5,
                                  created_at=NOW)])
    log_event(db, "info", "system", "New account 'Joint Taxable' from Betterment needs its type and owner set in "
              "Settings", actionable=True)
    db.commit()
    return keep, other


def test_undo_restores_every_table_exactly(db):
    """Review Focus 3, the clean case: nothing changed since, so every row of every table is as it was."""
    keep, other = _decorated_pair(db)
    oid, before = other.id, snapshot(db)
    m = merge(db, keep.id, oid, user_id=1, now=AT)
    db.commit()
    assert snapshot(db) != before and db.get(Account, oid) is None
    done = undo(db, m.undo, 1, SOON)
    db.commit()
    assert done.target is None and done.count == 5        # the five dropped copies came back
    assert snapshot(db) == before


def test_undo_of_a_held_merge_puts_the_held_feed_back_and_takes_out_what_came_in(db):
    keep = jr_account(db)
    h = held_copy(db, keep, days=JOINT_DAYS + [WIRE], balance=(date(2026, 10, 28), BALANCE - 40_00))
    before = snapshot(db)
    m = merge(db, keep.id, h, user_id=1, now=AT)
    db.commit()
    assert undo(db, m.undo, 1, SOON).count == 1            # the one new row it brought in went
    db.commit()
    assert snapshot(db) == before and db.get(HeldFeed, h.id) is not None


def test_undo_refuses_after_a_resort_of_a_carried_match(db):
    """Review Focus 3: the match took the copy's category, and a person sorted it again since."""
    keep, other = in_book_pair(db)
    d = txn(db, other, "sam-3")
    d.category, d.category_source = "fees", CategorySource.correction
    db.commit()
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    match = txn(db, keep, "jr-3")
    assert match.category == "fees"
    match.category = "taxes"
    db.commit()
    before = snapshot(db)
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert (e.value.status, e.value.message) == (409, CHANGED_SINCE)
    db.rollback()
    assert snapshot(db) == before


def test_undo_refuses_once_a_sync_used_the_merged_feed(db):
    """Review Focus 3: a row came in through the feed the merge added; undoing would leave it orphaned."""
    keep = jr_account(db)
    m = merge(db, keep.id, held_copy(db, keep), user_id=1, now=AT)
    db.commit()
    sam_feed = db.scalar(select(AccountFeed.id).where(AccountFeed.external_id == "sfin:sam-joint"))
    db.add(Transaction(account_id=keep.id, posted_at=date(2026, 10, 28), amount_cents=-7_00, raw_description="FEE",
                       external_id="sam-9", feed_id=sam_feed, imported_at=SOON))
    db.commit()
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert e.value.status == 409


def test_a_sync_that_brings_nothing_new_through_the_merged_feed_leaves_undo_working(db):
    """A scheduled sync inside the 15 minutes refreshes the merged feed's name and last seen, and nothing else."""
    app, state = make_fake()
    jr_login(state)
    with TestClient(app) as http:
        link = linked(db, http)
        sync(db, http, link)
        sam_login(state)
        sync(db, http, link, LATER)
        keep, h = feed_account(db, "sfin:jr-joint"), db.scalar(select(HeldFeed))
        hid, merged_at = h.id, LATER + timedelta(minutes=1)
        m = merge(db, keep.id, h, user_id=1, now=merged_at)
        db.commit()
        feed = db.scalar(select(AccountFeed).where(AccountFeed.external_id == "sfin:sam-joint"))
        seen_before, rows_before = feed.last_seen_at, db.scalar(select(func.count()).select_from(Transaction))
        next(a for a in state.accounts if a.id == "sam-joint").name = "Joint Taxable (Sam)"
        sync(db, http, link, merged_at + timedelta(minutes=4))     # the same rows again: nothing new
    db.expire_all()
    feed = db.scalar(select(AccountFeed).where(AccountFeed.external_id == "sfin:sam-joint"))
    assert feed.last_seen_at != seen_before and feed.name == "Joint Taxable (Sam)"
    assert db.scalar(select(func.count()).select_from(Transaction)) == rows_before
    undo(db, m.undo, 1, merged_at + timedelta(minutes=10))
    db.commit()
    assert db.get(HeldFeed, hid) is not None
    assert db.scalar(select(AccountFeed).where(AccountFeed.external_id == "sfin:sam-joint")) is None


def test_undo_refuses_when_a_row_it_brought_in_was_sorted_since(db):
    keep = jr_account(db)
    m = merge(db, keep.id, held_copy(db, keep, days=JOINT_DAYS + [WIRE]), user_id=1, now=AT)
    db.commit()
    new = txn(db, keep, "sam-5")
    new.category, new.category_source = "fees", CategorySource.correction
    db.commit()
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert e.value.status == 409


def test_undo_refuses_when_a_row_was_paired_with_a_merged_in_row_since(db):
    """Pre-flight F5: restore would null the peer but leave that row's category 'transfer'; so refuse instead."""
    keep = jr_account(db)
    m = merge(db, keep.id, held_copy(db, keep, days=JOINT_DAYS + [WIRE]), user_id=1, now=AT)
    db.commit()
    new = txn(db, keep, "sam-5")
    chk = make_account(db, "Checking")
    other = make_txn(db, chk, date(2026, 10, 27), 40_00, "TRANSFER IN", category="transfer", is_transfer=True,
                     category_source=CategorySource.rule)
    other.transfer_peer_id = new.id
    db.commit()
    before = snapshot(db)
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert e.value.status == 409
    db.rollback()
    assert snapshot(db) == before


def test_undo_refuses_when_the_deleted_accounts_id_was_taken_again(db):
    keep, other = in_book_pair(db)
    oid = other.id
    m = merge(db, keep.id, oid, user_id=1, now=AT)
    db.commit()
    db.expunge_all()
    again = make_account(db, "Brand new")
    assert again.id == oid                           # SQLite hands the highest id out again
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert e.value.status == 409


def test_an_undo_is_used_once_by_the_person_who_merged_within_15_minutes(db):
    keep, other = in_book_pair(db)
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    for user, at, status, message in ((2, SOON, 404, NO_UNDO), (1, AT + timedelta(minutes=15), 410, GONE)):
        with pytest.raises(UndoRefused) as e:
            undo(db, m.undo, user, at)
        assert (e.value.status, e.value.message) == (status, message)
    undo(db, m.undo, 1, AT + timedelta(minutes=14))
    db.commit()
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, AT + timedelta(minutes=14))
    assert e.value.status == 410


def test_undo_refuses_once_a_sync_used_a_feed_the_merge_moved(db):
    """A merged-in account's feed now belongs to the kept account; rows a sync adds through it are not the merge's."""
    keep, other = in_book_pair(db)
    moved = db.scalar(select(AccountFeed.id).where(AccountFeed.account_id == other.id))
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    assert db.get(AccountFeed, moved).account_id == keep.id
    before = snapshot(db)
    for extra in (
        lambda: db.add(Transaction(account_id=keep.id, posted_at=date(2026, 10, 28), amount_cents=-7_00,
                                   raw_description="FEE", external_id="sam-new", feed_id=moved, imported_at=SOON)),
        lambda: db.add(FeedTxnAlias(account_id=keep.id, feed_id=moved, external_id="sam-alias",
                                    transaction_id=txn(db, keep, "jr-1").id)),
    ):
        extra()
        db.commit()
        before = snapshot(db)
        with pytest.raises(UndoRefused) as e:
            undo(db, m.undo, 1, SOON)
        assert (e.value.status, e.value.message) == (409, CHANGED_SINCE)
        db.rollback()
        assert snapshot(db) == before
        if db.scalars(select(Transaction).where(Transaction.feed_id == moved, Transaction.external_id == "sam-new")).first():
            db.query(Transaction).filter(Transaction.external_id == "sam-new").delete()
            db.commit()


def test_a_failed_restore_changes_nothing_and_can_be_retried(db, monkeypatch):
    """The all-or-nothing savepoint: an insert that fails part way puts back everything it had done."""
    keep, other = _decorated_pair(db)
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    before = snapshot(db)
    real, calls = journal.insert, []

    def failing(table):
        calls.append(table)
        if len(calls) == 2:
            raise IntegrityError("insert", {}, Exception("taken"))
        return real(table)

    monkeypatch.setattr(journal, "insert", failing)
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert (e.value.status, e.value.message) == (409, CHANGED_SINCE)
    assert len(calls) >= 2                          # it got part way before failing
    db.rollback()
    assert snapshot(db) == before
    assert db.get(UndoEntry, m.undo).used_at is None
    monkeypatch.undo()
    undo(db, m.undo, 1, SOON)                       # retried, it works
    db.commit()


def test_undo_puts_back_holdings_imports_and_the_investment_fields_exactly(db):
    """Investment views with same account: the dropped day's holdings, the moved ones, the positions import, the kept
    account's carried fields and a vehicle's loan all go back as they were."""
    from steward.db.models import PositionsImport
    keep, other = in_book_pair(db)
    kid, oid = keep.id, other.id
    imp = PositionsImport(account_id=oid, as_of=date(2026, 10, 20), filename="sam.csv", row_count=1, imported_at=NOW,
                          imported_by=1)
    db.add(imp)
    db.flush()
    for aid, day, sym, cents, iid in ((kid, BALANCE_DAY, "VTI", 50_000, None), (oid, BALANCE_DAY, "VTI", 49_000, None),
                                      (oid, date(2026, 10, 20), "VTI", 48_000, imp.id)):
        db.add(Holding(account_id=aid, as_of=day, symbol=sym, name=sym, shares_milli=1000, market_value_cents=cents,
                       import_id=iid))
    other.advisory_fee_bp, other.sends_holdings, other.holdings_seen_at = 25, True, NOW
    car = make_account(db, "Subaru", type="vehicle")
    car.loan_id = oid
    db.commit()
    before = snapshot(db)
    m = merge(db, kid, oid, user_id=1, now=AT)
    db.commit()
    assert db.get(Account, kid).advisory_fee_bp == 25 and db.get(Account, car.id).loan_id is None
    undo(db, m.undo, 1, SOON)
    db.commit()
    assert snapshot(db) == before


def test_a_sync_that_refreshes_what_the_kept_account_sends_leaves_undo_working(db):
    """What the bank sent, and when, changes at every sync; the merge's Undo doesn't count it as a change since."""
    keep, other = in_book_pair(db)
    other.sends_holdings, other.holdings_seen_at = True, NOW
    db.commit()
    kid, oid = keep.id, other.id
    m = merge(db, kid, oid, user_id=1, now=AT)
    db.commit()
    k = db.get(Account, kid)
    k.sends_transactions, k.transactions_seen_at, k.holdings_seen_at = True, SOON, SOON
    db.commit()
    undo(db, m.undo, 1, SOON)
    db.commit()
    assert db.get(Account, oid) is not None
    k = db.get(Account, kid)
    assert (k.sends_holdings, k.holdings_seen_at) == (None, None)                 # put back as it was before the merge


def test_undo_still_refuses_when_a_carried_fee_was_changed_since(db):
    keep, other = in_book_pair(db)
    other.advisory_fee_bp = 25
    db.commit()
    kid = keep.id
    m = merge(db, kid, other.id, user_id=1, now=AT)
    db.commit()
    db.get(Account, kid).advisory_fee_bp = 30
    db.commit()
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert (e.value.status, e.value.message) == (409, CHANGED_SINCE)


def _texts(db, token) -> list[tuple]:
    return sorted((x.model, x.row_key, x.field, x.value, x.written)
                  for x in db.scalars(select(UndoText).where(UndoText.token == token)))


def test_a_merge_keeps_notes_and_names_out_of_its_undo_entry_and_undo_still_puts_back_every_row(db):
    """P36: the dropped copy's name and the merged account's name go to undo_text, the note moves by id only, and Undo
    puts every row back byte for byte."""
    keep, other = _decorated_pair(db)
    oid, d, mid = other.id, txn(db, other, "sam-3"), txn(db, keep, "jr-3").id
    did, d.nickname = d.id, "Wire to Dr. Alvarez"
    db.commit()
    before = snapshot(db)
    m = merge(db, keep.id, oid, user_id=1, now=AT)
    db.commit()
    entry = db.get(UndoEntry, m.undo)
    stored = entry.before + entry.after
    for text in ("Alvarez", "the Q3 fee", '"JR"', "Joint Taxable"):
        assert text not in stored
    assert _texts(db, m.undo) == sorted([("account", f"[{oid}]", "name", "Joint Taxable", None),
                                         ("transaction", f"[{did}]", "nickname", "Wire to Dr. Alvarez", None),
                                         ("transaction", f"[{mid}]", "nickname", None, "Wire to Dr. Alvarez")],
                                        key=lambda x: x[:2])                  # the last is the name carried over
    undo(db, m.undo, 1, SOON)
    db.commit()
    assert snapshot(db) == before                     # undo_text is in the snapshot too: the entry's rows went
    assert db.get(Transaction, did).nickname == "Wire to Dr. Alvarez"
    assert db.get(Transaction, mid).nickname is None


def test_a_carried_nickname_stays_out_of_every_undo_entry_and_undo_takes_it_off_again(db):
    """The dropped copy's nickname goes onto its match, which had none; the old (empty) name and the one written go to
    undo_text, never to undo_entry, and Undo leaves the match with no name again."""
    keep, other = in_book_pair(db)
    txn(db, other, "sam-3").nickname = "Wire to Dr. Alvarez"
    db.commit()
    mid, before = txn(db, keep, "jr-3").id, snapshot(db)
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    assert db.get(Transaction, mid).nickname == "Wire to Dr. Alvarez"
    entries = db.scalars(select(UndoEntry)).all()
    assert entries and not any("Alvarez" in e.before + e.after for e in entries)
    assert ("transaction", f"[{mid}]", "nickname", None, "Wire to Dr. Alvarez") in _texts(db, m.undo)
    undo(db, m.undo, 1, SOON)
    db.commit()
    assert db.get(Transaction, mid).nickname is None
    assert snapshot(db) == before


def test_undo_refuses_once_a_carried_nickname_was_changed_since(db):
    keep, other = in_book_pair(db)
    txn(db, other, "sam-3").nickname = "Wire to Dr. Alvarez"
    db.commit()
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    txn(db, keep, "jr-3").nickname = "Dr. Alvarez, Q3"
    db.commit()
    before = snapshot(db)
    with pytest.raises(UndoRefused) as e:
        undo(db, m.undo, 1, SOON)
    assert (e.value.status, e.value.message) == (409, CHANGED_SINCE)
    db.rollback()
    assert snapshot(db) == before


def test_a_deleted_note_goes_to_undo_text_and_comes_back_exactly(db):
    """A merge moves a dropped copy's notes, so the journal is driven directly: a note row it deletes keeps its body
    and author in undo_text, and Undo inserts it again as it was."""
    t = make_txn(db, make_account(db, "Old card"), date(2026, 10, 3), -1399, "PAYPAL *DISNEYPLUS", merchant="PayPal")
    t.nickname = "Disney+"
    db.add(TransactionNote(transaction_id=t.id, author_id=1, author_name="Jr Hale", body="zorblax for Dr. Alvarez",
                           created_at=NOW))
    db.commit()
    tid, before = t.id, snapshot(db)
    note_id = db.scalar(select(TransactionNote.id))
    with journal.recording(db) as j:
        j.remove(TransactionNote, TransactionNote.transaction_id == tid)
        j.remove(Transaction, Transaction.id == tid)
        with pytest.raises(ValueError):
            j.change(Transaction, Transaction.id == tid, nickname="x")   # a name never goes into the journal
    token = j.save(1, "merge", AT)
    db.commit()
    entry = db.get(UndoEntry, token)
    assert not any(s in entry.before + entry.after for s in ("zorblax", "Alvarez", "Jr Hale", "Disney+"))
    assert _texts(db, token) == [("transaction", f"[{tid}]", "nickname", "Disney+", None),
                                 ("transaction_note", f"[{note_id}]", "author_name", "Jr Hale", None),
                                 ("transaction_note", f"[{note_id}]", "body", "zorblax for Dr. Alvarez", None)]
    undo(db, token, 1, SOON)
    db.commit()
    assert snapshot(db) == before


def test_a_deleted_statement_layouts_label_goes_to_undo_text(db):
    """A statement layout's label is a bank's name: a journal that deletes the row keeps it in undo_text, and Undo
    puts the row back as it was."""
    lay = StatementLayout(key="k:summit", label="Summit Card Services", kind="card", anchors="[]", rules="{}",
                          model="m", created_at=NOW, confirmed_by=1)
    db.add(lay)
    db.commit()
    lid, before = lay.id, snapshot(db)
    with journal.recording(db) as j:
        j.remove(StatementLayout, StatementLayout.id == lid)
    token = j.save(1, "merge", AT)
    db.commit()
    entry = db.get(UndoEntry, token)
    assert "Summit" not in entry.before + entry.after
    assert _texts(db, token) == [("statement_layout", f"[{lid}]", "label", "Summit Card Services", None)]
    undo(db, token, 1, SOON)
    db.commit()
    assert snapshot(db) == before


def test_a_merges_undo_text_goes_when_its_entry_expires(db):
    keep, other = in_book_pair(db)
    txn(db, other, "sam-3").nickname = "Wire to Dr. Alvarez"
    db.commit()
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    assert len(_texts(db, m.undo)) == 3          # the account's name, the dropped copy's, and the carried one's
    with capturing(db, 1, "sort", AT + timedelta(minutes=16)):    # the next entry purges the expired one
        txn(db, keep, "jr-1").category = "fees"
    db.commit()
    assert db.get(UndoEntry, m.undo) is None
    assert _texts(db, m.undo) == []


def test_an_entry_made_before_undo_text_held_the_names_still_undoes_exactly(db, monkeypatch, undo_entries_hold_no_text):
    """An entry written by the old journal (the account's name in the deleted row) still puts it back."""
    undo_entries_hold_no_text.add("Joint Taxable")      # written the old way on purpose
    keep, other = _decorated_pair(db)
    before = snapshot(db)
    monkeypatch.setattr(journal, "TEXT", {})
    m = merge(db, keep.id, other.id, user_id=1, now=AT)
    db.commit()
    monkeypatch.undo()
    assert "Joint Taxable" in db.get(UndoEntry, m.undo).before and _texts(db, m.undo) == []
    undo(db, m.undo, 1, SOON)
    db.commit()
    assert snapshot(db) == before
