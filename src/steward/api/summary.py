from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import EventLog
from steward.deps import BookContext, book_db, open_book, today
from steward.events import visible_to
from steward.services import networth

router = APIRouter(prefix="/summary", dependencies=[Depends(open_book)])


@router.get("")
def summary(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    t = today()
    ms = networth.month_start(t)
    nw = networth.net_worth_on(db, t)
    before = ms - timedelta(days=1)
    has_prev = bool(networth._latest_per_account(db, before))
    prev = networth.net_worth_on(db, before)
    year_start = date(t.year, 1, 1)
    dec31 = year_start - timedelta(days=1)
    has_last_year = bool(networth._latest_per_account(db, dec31))
    attention = db.scalars(visible_to(select(EventLog), ctx.is_manager)
                           .where(EventLog.actionable.is_(True), EventLog.resolved_at.is_(None))
                           .order_by(EventLog.at.desc()))
    return {"net_worth_cents": nw, "month_start": ms.isoformat(), "change_month_cents": nw - prev if has_prev else None,
            "year_start": year_start.isoformat(),
            "change_year_cents": nw - networth.net_worth_on(db, dec31) if has_last_year else None,
            "as_of": t.isoformat(), "accounts_by_type": networth.by_type_on(db, t), "split": networth.split_on(db, t),
            "needs_attention": [{"id": e.id, "message": e.message, "kind": e.kind} for e in attention]}


@router.get("/history")
def history(days: int = Query(90, ge=1, le=3660), db: Session = Depends(book_db)):
    t = today()
    pts = networth.history_with_investable(db, t - timedelta(days=days - 1), t)
    return {"points": [{"date": d.isoformat(), "net_worth_cents": c, "investable_cents": i} for d, c, i in pts]}
