"""Set-asides (phase 11c spec, API). Household books only: every route goes through open_book and household_only, so
a parent book answers 404 and a viewer gets 403 on every write. POST /estimate is arithmetic and open to viewers.
Each write logs one event_log line and commits once, in the request's IMMEDIATE session (begin_write first, as every
write does). GETs write nothing."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.db.engine import begin_write
from steward.db.models import CATEGORIES, SetAside, Transaction
from steward.deps import BookContext, book_db, household_only, open_book, viewer_ok
from steward.events import log_event
from steward.services import setasides as svc
from steward.services.undo import capturing

router = APIRouter(prefix="/setasides", dependencies=[Depends(open_book), Depends(household_only)])


def _name(ctx: BookContext) -> str:
    return next((p.display_name for p in ctx.people if p.id == ctx.user_id), None) or "Someone"


def _get(db: Session, sa_id) -> SetAside:
    sa = db.get(SetAside, sa_id) if isinstance(sa_id, int) and not isinstance(sa_id, bool) else None
    if sa is None:
        raise bad("No such set-aside.", 404)
    return sa


def _active(db: Session, sa_id) -> SetAside:
    sa = _get(db, sa_id)
    if sa.archived_at is not None:
        raise bad("That set-aside was stopped.", 409)
    return sa


def _date(value) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise bad(svc.NOT_UNDERSTOOD) from None


@router.get("")
def get_list(db: Session = Depends(book_db)):
    return svc.list_view(db, deps.today())


@router.get("/{sa_id}")
def get_one(sa_id: int, db: Session = Depends(book_db)):
    return svc.detail_view(db, deps.today(), _get(db, sa_id))


@router.post("", status_code=201)
def add(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    try:
        sa = svc.add(db, svc.parse_body(body, t), user_id=ctx.user_id, who=_name(ctx), today=t, at=deps.now())
    except svc.SetAsideError as e:
        raise bad(str(e)) from None
    db.commit()
    return svc.detail_view(db, t, sa)


@router.post("/many", status_code=201)
def add_many(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P26: the suggestions a person ticked, made in one write with one Undo. Any item that can't be saved refuses
    the whole request and nothing is made."""
    begin_write(db)
    t = deps.today()
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise bad(svc.NOT_UNDERSTOOD)
    if len(items) > svc.MAX_MANY:
        raise bad(svc.TOO_MANY)
    try:
        fs = [svc.parse_body(i, t) for i in items]
        with capturing(db, ctx.user_id, "set_asides", deps.now()) as cap:
            made = svc.add_many(db, fs, user_id=ctx.user_id, who=_name(ctx), today=t, at=deps.now())
    except svc.SetAsideError as e:
        db.rollback()
        raise bad(str(e)) from None
    db.commit()
    return {"ids": [s.id for s in made], "monthly_cents": sum(svc.monthly_cents(s) for s in made), "undo": cap.token}


@router.put("/{sa_id}")
def edit(sa_id: int, body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    sa = _active(db, sa_id)
    try:
        svc.edit(db, sa, svc.parse_body(body, t, current=sa), user_id=ctx.user_id, who=_name(ctx), today=t, at=deps.now())
    except svc.SetAsideError as e:
        raise bad(str(e)) from None
    db.commit()
    return svc.detail_view(db, t, sa)


@router.delete("/{sa_id}", status_code=204)
def stop(sa_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    svc.archive(db, _active(db, sa_id), user_id=ctx.user_id, who=_name(ctx), at=deps.now())
    db.commit()
    return Response(status_code=204)


@router.post("/{sa_id}/replace", status_code=201)
def replace(sa_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    try:
        new = svc.replace(db, _active(db, sa_id), user_id=ctx.user_id, who=_name(ctx), today=t, at=deps.now())
    except svc.SetAsideError as e:
        raise bad(str(e), 409) from None
    db.commit()
    return svc.detail_view(db, t, new)


@router.post("/{sa_id}/skip")
def skip(sa_id: int, body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    sa = _active(db, sa_id)
    due_on = _date(body.get("due_on"))
    try:
        svc.skip_due(db, sa, due_on, by=ctx.user_id)
    except svc.MatchError as e:
        raise bad(str(e)) from None
    log_event(db, "info", "setaside", f"{_name(ctx)} said {sa.name}'s {svc.day_text(due_on)} installment was not due")
    db.commit()
    return svc.detail_view(db, t, sa)


@router.post("/estimate")
@viewer_ok
def estimate(body: dict = Depends(json_object), db: Session = Depends(book_db)):
    """Read-only arithmetic (spec, API): any draft is worked out by the service's own rules and nothing is written,
    so a viewer may ask. The web never recomputes; it shows this. With set_aside_id the draft is an edit of that
    set-aside (404 if it isn't in this book)."""
    sa = None
    if body.get("set_aside_id") is not None:
        sa = _get(db, body["set_aside_id"])
    try:
        return svc.preview(body, deps.today(), db, sa)
    except svc.SetAsideError as e:
        raise bad(str(e)) from None


def _pair(body: dict) -> tuple[str, str]:
    """A suggestion's (payee key, category), bounded as parse_body bounds them."""
    key, category = body.get("payee_key"), body.get("category")
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise bad(svc.NOT_UNDERSTOOD)
    if not isinstance(category, str) or category not in CATEGORIES:
        raise bad(svc.BAD_CATEGORY)
    return key, category


@router.post("/suggestions/dismiss")
def dismiss(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    key, category = _pair(body)
    svc.dismiss(db, key, category, by=ctx.user_id)
    log_event(db, "info", "setaside", f"{_name(ctx)} dismissed the {svc.payee_name_of(db, key)} suggestion")
    db.commit()
    return svc.list_view(db, t)


@router.post("/suggestions/restore")
def restore(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    key, category = _pair(body)
    if not svc.restore(db, key, category):
        raise bad("That suggestion wasn't dismissed.", 404)
    log_event(db, "info", "setaside", f"{_name(ctx)} brought back the {svc.payee_name_of(db, key)} suggestion")
    db.commit()
    return svc.list_view(db, t)


@router.post("/match")
def match(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    t = deps.today()
    tid = body.get("transaction_id")
    txn = db.get(Transaction, tid) if isinstance(tid, int) and not isinstance(tid, bool) else None
    if txn is None:
        raise bad("No such transaction.", 404)
    sa = _active(db, body.get("set_aside_id"))
    try:
        m = svc.match_by_hand(db, txn, sa, t, by=ctx.user_id)
    except svc.MatchError as e:
        raise bad(str(e)) from None
    log_event(db, "info", "setaside", f"{_name(ctx)} matched a {svc.dollars_text(-txn.amount_cents)} payment to {sa.name} ({svc.day_text(m.due_on)})")
    db.commit()
    return svc.detail_view(db, t, sa)


@router.delete("/match/{transaction_id}", status_code=204)
def unmatch(transaction_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    try:
        m = svc.refuse(db, transaction_id, by=ctx.user_id)
    except svc.StoppedError as e:
        raise bad(str(e), 409) from None
    except svc.MatchError as e:
        raise bad(str(e)) from None
    sa = db.get(SetAside, m.set_aside_id)
    txn = db.get(Transaction, transaction_id)
    log_event(db, "info", "setaside", f"{_name(ctx)} unmatched a {svc.dollars_text(-txn.amount_cents)} payment from {sa.name}")
    db.commit()
    return Response(status_code=204)
