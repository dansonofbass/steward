from datetime import date, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from steward.db.models import Account, BalanceSnapshot, Holding, ImportBatch, PositionsImport, Source, Transaction
from steward.services.categorize import Suggestion
from steward.services.categorizer_client import ModelClient
from steward.services.ingest import ingest_rows
from steward.services.importers.base import ParsedRow
from steward.services.review import forget_duplicate_keeps
from steward.services.transfers import unpair_peers

WINDOW_DAYS = 2


def simplefin_since(db: Session, acct: Account) -> date | None:
    """Earliest date SimpleFIN itself supplied for this account (rows with a bank id and no import file), else None."""
    if acct.source != Source.simplefin:
        return None
    return db.scalar(select(func.min(Transaction.posted_at)).where(
        Transaction.account_id == acct.id, Transaction.external_id.is_not(None),
        Transaction.import_batch_id.is_(None)))


def kept_rows(rows: list[ParsedRow], skip: list[bool]) -> list[ParsedRow]:
    return [r for r, s in zip(rows, skip, strict=True) if not s]


def commit_batch(db: Session, account_id: int, filename: str, fmt: str, rows: list[ParsedRow],
                 imported_by: int, skip: list[bool], now: datetime,
                 model: ModelClient | None = None, household: bool = True,
                 suggestions: list[Suggestion] | None = None, set_id: int | None = None, layout_id: int | None = None,
                 content_sha256: str | None = None, period: tuple[date, date] | None = None, pages: int | None = None,
                 check_state: str | None = None, check_gap_cents: int | None = None,
                 statement_layout_id: int | None = None) -> ImportBatch:
    """`suggestions`, one per kept row, are what the route computed with no transaction open (see ingest_rows)."""
    acct = db.get(Account, account_id)
    if acct is None:
        raise ValueError("That account doesn't exist.")
    batch = ImportBatch(account_id=account_id, filename=filename[:200], format=fmt, row_count=0,
                        imported_at=now, imported_by=imported_by, set_id=set_id, layout_id=layout_id,
                        content_sha256=content_sha256, period_start=period[0] if period else None,
                        period_end=period[1] if period else None, pages=pages, check_state=check_state,
                        check_gap_cents=check_gap_cents, statement_layout_id=statement_layout_id)
    db.add(batch)
    db.flush()
    kept = kept_rows(rows, skip)
    ingest_rows(db, acct, kept, batch=batch, now=now, model=model, household=household, suggestions=suggestions)
    batch.row_count = len(kept)
    db.flush()
    return batch


def rollback_batch(db: Session, batch_id: int, now: datetime) -> int:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise ValueError("That import doesn't exist.")
    if batch.rolled_back_at is not None:
        raise ValueError("That import was already undone.")
    ids = db.scalars(select(Transaction.id).where(Transaction.import_batch_id == batch_id)).all()
    if ids:
        unpair_peers(db, ids)
        forget_duplicate_keeps(db, ids)
        db.execute(update(Transaction).where(Transaction.id.in_(ids)).values(transfer_peer_id=None))
        db.flush()
        for t in db.scalars(select(Transaction).where(Transaction.id.in_(ids))):
            db.delete(t)
    batch.rolled_back_at = now
    db.flush()
    return len(ids)


def undo_snapshot(db: Session, batch: ImportBatch) -> date | None:
    """P40: the balance a statement wrote goes with its Undo while its value is still the one written; a changed one
    stays, and its date is returned so the answer can say so."""
    if batch.snapshot_as_of is None:
        return None
    snap = db.get(BalanceSnapshot, (batch.account_id, batch.snapshot_as_of))
    if snap is None:
        return None
    if snap.balance_cents == batch.snapshot_cents:
        db.delete(snap)
        db.flush()
        return None
    return batch.snapshot_as_of


def undo_holdings(db: Session, batch_id: int, now: datetime) -> int:
    """P40: a statement's holdings go with its Undo (by import_id), and its positions import is marked undone. Only the
    batch that wrote them: a same-day file that was kept wrote none, so its Undo takes none."""
    gone = 0
    for pi in db.scalars(select(PositionsImport).where(PositionsImport.batch_id == batch_id,
                                                       PositionsImport.rolled_back_at.is_(None))):
        gone += db.execute(delete(Holding).where(Holding.import_id == pi.id)).rowcount
        pi.rolled_back_at = now
    db.flush()
    return gone


def list_batches(db: Session) -> list[ImportBatch]:
    return list(db.scalars(select(ImportBatch).order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())))
