"""Export (import/export spec, Export; P23-P25, P29, P30): the transactions CSV, the business report CSV and the
encrypted backup. Managers only (a viewer gets 404, as managers_only answers). Each download writes a log line; a
GET that logs calls begin_write first."""
from __future__ import annotations

import secrets
import shutil
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from steward import deps
from steward.api.body import json_object
from steward.api.business import year_param
from steward.business.report import business_report
from steward.business.settings import business_type
from steward.db.engine import begin_write
from steward.db.models import Account, Transaction, TransactionNote
from steward.deps import NOT_IN_THIS_BOOK, BookContext, book_db, household_only, managers_only, open_book, real_book_only, recorded, viewer_ok
from steward.events import log_event
from steward.inventory.changes import record
from steward.services import book_export
from steward.services.category_labels import label
from steward.services.export_csv import decimal, download, guard, write

router = APIRouter(prefix="/export", dependencies=[Depends(open_book), Depends(real_book_only), Depends(managers_only)])
RANGE = "Choose a start and an end date."
NOT_UNDERSTOOD = "That request wasn't understood."


def who(ctx: BookContext) -> str:
    return next((p.display_name for p in ctx.people if p.id == ctx.user_id), "Someone")


def _bad(message: str) -> HTTPException:
    return HTTPException(422, detail={"error": message})


def _range(start: str | None, end: str | None) -> tuple[date | None, date | None]:
    """Engineering choice 10: both ends or neither (All time); inclusive."""
    if start is None and end is None:
        return None, None
    try:
        a, b = date.fromisoformat(start or ""), date.fromisoformat(end or "")
    except ValueError:
        raise _bad(RANGE) from None
    if a > b:
        raise _bad(RANGE)
    return a, b


