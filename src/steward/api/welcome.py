"""GET /api/b/{slug}/welcome: what this person's welcome plays and where its steps stand, read live (guided setup spec
7, plan D7). It never writes. The directory is read first and let go before the book is opened, so no transaction
waits on the other."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.books.registry import household_book_id
from steward.books.service import welcome_kind
from steward.db.directory_models import Book, Membership, User
from steward.db.models import Account, SimplefinLink, Transaction
from steward.deps import BookContext, book_db, directory_db, now, open_book
from steward.services.review import waiting_filter

router = APIRouter(prefix="/welcome", dependencies=[Depends(open_book)])


@router.get("")
def welcome(request: Request, ctx: BookContext = Depends(open_book), ddb: Session = Depends(directory_db),
            db: Session = Depends(book_db)) -> dict:
    book = ddb.get(Book, ctx.book.id)
    m = ddb.get(Membership, (ctx.user_id, ctx.book.id))
    kind = welcome_kind(book, m, household_book_id(ddb), ctx.user_id, ignore_mark=True)
    inviter = None
    if kind == "partner" and m.created_by not in (None, ctx.user_id):
        inviter = ddb.scalar(select(User.display_name).where(User.id == m.created_by))
    seen = m.welcome_seen_at is not None
    ddb.rollback()

    linked = db.scalar(select(SimplefinLink.id).limit(1)) is not None
    accounts = db.scalar(select(func.count()).select_from(Account).where(Account.is_active.is_(True))) or 0
    rows = db.scalar(select(func.count()).select_from(Transaction)) or 0
    waiting = db.scalar(select(func.count()).select_from(Transaction).where(waiting_filter(now()))) or 0
    db.rollback()

    money_in = linked or rows > 0
    zone = request.app.state.app_settings.effective()["general.timezone"]
    return {"kind": kind, "seen": seen, "inviter": inviter,
            "money": {"in": money_in, "linked": linked, "accounts": accounts, "rows": rows}, "waiting": waiting,
            "zone_needed": kind == "first_run" and zone.source == "default" and not os.environ.get("TZ"),
            "step": "money" if not money_in else "sort" if waiting else "extras"}
