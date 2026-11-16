"""Growth toward an oak (phase 17 spec 3.4): GET /growth, the book's stage, its five milestones and whether the person
asking has seen this stage; POST /growth/seen, that person's own mark, kept on their membership in the directory.
Household books only: a parent book answers 404. Only counts, keys and a calendar month leave; nothing here is logged."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import NOT_UNDERSTOOD, bad, json_object
from steward.db.directory_models import Membership
from steward.deps import BookContext, book_db, directory_db, household_only, not_recorded, open_book, viewer_ok
from steward.services import book_growth as svc

router = APIRouter(prefix="/growth", dependencies=[Depends(open_book), Depends(household_only)])


@router.get("")
def growth(db: Session = Depends(book_db), ddb: Session = Depends(directory_db), ctx: BookContext = Depends(open_book)):
    """Any member, the same tree; `seen` is the asker's own. A rise in the stage is written here (svc.raise_stage)."""
    seen = ddb.scalar(select(Membership.growth_seen).where(Membership.user_id == ctx.user_id,
                                                           Membership.book_id == ctx.book.id))
    ddb.commit()
    return svc.growth_view(db, deps.today(), seen)


@router.post("/seen", status_code=204)
@viewer_ok
@not_recorded("Remembering which growth stage someone has seen changes no money or item.")
def seen(body: dict = Depends(json_object), ddb: Session = Depends(directory_db), ctx: BookContext = Depends(open_book)):
    """{stage}: the stage Home just showed this person. The mark only rises."""
    stage = body.get("stage")
    if set(body) != {"stage"} or isinstance(stage, bool) or not isinstance(stage, int) or not 0 <= stage <= svc.MAX_STAGE:
        raise bad(NOT_UNDERSTOOD)
    m = ddb.get(Membership, (ctx.user_id, ctx.book.id))
    if m is not None and (m.growth_seen is None or stage > m.growth_seen):
        m.growth_seen = stage
    ddb.commit()
    return Response(status_code=204)
