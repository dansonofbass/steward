"""Look into (spec 4.2): the list, the Home tab count, a flag's page, and the manager actions. Viewers read
everything and change nothing (spec 2.5)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import NOT_UNDERSTOOD, bad, json_object
from steward.db.models import Flag
from steward.deps import BookContext, book_db, open_book, parent_only, recorded
from steward.mail import mail_ready
from steward.watch import vocab as V
from steward.watch.flags import (
    NO_SUCH_FLAG, FlagRefused, change_note, mark_checking, mark_expected, mark_handled, reopen,
)
from steward.watch.views import counts, flag_detail, list_flags, ran

router = APIRouter(prefix="/flags", dependencies=[Depends(open_book), Depends(parent_only)])
SHOW_RULE = "Choose To look into or Done."
CHECK_RULE = "Choose one of the checks."


def owners_of(ctx: BookContext) -> dict[str, str]:
    return {o.key: o.label for o in ctx.owners}


def get_flag(db: Session, flag_id: int) -> Flag:
    f = db.get(Flag, flag_id)
    if f is None:
        raise bad(NO_SUCH_FLAG, 404)
    return f


def detail(request: Request, db: Session, ctx: BookContext, f: Flag) -> dict:
    return flag_detail(db, request.app.state.books.directory, f, deps.today(), owners_of(ctx), can_edit=ctx.is_manager)


@router.get("")
def list_(request: Request, show: str = "open", check: str | None = None, account_id: int | None = None,
          offset: int = 0, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    if show not in ("open", "done"):
        raise bad(SHOW_RULE)
    if check is not None and check not in V.RANK:
        raise bad(CHECK_RULE)
    if offset < 0:
        raise bad(NOT_UNDERSTOOD)
    today = deps.today()
    out = list_flags(db, request.app.state.books.directory, show=show, check=check, account_id=account_id,
                     offset=offset, today=today, owners=owners_of(ctx))
    out["ran"] = ran(db, today)
    out["mail_ready"] = mail_ready(request.app.state.mailer) if ctx.is_manager else None
    out["can_edit"] = ctx.is_manager
    return out


@router.get("/count")
def count(db: Session = Depends(book_db)):
    return counts(db)


@router.get("/{flag_id}")
def one(flag_id: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return detail(request, db, ctx, get_flag(db, flag_id))


def _act(request: Request, db: Session, ctx: BookContext, flag_id: int, fn) -> dict:
    f = get_flag(db, flag_id)
    try:
        out = fn(f) or {}
    except FlagRefused as e:
        raise bad(str(e), e.status) from None
    db.commit()
    return {**detail(request, db, ctx, f), "done_line": out.get("done_line")}


@router.post("/{flag_id}/expected")
@recorded
def expected(flag_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
             ctx: BookContext = Depends(open_book)):
    return _act(request, db, ctx, flag_id, lambda f: mark_expected(db, ctx, f, body, deps.now()))


@router.post("/{flag_id}/handled")
@recorded
def handled(flag_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
            ctx: BookContext = Depends(open_book)):
    return _act(request, db, ctx, flag_id, lambda f: mark_handled(db, ctx, f, body, deps.now()))


@router.post("/{flag_id}/checking")
@recorded
def checking(flag_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
             ctx: BookContext = Depends(open_book)):
    return _act(request, db, ctx, flag_id, lambda f: mark_checking(db, ctx, f, body, deps.now()))


@router.post("/{flag_id}/note")
@recorded
def note(flag_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
         ctx: BookContext = Depends(open_book)):
    return _act(request, db, ctx, flag_id, lambda f: change_note(db, ctx, f, body, deps.now()))


@router.post("/{flag_id}/reopen")
@recorded
def reopen_(flag_id: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return _act(request, db, ctx, flag_id, lambda f: reopen(db, ctx, f, deps.now()))
