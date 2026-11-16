"""Settings → Chat → Claude Code (spec 5.1, 7, ruling 3). Every member of the book sees its grants; only managers
issue one, and only for themselves (final review M6: Claude Code's lookups are logged as the grant's person, so that
is always someone who has seen the disclosure); the grant's text is in the answer to the issue and nowhere else; a
manager or the person a grant is for can revoke it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from steward import deps
from steward.advisor import grants as G
from steward.api.body import bad, json_object
from steward.db.directory_models import AdvisorGrant
from steward.deps import BookContext, not_recorded, open_book, real_book_only, viewer_ok

router = APIRouter(prefix="/chat/grants", dependencies=[Depends(open_book), Depends(real_book_only)])
FOR_YOURSELF = "A grant is for the manager who issues it."
NOT_YOURS = "Only a manager or the person it's for can revoke a grant."
NO_GRANT = "No such grant."
NOTE = "Claude Code grants are listed in Settings → Chat with who issued them and who revoked them."


def _ddb(request: Request) -> Session:
    return Session(request.app.state.books.directory.execution_options(immediate=True))


def _row(ddb: Session, g: AdvisorGrant, ctx: BookContext) -> dict:
    names = G.names_for(ddb, {i for i in (g.user_id, g.issued_by, g.revoked_by) if i is not None})
    return G.row(g, names, now=deps.now(), today=deps.today(), me=ctx.user_id, manager=ctx.is_manager)


@router.get("")
def list_grants(request: Request, ctx: BookContext = Depends(open_book)):
    with _ddb(request) as ddb:
        found = G.rows(ddb, ctx.book.id, now=deps.now(), today=deps.today(), me=ctx.user_id, manager=ctx.is_manager)
        ddb.rollback()
    return {"grants": found, "can_issue": ctx.is_manager, "days": G.GRANT_DAYS}


@router.post("")
@not_recorded(NOTE)
def issue_grant(request: Request, body: dict = Depends(json_object), ctx: BookContext = Depends(open_book)):
    uid = body.get("user_id", ctx.user_id)
    if isinstance(uid, bool) or uid != ctx.user_id:
        raise bad(FOR_YOURSELF)
    with _ddb(request) as ddb:
        g, text = G.issue(ddb, book_id=ctx.book.id, slug=ctx.book.slug, user_id=ctx.user_id, by=ctx.user_id,
                          now=deps.now())
        ddb.commit()
        return {"grant": text, "command": "steward-gateway mcp-grant add", "row": _row(ddb, g, ctx)}


@router.post("/{grant_id}/revoke")
@viewer_ok
@not_recorded(NOTE)
def revoke_grant(grant_id: int, request: Request, ctx: BookContext = Depends(open_book)):
    with _ddb(request) as ddb:
        g = ddb.get(AdvisorGrant, grant_id)
        if g is None or g.book_id != ctx.book.id:
            raise HTTPException(404, detail={"error": NO_GRANT})
        if not ctx.is_manager and g.user_id != ctx.user_id:
            raise HTTPException(403, detail={"error": NOT_YOURS})
        G.revoke(g, ctx.user_id, deps.now())
        ddb.commit()
        return {"row": _row(ddb, g, ctx)}
