"""Home (phase 11 spec, API): GET /home, the verdict, the signs, For you and Since for the person asking, and POST /home/seen, a
person's own visit. Household books only, like Spending: a parent book answers 404. Neither route logs an amount, a name or a mark."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import NOT_UNDERSTOOD, bad, json_object
from steward.deps import BookContext, book_db, household_only, not_recorded, open_book, viewer_ok
from steward.services import home_since as hs
from steward.services import home as svc

router = APIRouter(prefix="/home", dependencies=[Depends(open_book), Depends(household_only)])
MAX_STAMP = 40


def stamp(value: object) -> datetime | None:
    """An ISO time with its zone, as GET /home sends it, in UTC; None for anything else."""
    if not isinstance(value, str) or not value or len(value) > MAX_STAMP:
        return None
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return at.astimezone(timezone.utc) if at.tzinfo is not None else None


@router.get("")
def home(from_: str | None = Query(None, alias="from"), db: Session = Depends(book_db),
         ctx: BookContext = Depends(open_book)):
    """GET /home[?from=]: any member, for themselves. A viewer gets no manager-only rows (P22); a refetch's ?from=
    holds the Since list still while the visit is saved (P29); one that doesn't parse is ignored."""
    return svc.home_view(db, deps.today(), deps.now(), ctx.user_id, ctx.is_manager, stamp(from_))


@router.post("/seen", status_code=204)
@viewer_ok
@not_recorded("Remembering when someone last looked at Home changes no money or item.")
def seen(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """{mark, glance} (P27, P28): mark is GET /home's own `mark`, sent back, so anything that arrived between the GET
    and this POST isn't skipped. A viewer saves their own visit too."""
    mark, glance = stamp(body.get("mark")), body.get("glance")
    if mark is None or not isinstance(glance, bool):
        raise bad(NOT_UNDERSTOOD)
    try:
        hs.save_look(db, ctx.user_id, mark, glance=glance, now=deps.now())
    except hs.LookRefused as e:
        db.rollback()
        raise bad(e.message) from None
    db.commit()
    return Response(status_code=204)
