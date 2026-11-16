from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import EventLog
from steward.deps import BookContext, book_db, not_recorded, now, open_book
from steward.events import event_visible, resolve_event, visible_to
from steward.services.simplefin.sync import dismiss_sync_warning
from steward.services.undo import capturing

router = APIRouter(prefix="/events", dependencies=[Depends(open_book)])


def _out(e: EventLog) -> dict:
    return {
        "id": e.id,
        "at": e.at.isoformat(),
        "level": e.level,
        "kind": e.kind,
        "message": e.message,
        "actionable": e.actionable,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
    }


@router.get("")
def list_events(
    limit: int = Query(100, ge=1, le=500),
    unresolved: bool = False,
    db: Session = Depends(book_db),
    ctx: BookContext = Depends(open_book),
):
    """The Log screen. A viewer never sees a managers-only kind (an import notice can name uploaded files)."""
    q = visible_to(select(EventLog), ctx.is_manager).order_by(EventLog.at.desc(), EventLog.id.desc()).limit(limit)
    if unresolved:
        q = q.where(EventLog.resolved_at.is_(None))
    return {"events": [_out(e) for e in db.scalars(q)]}


@router.post("/{event_id}/resolve")
@not_recorded("Dismissing a notice changes no money or item.")
def resolve(event_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Dismiss (Home spec P20): resolves the event and returns an undo token; Undo reopens it. A sync warning is also
    remembered on its connection, as before (engineering choice 11: that part isn't undone)."""
    e = db.get(EventLog, event_id)
    if e is None or not event_visible(e, ctx.is_manager):
        raise HTTPException(404, detail={"error": "No such event."})
    at = now()
    with capturing(db, ctx.user_id, "dismiss", at) as cap:
        if e.kind == "sync":
            dismiss_sync_warning(db, e, at)  # stays dismissed until that connection's error changes or clears
        else:
            resolve_event(db, event_id, at)
    db.commit()
    return {"undo": cap.token}
