"""Is this one of the parent's? (spec 3.3; decisions 7 and 9). Managers only: a viewer gets 404 (ruling 29)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.api.body import bad, json_object
from steward.api.inventory import owners_of
from steward.books.history import names_for
from steward.books.owners import default_owner
from steward.db.models import Suggestion
from steward.deps import BookContext, book_db, managers_only, open_book, parent_only, recorded, today
from steward.inventory.suggestions import (
    SuggestionRefused, dismiss, dismissed_rows, get_open, link, open_rows, refresh, suggestion_out, undo,
)
from steward.inventory.views import load

router = APIRouter(prefix="/inventory/suggestions",
                   dependencies=[Depends(open_book), Depends(parent_only), Depends(managers_only)])


def _refused(e: SuggestionRefused):
    return bad(str(e), e.status)


@router.get("")
def list_open(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    L = load(db, owners_of(ctx))
    owner = default_owner(ctx.book.owner_names)
    return {"suggestions": [suggestion_out(db, s, L, owner) for s in open_rows(db)]}


@router.get("/dismissed")
def list_dismissed(request: Request, db: Session = Depends(book_db)):
    ids = db.scalars(select(Suggestion.answered_by).where(Suggestion.status == "dismissed")).all()
    return {"dismissed": dismissed_rows(db, names_for(request.app.state.books.directory, ids))}


@router.post("/{sid}/dismiss")
@recorded
def answer_not_hers(sid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    try:
        answer = dismiss(db, ctx, get_open(db, sid))
    except SuggestionRefused as e:
        raise _refused(e) from None
    refresh(db, today())   # the payer's other open suggestions go now, not at the next refresh
    db.commit()
    return {"answer": answer}


@router.post("/{sid}/link")
@recorded
def answer_already_listed(sid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
                          ctx: BookContext = Depends(open_book)):
    try:
        answer = link(db, ctx, get_open(db, sid), body.get("item_id"), body.get("confirm"))
    except SuggestionRefused as e:
        raise _refused(e) from None
    db.commit()
    return {"answer": answer}


@router.post("/{sid}/undo")
@recorded
def undo_answer(sid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    s = db.get(Suggestion, sid)
    if s is None:
        raise bad("No such suggestion.", 404)
    try:
        undo(db, ctx, s)
    except SuggestionRefused as e:
        raise _refused(e) from None
    db.commit()
    return {"ok": True}
