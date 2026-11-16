"""Came from (JR, Oct 31): where a transaction came from, from data that already exists: its import file
(import_batch: the file's name, when, who), its SimpleFIN feed (the feed's institution and its last sync), or neither
(a person typed it in). A row with a bank id and no feed was synced before feeds existed: its account's institution
(plan Engineering choice 3). Never read by the advisor, Ask's About or the gateway
(tests/advisor/test_came_from_never_reaches_ask.py). The PDF round adds the statement's period, page and check here."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountFeed, ImportBatch, Institution, Transaction


def came_from(db: Session, t: Transaction, people: dict[int, str], manager: bool) -> dict:
    if t.import_batch_id is not None:
        b = db.get(ImportBatch, t.import_batch_id)
        count = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.import_batch_id == b.id))
        line = {"label": b.filename, "at": b.imported_at.isoformat(), "batch_id": b.id, "by": people.get(b.imported_by),
                "count": count, "undoable": manager and b.rolled_back_at is None}
        if b.format in ("pdf", "pdf_scan"):           # PDF statements spec P42: the period, the page, the check
            return {"kind": "statement", **line,
                    "period": {"start": b.period_start.isoformat(), "end": b.period_end.isoformat()}
                    if b.period_start and b.period_end else None,
                    "page": t.statement_page, "check": b.check_state, "gap_cents": b.check_gap_cents}
        return {"kind": "file", **line}
    if t.external_id is not None:
        feed = db.get(AccountFeed, t.feed_id) if t.feed_id is not None else None
        account = db.get(Account, t.account_id)
        iid = feed.institution_id if feed else account.institution_id if account else None
        inst = db.get(Institution, iid) if iid is not None else None
        if inst is None:            # no bank to name: the account's, as the line's quiet fallback, never a 500
            return {"kind": "simplefin", "label": account.name if account else None, "at": None}
        return {"kind": "simplefin", "label": inst.name, "at": inst.last_sync_at.isoformat() if inst.last_sync_at else None}
    return {"kind": "typed", "label": None, "at": None}
