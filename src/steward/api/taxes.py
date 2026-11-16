"""Taxes (spec 7): quarterly estimates, Solo 401(k) or SEP, Roth or traditional. Household books only: every route goes
through open_book and household_only, so a parent book answers 404 and a viewer gets 403 on writes (the email switch,
a person's own, is viewer_ok). Steward never pays or files anything."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.db.models import Transaction
from steward.deps import BookContext, book_db, household_only, open_book, viewer_ok
from steward.engine.inputs import InputError
from steward.engine.tax.rules import RulesError
from steward.services.plan import engine_text
from steward.taxes import store
from steward.taxes.household import NotReady
from steward.taxes.plans import plans, plans_out
from steward.taxes.quarterly import notice, notice_line, quarterly, quarterly_out
from steward.taxes.roth import roth_out, roth_view

router = APIRouter(prefix="/taxes", dependencies=[Depends(open_book), Depends(household_only)])
RETURN_YEARS = "Enter a return for one of the last two years."
WITHHOLDING_YEARS = "Enter withholding for this year or last year."
COUNTS = "Choose whether it counts: true or false."
NOT_READY = (NotReady, InputError, RulesError)


def _unavailable(db: Session, e: Exception) -> dict:
    return {"available": False, "reason": engine_text(db, e)}


def _quarterly(db: Session, ctx: BookContext) -> dict:
    t = deps.today()
    try:
        q = quarterly(db, t)
    except NOT_READY as e:
        return _unavailable(db, e)
    return quarterly_out(q, t, store.email_on(db, ctx.user_id))


@router.get("/quarterly")
def get_quarterly(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return _quarterly(db, ctx)


@router.get("/notice")
def get_notice(db: Session = Depends(book_db)):
    t = deps.today()
    try:
        q = quarterly(db, t)
    except NOT_READY:
        return {"notice": None}
    n = notice(q, t)
    return {"notice": None if n is None else {"due": n.due.isoformat(), "line": notice_line(n, q.state),
                                              "federal_cents": n.federal_cents, "state_cents": n.state_cents}}


@router.put("/return/{year}")
def put_return(year: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
               ctx: BookContext = Depends(open_book)):
    this = deps.today().year
    if year not in (this - 2, this - 1):
        raise bad(RETURN_YEARS)
    try:
        store.write_return(db, year, body, ctx.user_id, deps.now())
    except store.StoreError as e:
        db.rollback()
        raise bad(str(e)) from None
    db.commit()
    return _quarterly(db, ctx)


@router.put("/withholding/{year}")
def put_withholding(year: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
                    ctx: BookContext = Depends(open_book)):
    t = deps.today()
    if year not in (t.year - 1, t.year):
        raise bad(WITHHOLDING_YEARS)
    try:
        store.write_withholding(db, year, body, today=t, user_id=ctx.user_id, at=deps.now())
    except store.StoreError as e:
        db.rollback()
        raise bad(str(e)) from None
    db.commit()
    return _quarterly(db, ctx)


@router.put("/payments/{tid}")
def put_payment(tid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
                ctx: BookContext = Depends(open_book)):
    if db.get(Transaction, tid) is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    if not isinstance(body.get("counts"), bool):
        raise bad(COUNTS)
    store.mark_payment(db, tid, body["counts"], ctx.user_id, deps.now())
    db.commit()
    return _quarterly(db, ctx)


@router.get("/plans")
def get_plans(db: Session = Depends(book_db)):
    t = deps.today()
    try:
        p = plans(db, t)
    except NOT_READY as e:
        return _unavailable(db, e)
    return plans_out(p, t)


@router.get("/roth")
def get_roth(db: Session = Depends(book_db)):
    t = deps.today()
    try:
        v = roth_view(db, t)
    except NOT_READY as e:
        return _unavailable(db, e)
    db.rollback()                       # build_inputs read only; end the transaction as GET /plan does
    return roth_out(v)


SWITCH = "Choose on or off."


@router.get("/email")
def get_email(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return {"on": store.email_on(db, ctx.user_id)}


@router.put("/email")
@viewer_ok
def put_email(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    if not isinstance(body.get("on"), bool) or set(body) != {"on"}:
        raise bad(SWITCH)
    store.set_email(db, ctx.user_id, body["on"], deps.now())
    db.commit()
    return {"on": store.email_on(db, ctx.user_id)}
