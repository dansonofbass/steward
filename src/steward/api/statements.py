"""PDF statements under Import (spec P1-P3, P7, API). The PDF is the raw request body (application/pdf), never
multipart: Starlette's multipart parser spools a part over 1 MB to a temporary file and the NAS has no tmpfs (P1). Its
memory is reserved before the body is read (P7, Engineering choice 11); BodyLimit guards the path at 15 MB + 64 KB.
Managers only: a viewer gets 404 on every route, as the rest of Import (viewer_ok lets a viewer's write past
open_book's 403 so managers_only's 404 answers it)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, undefer

from steward.api.body import json_object
from steward.db.engine import begin_write
from steward.db.models import Account, ImportBatch, StatementLayout, StatementStage
from steward.books.people import names_of
from steward import clock
from steward.deps import BookContext, book_db, managers_only, not_recorded, now, open_book, real_book_only, today, viewer_ok
from steward.inventory.files import clean_name
from steward.services import import_staging
from steward.services.statements import layouts, stage
from steward.services.statements import scan as scan_read
from steward.services.statements.copy import NO_STATEMENT, NOT_A_PDF_TYPE, NOT_NOW, SAME_FILE, TOO_MANY
from steward.services.statements.reader import Busy, StatementReader
from steward.services.undo import TTL, capturing

router = APIRouter(prefix="/import", dependencies=[Depends(open_book), Depends(real_book_only), Depends(managers_only)])
MAX_PDF = 15 * 1024 * 1024
TOO_BIG = "Bigger than 15 MB. Download it again or split it."


def reader_of(request: Request) -> StatementReader:
    return request.app.state.statements


def people_of(ctx: BookContext) -> dict[int, str]:
    return names_of(ctx.people)


def _refuse(status: int, message: str) -> HTTPException:
    return HTTPException(status, detail={"error": message})


@dataclass
class Upload:
    data: bytearray
    rid: int | None


async def pdf_body(request: Request, ctx: BookContext = Depends(open_book)) -> Upload:
    """P1, P7: application/pdf only; a declared length over 15 MB refused before reading; room reserved for the
    worst case (the declared length, or 15 MB when chunked, with a bytearray's growth) before the first byte."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
        raise _refuse(415, NOT_A_PDF_TYPE)
    declared = request.headers.get("content-length", "").strip()
    size = int(declared) if declared.isascii() and declared.isdigit() else MAX_PDF + 1
    if size > MAX_PDF and declared:
        raise _refuse(413, TOO_BIG)
    try:
        rid = reader_of(request).reserve(ctx.user_id, size + (size >> 3) + 64)
    except Busy:
        raise _refuse(503, reader_of(request).busy_line()) from None
    buf = bytearray()
    try:
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > MAX_PDF:
                raise _refuse(413, TOO_BIG)
    except BaseException:
        reader_of(request).release(rid)
        raise
    return Upload(buf, rid)


def _csv_files(request: Request, ctx: BookContext, batch: str | None) -> int:
    if not batch:
        return 0
    try:
        b = request.app.state.import_staging.find(ctx.user_id, ctx.book.id, batch, now())
    except import_staging.StagingRefused:
        return 0
    return len(b.uploads)


def imported_before(db: Session, stages: list[StatementStage]) -> dict[int, str]:
    """P37's tag: the same bytes imported before, or the same account and period (Engineering choice 21)."""
    def day(at) -> str:
        return at.astimezone(clock.household_tz()).date().isoformat()
    shas = {s.content_sha256 for s in stages}
    by_sha = dict(db.execute(select(ImportBatch.content_sha256, func.max(ImportBatch.imported_at))
                             .where(ImportBatch.content_sha256.in_(shas), ImportBatch.rolled_back_at.is_(None))
                             .group_by(ImportBatch.content_sha256)).all()) if shas else {}
    accounts = {s.account_id for s in stages if s.account_id is not None}
    by_period = {}
    if accounts:
        for aid, start, end, at in db.execute(select(ImportBatch.account_id, ImportBatch.period_start, ImportBatch.period_end,
                                                     ImportBatch.imported_at)
                                              .where(ImportBatch.account_id.in_(accounts), ImportBatch.period_end.is_not(None),
                                                     ImportBatch.rolled_back_at.is_(None))):
            key = (aid, start.isoformat(), end.isoformat())
            by_period[key] = max(by_period.get(key, at), at)
    out = {}
    for s in stages:
        f = stage.facts_of(s) if s.statement else {}
        period = f.get("period")
        at = by_sha.get(s.content_sha256) or (by_period.get((s.account_id, period[0], period[1])) if period else None)
        if at is not None:
            out[s.id] = day(at)
    return out


@router.post("/statements", status_code=201)
@viewer_ok
@not_recorded("Staging reads the file and saves nothing to the books.")
def upload(request: Request, batch: str | None = None, up: Upload = Depends(pdf_body), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    """Plain def, so the hashing and the writes run in the threadpool."""
    reader = reader_of(request)
    try:
        name = clean_name(unquote(request.headers.get("x-filename", ""))) or "statement.pdf"
        sha = hashlib.sha256(up.data).hexdigest()
        t = now()
        begin_write(db)
        stage.sweep(db, t)
        old = stage.same_file(db, sha)
        if old is not None and old.state not in ("error", "cleared"):
            raise _refuse(409, SAME_FILE)
        if old is not None and old.state == "error" and old.error in ("restarted", "page_failed") and stage.is_scanning(old):
            old.state, old.error, old.tries = "queued", None, 0         # P32: the same file finishes the scan it started
            stage.touch(old, t)
            db.commit()
            reader.hold(ctx.book.id, old.id, ctx.user_id, up.data, up.rid)
            up.rid = None
            return {"statement": stage.line_out(old, people_of(ctx), ctx.user_id, None)}
        if old is not None:
            db.delete(old)
            db.flush()
        if stage.live_count(db) + _csv_files(request, ctx, batch) >= stage.MAX_FILES:
            raise _refuse(422, TOO_MANY)
        s = stage.add(db, user_id=ctx.user_id, filename=name, size=len(up.data), sha=sha, now=t)
        db.commit()
        reader.hold(ctx.book.id, s.id, ctx.user_id, up.data, up.rid)
        up.rid = None
        return {"statement": stage.line_out(s, people_of(ctx), ctx.user_id, None)}
    finally:
        if up.rid is not None:
            reader.release(up.rid)


@router.get("/statements")
def statements(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Every staged statement of the book (book-wide among managers, P3) and the gateway's state; runs the sweep (P5)
    when it has something to do, so an open with nothing due is a plain read (phase 18)."""
    t = now()
    if stage.sweep_due(db, t):
        begin_write(db)
        stage.sweep(db, t)
        db.commit()
    rows = list(db.scalars(select(StatementStage).options(undefer(StatementStage.rows), undefer(StatementStage.statement),
                                                      undefer(StatementStage.holdings))
                           .order_by(StatementStage.id)))
    before = imported_before(db, rows)
    people = people_of(ctx)
    scanning = set(db.scalars(select(StatementStage.id).where(StatementStage.proposal.startswith(stage.SCAN_MARK))))
    # A waiting file whose pages are read (or a scan) waits on a model, which the line names (INS-12).
    read = set(db.scalars(select(StatementStage.id).where(StatementStage.state == "waiting",
                                                          StatementStage.lines.is_not(None))))
    reader = reader_of(request)
    lines = []
    for s in rows:
        line = stage.line_out(s, people, ctx.user_id, before.get(s.id), s.id in scanning)
        line["needs_model"] = (s.state == "waiting" and (s.id in read or s.id in scanning)
                               and reader.needs_model(s.id in scanning))
        lines.append(line)
    return {"statements": lines, "gateway": reader.remote_state(), "reading": reader.place}


def live(db: Session, sid: int) -> StatementStage:
    s = db.get(StatementStage, sid)
    if s is None:
        raise _refuse(404, NO_STATEMENT)
    return s


@router.get("/statements/{sid}")
def statement(sid: int, db: Session = Depends(book_db)):
    return stage.detail_out(live(db, sid))


LAYOUT_NOT_RECORDED = "A layout is how files are read, not the book's money."
ROWS_NOT_RECORDED = "Checking a staged statement's rows saves nothing to the books."
STAGE_NOT_RECORDED = "A staged statement isn't in the books yet."
NO_LAYOUT = "That layout isn't here anymore."
NO_ACCOUNT = "No such account."
NOT_UNDERSTOOD = "That request wasn't understood."
RETRYABLE = ("layout_failed", "page_failed", "read_failed")


def _bad(message: str = NOT_UNDERSTOOD, status: int = 422) -> HTTPException:
    return HTTPException(status, detail={"error": message})


def _line(db: Session, s: StatementStage, ctx: BookContext) -> dict:
    return {"statement": stage.line_out(s, people_of(ctx), ctx.user_id, imported_before(db, [s]).get(s.id))}


def _reread_for(db: Session, s: StatementStage, aid: int) -> None:
    """Engineering choice 6: a scan's account says bank or owed. A different sense reads the rows again from the pages
    kept (when none were edited), and either way the gap is checked again."""
    kind = scan_read.kind_for(db.get(Account, aid).type)
    facts = stage.facts_of(s)
    if facts.get("kind") != kind:
        across = (kind in stage.HOLDING_KINDS) != (facts.get("kind") in stage.HOLDING_KINDS) or "loan" in (kind, facts.get("kind"))
        untouched = all(r["state"] == "read" for r in stage.rows_of(s)) and \
            all(h["state"] == "read" for h in stage.holdings_of(s))
        if untouched or across:
            reading, again = scan_read.assemble(json.loads(s.proposal)["pages"], kind, today())
            if not reading.error:
                again["model"] = facts.get("model")
                stage.put_assembled(s, reading, again)
        else:
            s.statement = json.dumps({**facts, "kind": kind})
    s.gap_cents = stage.regap(s)
    s.state = "ready" if s.gap_cents == 0 else "off"
    if s.state == "ready":
        s.anyway = False


@router.patch("/statements/{sid}")
@viewer_ok
@not_recorded(STAGE_NOT_RECORDED)
def change(sid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    """The account (P36: the person's choice ends the suggestion) and Import anyway (P35: only while off)."""
    if not body or set(body) - {"account_id", "anyway"}:
        raise _bad()
    begin_write(db)
    s = live(db, sid)
    if "account_id" in body:
        aid = body["account_id"]
        if aid is not None and (not isinstance(aid, int) or isinstance(aid, bool)):
            raise _bad()
        if aid is not None and db.scalar(select(Account.id).where(Account.id == aid, Account.is_active.is_(True))) is None:
            raise _bad(NO_ACCOUNT, 404)
        s.account_id, s.suggested_by = aid, None
        if aid is not None and stage.is_scanning(s) and s.state in ("ready", "off"):
            _reread_for(db, s, aid)
        elif aid is None and stage.is_scanning(s) and s.state in ("ready", "off"):
            s.gap_cents, s.state, s.anyway = None, "ready", False   # back to no account: nothing to check by
    if "anyway" in body:
        if not isinstance(body["anyway"], bool):
            raise _bad()
        if body["anyway"] and s.state != "off":             # off with no gap (a balance not read) is still off
            raise _bad(NOT_NOW, 409)
        s.anyway = body["anyway"]
    stage.touch(s, now())
    db.commit()
    return _line(db, s, ctx)


@router.post("/statements/{sid}/layout")
@viewer_ok
@not_recorded(LAYOUT_NOT_RECORDED)
def layout_answer(sid: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
                  ctx: BookContext = Depends(open_book)):
    """P23: Looks right remembers the layout at once (so the rest of the batch reads on the NAS alone); Not right opens
    row review and remembers nothing."""
    if set(body) != {"answer"} or body["answer"] not in ("right", "wrong"):
        raise _bad()
    begin_write(db)
    s = live(db, sid)
    if s.state not in ("layout", "holdings") or s.proposal is None or s.lines is None:
        raise _bad(NOT_NOW, 409)
    t = now()
    siblings = list(db.scalars(select(StatementStage).where(StatementStage.content_sha256 == s.content_sha256,
                                                            StatementStage.state.in_(("layout", "holdings")))))
    if body["answer"] == "wrong":
        loan = stage.facts_of(s).get("kind") == "loan"
        for x in siblings:
            x.state, x.error = ("error", "not_statement") if loan else ("off", None)
            stage.touch(x, t)
        db.commit()
        return _line(db, s, ctx)
    rules, facts = json.loads(s.proposal), stage.facts_of(s)
    a = layouts.anchors(rules, json.loads(s.lines))
    row = None
    if a is not None:                                   # fewer than 3 anchors: read this once, remember nothing (P24)
        _purge_forgotten(db, t)
        key = layouts.key_of(a)
        row = db.scalar(select(StatementLayout).where(StatementLayout.key == key))
        if row is None:
            row = StatementLayout(key=key, created_at=t, uses=0)
            db.add(row)
        row.label, row.kind = (facts.get("institution") or rules["institution"])[:60], rules["kind"]
        row.anchors, row.rules, row.account_id = json.dumps(a), json.dumps(rules), s.account_id
        row.model, row.confirmed_by, row.forgotten_at = (facts.get("model") or "unknown")[:60], ctx.user_id, None
        db.flush()
    for x in siblings:
        x.state, x.layout_id = "ready", row.id if row is not None else None
        stage.touch(x, t)
    db.commit()
    reader_of(request).wake()
    return _line(db, s, ctx)


@router.post("/statements/{sid}/rows")
@viewer_ok
@not_recorded(ROWS_NOT_RECORDED)
def review(sid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    """P34: edit, add, remove and put back; the server recomputes the gap after each request. done moves an off
    statement to ready when it adds up (Engineering choice 9). Never undo_entry."""
    if set(body) - {"ops", "done"} or ("done" in body and not isinstance(body["done"], bool)):
        raise _bad()
    begin_write(db)
    s = live(db, sid)
    if s.state != "off" or stage.facts_of(s).get("kind") not in ("bank", "card"):
        raise _bad(NOT_NOW, 409)
    try:
        stage.apply_ops(s, body.get("ops", []), s.pages)
    except stage.OpsRefused:
        raise _bad() from None
    s.gap_cents = stage.regap(s)
    if body.get("done") and s.gap_cents == 0:
        s.state, s.anyway = "ready", False
    stage.touch(s, now())
    db.commit()
    d = stage.detail_out(s)
    return {"state": s.state, "gap_cents": s.gap_cents, "sections": d["sections"], "rows": d["rows"]}


@router.post("/statements/{sid}/holdings")
@viewer_ok
@not_recorded(ROWS_NOT_RECORDED)
def review_holdings(sid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
                    ctx: BookContext = Depends(open_book)):
    """Holdings review: edit, add, remove and put back, with the gap to the total recomputed (within $1 adds up)."""
    if set(body) - {"ops", "done"} or ("done" in body and not isinstance(body["done"], bool)):
        raise _bad()
    begin_write(db)
    s = live(db, sid)
    if s.state != "off" or stage.facts_of(s).get("kind") not in stage.HOLDING_KINDS:
        raise _bad(NOT_NOW, 409)
    try:
        stage.apply_holding_ops(s, body.get("ops", []))
    except stage.OpsRefused:
        raise _bad() from None
    s.gap_cents = stage.regap(s)
    if body.get("done") and s.gap_cents == 0:
        s.state, s.anyway = "ready", False
    stage.touch(s, now())
    db.commit()
    return {"state": s.state, "gap_cents": s.gap_cents, "holdings": stage.detail_out(s)["holdings"]}


@router.post("/statements/{sid}/retry")
@viewer_ok
@not_recorded(STAGE_NOT_RECORDED)
def retry(sid: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P33's Try again: back in the queue, with its lines (a file whose bytes are gone is added again instead)."""
    begin_write(db)
    s = live(db, sid)
    if s.state != "error" or s.error not in RETRYABLE or (s.error == "layout_failed" and s.lines is None):
        raise _bad(NOT_NOW, 409)
    if s.error in ("page_failed", "read_failed") and not reader_of(request).has(ctx.book.id, sid):
        raise _bad(NOT_NOW, 409)
    s.state, s.error, s.tries = "queued", None, 0
    stage.touch(s, now())
    db.commit()
    reader_of(request).wake()
    return _line(db, s, ctx)


@router.delete("/statements/{sid}", status_code=204)
@viewer_ok
@not_recorded(STAGE_NOT_RECORDED)
def remove(sid: int, request: Request, final: int = 0, db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    """Remove collapses the line ("Removed {file} · Undo"); ?final=1 when the toast goes; else the sweep after 10
    minutes. Never undo_entry."""
    begin_write(db)
    s = live(db, sid)
    if final:
        db.delete(s)
        reader_of(request).drop(ctx.book.id, sid)
    else:
        s.removed_at = now()
    db.commit()


@router.post("/statements/{sid}/restore")
@viewer_ok
@not_recorded(STAGE_NOT_RECORDED)
def restore(sid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    s = live(db, sid)
    s.removed_at = None
    stage.touch(s, now())
    db.commit()
    return _line(db, s, ctx)


def _purge_forgotten(db: Session, t: datetime) -> None:
    """Engineering choice 8: a forgotten layout goes for good once its 15-minute Undo has passed (at a layout write)."""
    db.execute(delete(StatementLayout).where(StatementLayout.forgotten_at.is_not(None),
                                             StatementLayout.forgotten_at <= t - TTL))


@router.delete("/statement-layouts/{lid}")
@viewer_ok
@not_recorded(LAYOUT_NOT_RECORDED)
def forget(lid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P23's Forget, with "Forgot {label} · Undo" through the journal."""
    begin_write(db)
    row = db.get(StatementLayout, lid)
    if row is None or row.forgotten_at is not None:
        raise _bad(NO_LAYOUT, 404)
    t = now()
    _purge_forgotten(db, t)
    with capturing(db, ctx.user_id, "forget", t) as cap:
        row.forgotten_at = t
    db.commit()
    return {"undo": cap.token}
