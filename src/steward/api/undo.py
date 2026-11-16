"""Undo a Review action (sorting redesign spec, Undo): POST /undo/{token}, for the person who acted, within 15
minutes, all or nothing."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from steward.api.transactions import note_counts, set_asides_of, transaction_row
from steward.db.models import Account
from steward import deps
from steward.deps import BookContext, book_db, open_book, recorded
from steward.inventory.changes import about, record
from steward.services.undo import UndoRefused, undo

router = APIRouter(dependencies=[Depends(open_book)])


def now():
    """The clock, read through steward.deps so a pinned test clock reaches the journal too."""
    return deps.now()


@router.post("/undo/{token}")
@recorded
def undo_action(token: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    try:
        done = undo(db, token, ctx.user_id, now())
    except UndoRefused as e:
        db.rollback()
        raise HTTPException(e.status, detail={"error": e.message}) from None
    t = done.target
    if t is not None:
        record(db, ctx, "txn.undo", target_id=t.id, after={"count": done.count, "about": about(t)})
    elif done.action == "sort_many":          # a bulk sort has no one row to name
        record(db, ctx, "txn.undo", after={"count": done.count})
    db.commit()
    row = None
    if t is not None:
        row = transaction_row(t, db.get(Account, t.account_id).name, set_asides_of(db, [t.id]).get(t.id),
                              note_counts(db, [t.id]).get(t.id, 0))
    return {"undone": done.count, "transaction": row}
