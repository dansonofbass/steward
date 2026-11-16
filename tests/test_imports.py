from datetime import date

import pytest
from sqlalchemy import func, select

from steward.db.models import ImportBatch, Transaction
from steward.deps import now
from steward.services.imports import commit_batch, list_batches, rollback_batch
from steward.services.importers.base import ParsedRow
from tests.factories import make_account, make_txn, make_user


def _rows():
    return [
        ParsedRow(date(2026, 10, 3), -5412, "GREENLEAF MARKET #12", None),
        ParsedRow(date(2026, 10, 1), 412000, "PAYROLL ACME CORP", None),
        ParsedRow(date(2026, 10, 1), 412000, "PAYROLL ACME CORP", None),  # dup inside the file
    ]


def test_commit_skips_flagged_and_sets_batch(db):
    u = make_user(db)
    a = make_account(db)
    rows = _rows()
    b = commit_batch(db, a.id, "x.csv", "chase_card", rows, u.id, skip=[False, False, True], now=now())
    db.commit()
    assert b.row_count == 2
    txns = db.scalars(select(Transaction).where(Transaction.import_batch_id == b.id)).all()
    assert len(txns) == 2 and {t.category for t in txns} == {"uncategorized", "income"}
    assert list_batches(db)[0].id == b.id


def test_commit_marks_business_account_rows(db):
    u = make_user(db)
    a = make_account(db, owner="business")
    b = commit_batch(db, a.id, "x.csv", "chase_card", _rows()[:1], u.id, [False], now())
    db.commit()
    t = db.scalars(select(Transaction).where(Transaction.import_batch_id == b.id)).one()
    assert t.is_business is True


def test_list_batches_newest_first(db):
    from datetime import timedelta
    u = make_user(db)
    a = make_account(db)
    t0 = now()
    first = commit_batch(db, a.id, "1.csv", "chase_card", [], u.id, [], t0)
    second = commit_batch(db, a.id, "2.csv", "chase_card", [], u.id, [], t0 + timedelta(hours=1))
    db.commit()
    assert [b.id for b in list_batches(db)] == [second.id, first.id]


def test_rollback_deletes_rows_and_unpairs_transfers(db):
    u = make_user(db)
    chk, sav = make_account(db, "Checking"), make_account(db, "Savings", type="savings", institution_name="Other")
    survivor = make_txn(db, sav, date(2026, 10, 5), 100000, "TRANSFER FROM CHECKING")
    b = commit_batch(db, chk.id, "x.csv", "chase_checking",
                     [ParsedRow(date(2026, 10, 5), -100000, "TRANSFER TO SAVINGS", None)], u.id, [False], now())
    db.commit()
    gone = db.scalars(select(Transaction).where(Transaction.import_batch_id == b.id)).one()
    # pair them by hand the way transfers.py will
    for x, y in ((gone, survivor), (survivor, gone)):
        x.is_transfer, x.category, x.transfer_peer_id = True, "transfer", y.id
    db.commit()
    assert rollback_batch(db, b.id, now()) == 1
    db.commit(); db.refresh(survivor)
    assert survivor.is_transfer is False and survivor.transfer_peer_id is None and survivor.category == "uncategorized"
    assert db.get(ImportBatch, b.id).rolled_back_at is not None
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.import_batch_id == b.id)) == 0
    with pytest.raises(ValueError):
        rollback_batch(db, b.id, now())


def test_rollback_with_both_halves_of_a_pair_in_the_batch(db):
    u = make_user(db)
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    b1 = commit_batch(db, chk.id, "a.csv", "chase_checking",
                      [ParsedRow(date(2026, 10, 5), -100000, "MOVE OUT", None)], u.id, [False], now())
    b2 = commit_batch(db, sav.id, "b.csv", "chase_checking",
                      [ParsedRow(date(2026, 10, 5), 100000, "MOVE IN", None)], u.id, [False], now())
    db.commit()
    # Move the second row into the first batch so one rollback covers both halves.
    for t in db.scalars(select(Transaction).where(Transaction.import_batch_id == b2.id)):
        t.import_batch_id = b1.id
    db.commit()
    peers = db.scalars(select(Transaction).where(Transaction.import_batch_id == b1.id)).all()
    assert len(peers) == 2 and peers[0].transfer_peer_id == peers[1].id and peers[1].transfer_peer_id == peers[0].id
    assert rollback_batch(db, b1.id, now()) == 2
    db.commit()
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0


def test_unknown_batch_and_account_raise_plain_errors(db):
    with pytest.raises(ValueError, match="doesn't exist"):
        rollback_batch(db, 999, now())
    with pytest.raises(ValueError, match="account doesn't exist"):
        commit_batch(db, 999, "x.csv", "chase_card", [], 1, [], now())
