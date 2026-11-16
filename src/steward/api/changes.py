"""Settings → Change record (spec 5, design pass decision 8): everyone in the book can read it; nobody can change it."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from steward.api.body import NOT_UNDERSTOOD, bad
from steward.deps import BookContext, book_db, open_book, parent_only, today
from steward.inventory.changes import KIND_FILTERS, KIND_RULE, page

router = APIRouter(dependencies=[Depends(open_book), Depends(parent_only)])


@router.get("/changes")
def changes(request: Request, user_id: int | None = None, kind: str | None = None, before: str | None = None,
            db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    if kind is not None and kind not in KIND_FILTERS:
        raise bad(KIND_RULE)
    try:
        cursor = datetime.fromisoformat(before) if before else None
    except ValueError:
        raise bad(NOT_UNDERSTOOD) from None
    if cursor is not None and cursor.tzinfo is None:
        raise bad(NOT_UNDERSTOOD)
    owners = {o.key: o.label for o in ctx.owners}
    out = page(db, request.app.state.books.directory, ctx.book.id, user_id=user_id, kind=kind, before=cursor,
               today=today(), owners=owners)
    out["people"] = [{"id": p.id, "name": p.display_name} for p in ctx.people]
    return out
