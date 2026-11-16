"""Notes that spread and names (polish round, item 5; API, PR 2): the form's reach and rule, and its Save: a note and a
name on the row, the rows like it and future ones, in one action with one Undo. Household books only (a parent book
answers 404, a viewer's PUT 403 through open_book). The change record keeps counts and ids, never the note or the
name."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.db.models import Transaction
from steward.deps import BookContext, book_db, household_only, open_book
from steward.inventory.changes import record
from steward.services import labels
from steward.services.undo import capturing

router = APIRouter(prefix="/transactions/{tid}/label", dependencies=[Depends(open_book), Depends(household_only)])


def _txn(db: Session, tid: int) -> Transaction:
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    return t


@router.get("")
def get_label(tid: int, db: Session = Depends(book_db)):
    return labels.label_view(db, _txn(db, tid))


@router.put("")
def put_label(tid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
              ctx: BookContext = Depends(open_book)):
    t = _txn(db, tid)
    try:
        note, nickname, also, future = labels.parse_label(body)
    except labels.LabelError as e:
        raise bad(str(e)) from None
    author = next((p.display_name for p in ctx.people if p.id == ctx.user_id), None) or "Someone"
    at = deps.now()
    try:
        with capturing(db, ctx.user_id, "label", at) as cap:
            out = labels.save_label(db, t, cap, note=note, nickname=nickname, also=also, future=future,
                                    user_id=ctx.user_id, author=author, now=at)
    except labels.LabelError as e:
        db.rollback()
        raise bad(str(e)) from None
    record(db, ctx, "txn.label", target_id=t.id, after={"rows": out["rows"], "notes": out["notes_added"], "named": out["named"]})
    if out["rule_id"] is not None:
        record(db, ctx, "rule.label", after={"rule_id": out["rule_id"]})
    db.commit()
    return {**out, "undo": cap.token}
