from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import SimplefinLink
from steward.deps import BookContext, book_db, not_recorded, now, open_book, real_book_only, recorded, sample_ok
from steward.inventory.changes import record
from steward.services.simplefin.client import SimplefinError, claim, parse_setup_token
from steward.services.simplefin.sync import needs_sign_in, sync_now

router = APIRouter(dependencies=[Depends(open_book), Depends(real_book_only)])


class LinkIn(BaseModel):
    setup_token: str


def _link(db: Session) -> SimplefinLink | None:
    return db.scalar(select(SimplefinLink).order_by(SimplefinLink.id))


def _run(request: Request):
    from steward.books.owners import default_owner
    from steward.inventory.accounts import parent_hook
    st, book = request.app.state, request.state.book.book
    return sync_now(st.books.engine_for(book), st.http, st.model, now(), st.settings.simplefin_allowed_hosts,
                    default_owner=default_owner(book.owner_names), after=parent_hook(book.kind), household=book.kind == "household")


def _lock(request: Request):
    return request.app.state.books.sync_lock(request.state.book.book.id)


@router.get("/simplefin")
@sample_ok
def status(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    link = _link(db)
    return {"linked": link is not None,
            "last_sync_at": link.last_sync_at.isoformat() if link and link.last_sync_at else None,
            "last_error": link.last_error if link else None,
            "sign_in": needs_sign_in(db, ctx.is_manager)}   # issue #16: the banks Home's Fix is about


@router.post("/simplefin/link", status_code=201)
@recorded
def link(body: LinkIn, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    st = request.app.state
    hosts = st.settings.simplefin_allowed_hosts
    if _link(db) is not None:
        raise HTTPException(409, detail={"error": "SimpleFIN is already linked. Unlink it first."})
    db.rollback()  # no transaction open while we talk to SimpleFIN
    try:
        claim_url = parse_setup_token(body.setup_token, hosts)
    except (ValueError, SimplefinError):
        raise HTTPException(422, detail={"error": "That setup token isn't valid."}) from None
    try:
        access_url = claim(st.http, claim_url, hosts)
    except SimplefinError as e:
        raise HTTPException(502, detail={"error": str(e)}) from None
    if _link(db) is not None:  # linked by someone else while we were claiming
        raise HTTPException(409, detail={"error": "SimpleFIN is already linked. Unlink it first."})
    db.add(SimplefinLink(access_url=access_url, claimed_at=now()))
    record(db, ctx, "feed.connect")
    db.commit()
    lock = _lock(request)
    if not lock.acquire(timeout=90):
        return {"linked": True, "sync": None}  # the sync already in flight covers it
    try:
        result = _run(request)
    finally:
        lock.release()
    return {"linked": True, "sync": asdict(result) if result else None}


@router.delete("/simplefin", status_code=204)
@recorded
def unlink(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    link = _link(db)
    if link is not None:
        db.delete(link)  # institutions, accounts and transactions stay
        record(db, ctx, "feed.disconnect")
        db.commit()
    return Response(status_code=204)


@router.post("/sync")
@not_recorded("A sync brings in what the bank reports; each one is listed under Settings → Banks.")
def sync(request: Request, db: Session = Depends(book_db)):
    db.commit()  # sign-in check may have written; free the write lock for the sync's own session
    lock = _lock(request)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, detail={"error": "A sync is already running."})
    try:
        result = _run(request)
    finally:
        lock.release()
    if result is None:
        raise HTTPException(409, detail={"error": "SimpleFIN isn't linked yet."})
    return asdict(result)