@router.get("/transactions.csv")
def transactions_csv(start: str | None = Query(None, alias="from"), end: str | None = Query(None, alias="to"),
                     notes: str = "0", db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P24: by date, then id. Notes only with notes=1, newest first, joined by " | " (never remembered: the web's box
    is unticked on every visit). Business % in household books only."""
    a, b = _range(start, end)
    if notes not in ("0", "1"):
        raise _bad(NOT_UNDERSTOOD)
    with_notes, household = notes == "1", ctx.book.kind == "household"
    q = select(Transaction, Account.name).join(Account, Account.id == Transaction.account_id)
    if a is not None:
        q = q.where(Transaction.posted_at >= a, Transaction.posted_at <= b)
    rows = db.execute(q.order_by(Transaction.posted_at, Transaction.id)).all()
    said: dict[int, list[str]] = defaultdict(list)
    if with_notes:
        nq = (select(TransactionNote.transaction_id, TransactionNote.body)
              .join(Transaction, Transaction.id == TransactionNote.transaction_id)
              .order_by(TransactionNote.created_at.desc(), TransactionNote.id.desc()))
        if a is not None:
            nq = nq.where(Transaction.posted_at >= a, Transaction.posted_at <= b)
        for tid, body in db.execute(nq):
            said[tid].append(body)
    out = [["Date", "Account", "Description", "Name", "Category", "Amount", "Transfer"]
           + (["Business %"] if household else []) + (["Notes"] if with_notes else [])]
    for t, account in rows:
        line = [t.posted_at.isoformat(), guard(account), guard(t.raw_description), guard(t.nickname or t.merchant or ""),
                guard(label(t.category)), decimal(t.amount_cents), "yes" if t.is_transfer else ""]
        if household:
            line.append(str(t.business_pct) if t.business_pct > 0 else "")
        if with_notes:
            line.append(guard(" | ".join(said.get(t.id, []))))
        out.append(line)
    span = "all time" if a is None else f"{a.isoformat()} to {b.isoformat()}"
    begin_write(db)
    log_event(db, "info", "export", f"{who(ctx)} downloaded transactions ({span}{', with notes' if with_notes else ''})")
    db.commit()
    name = f"steward-{ctx.book.slug}-transactions-" + ("all" if a is None else f"{a.isoformat()}-{b.isoformat()}") + ".csv"
    return download(write(out), name)


@router.get("/business.csv", dependencies=[Depends(household_only)])
def business_csv(year: str | None = None, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P25: the Business page's line totals for a year (Engineering choice 9 for the three totals)."""
    if business_type(db) == "none":
        raise HTTPException(404, detail={"error": NOT_IN_THIS_BOOK})
    y = year_param(year)
    r = business_report(db, y, deps.today())
    out = [["Line", "Label", "Counts", "Rows", "Note"]]
    out += [[l.number, guard(l.label), decimal(l.counts_cents), str(l.count), guard(l.note or "")] for l in r.lines]
    out += [["", "Income", decimal(r.income_cents), "", ""], ["", "Expenses", decimal(r.expenses_cents), "", ""],
            ["", "Profit", decimal(r.profit_cents), "", ""]]
    begin_write(db)
    log_event(db, "info", "export", f"{who(ctx)} downloaded the business report ({y})")
    db.commit()
    return download(write(out), f"steward-{ctx.book.slug}-business-{y}.csv")


@dataclass(frozen=True)
class Pending:
    user_id: int
    book_id: int
    path: Path
    folder: Path
    filename: str
    expires: datetime


class Downloads:
    """P29: a made backup waits here for its one GET, by a token bound to the person and the book, for 10 minutes
    (deps.now()). On app.state; a restart forgets every token and the startup sweep removes the folders."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, Pending] = {}

    def put(self, made: book_export.Made, user_id: int, book_id: int, now: datetime) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._items[token] = Pending(user_id, book_id, made.path, made.folder, made.filename, now + book_export.TTL)
        return token

    def take(self, token: str, user_id: int, book_id: int, now: datetime) -> Pending | None:
        with self._lock:
            p = self._items.get(token)
            if p is None or p.user_id != user_id or p.book_id != book_id:
                return None
            del self._items[token]
        if now >= p.expires:
            shutil.rmtree(p.folder, ignore_errors=True)
            return None
        return p

    def sweep(self, now: datetime) -> None:
        with self._lock:
            old = [t for t, p in self._items.items() if now >= p.expires]
            gone = [self._items.pop(t) for t in old]
        for p in gone:
            shutil.rmtree(p.folder, ignore_errors=True)


def _sweep(request: Request) -> None:
    """Each request to /export, besides startup: expired links, then any stray steward-export-* folder."""
    request.app.state.export_downloads.sweep(deps.now())
    book_export.sweep(book_export.tmp_root(request.app.state.settings), time.time())


@router.post("/backup", status_code=201)
@viewer_ok
@recorded
def make_backup(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
                ctx: BookContext = Depends(open_book)):
    """P26-P30. Plain def: Argon2 and the copy run in the threadpool, before the book's session begins, so no write
    lock is held meanwhile. viewer_ok only lets open_book pass a viewer on to managers_only's 404 (spec: viewers 404).
    The body is read with json_object, never a model, so a 422 never echoes the passphrase."""
    _sweep(request)
    try:
        passphrase = book_export.check_passphrase(body.get("passphrase"), body.get("again"))
        made = book_export.make(request.app.state.books, ctx.book, passphrase, request.app.state.settings,
                                deps.today(), deps.now())
    except book_export.ExportRefused as e:
        raise HTTPException(e.status, detail={"error": e.message}) from None
    finally:
        passphrase = body = None                     # drop the references (the spec claims no more)
    log_event(db, "info", "export", f"{who(ctx)} made an encrypted backup of this book")
    record(db, ctx, "export.backup", after={"bytes": made.size})
    db.commit()
    token = request.app.state.export_downloads.put(made, ctx.user_id, ctx.book.id, deps.now())
    return {"token": token, "filename": made.filename, "bytes": made.size}


@router.get("/backup/{token}")
def download_backup(token: str, request: Request, ctx: BookContext = Depends(open_book)):
    """Streams once, to the same person, within 10 minutes; the folder goes after it's sent."""
    _sweep(request)
    p = request.app.state.export_downloads.take(token, ctx.user_id, ctx.book.id, deps.now())
    if p is None:
        raise HTTPException(404, detail={"error": book_export.EXPIRED})
    return FileResponse(p.path, media_type="application/octet-stream", filename=p.filename,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                        background=BackgroundTask(shutil.rmtree, p.folder, True))
