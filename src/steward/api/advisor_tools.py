"""The routes the gateway calls for Claude Code (spec 7, rulings 1, 7). Every one goes through open_book_by_grant,
so each call re-checks the grant and the membership. A tool runs exactly as chat runs it (run_call: input checked,
read-only, aliases, result schema and stored-text rule); its part waits here for one minute; the gateway runs the
outgoing checks and then says "sent" (the NAS writes its own copy to the book's log, channel mcp) or "stopped" (a book
event with the check and the path). Nothing is recorded that the gateway didn't clear, and nothing the tool didn't
produce."""
from __future__ import annotations

import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from steward import clock, deps
from steward.advisor.aliases import Aliases
from steward.advisor.identifiers import load_identifiers
from steward.advisor.mcp import PENDING_S, PendingCall, offered
from steward.advisor.outgoing import record_parts
from steward.advisor.redact import turn_hash_sets
from steward.advisor.state import OFF_LINE, chat_on
from steward.advisor.tools import run_call
from steward.api.body import NOT_UNDERSTOOD, bad, json_object
from steward.books.people import attach_people
from steward.db.engine import begin_write
from steward.deps import BookContext, grant_book_db, not_recorded, open_book_by_grant, viewer_ok
from steward.events import log_event
from steward.inventory.present import day_label
from steward_boundary import tools as T
from steward_boundary.canonical import canonical, sha256_hex
from steward_boundary.protocol import CHECK_WORDS

router = APIRouter(prefix="/advisor", dependencies=[Depends(open_book_by_grant)])
NOT_OFFERED = "Claude Code can't use that tool."
EXPIRED = "That call has expired. Call the tool again."
NOTE = "Claude Code's lookups change nothing in the book; what they return is kept in the book's log of what was sent."
PATH_RE = re.compile(r"^[A-Za-z0-9_.\[\]]{1,200}$")


def _rt(request: Request):
    return request.app.state.advisor


def _off(db: Session) -> None:
    if not chat_on(db):
        db.rollback()
        raise HTTPException(409, detail={"error": OFF_LINE})


@router.get("/tools")
def tools(request: Request, db: Session = Depends(grant_book_db), ctx: BookContext = Depends(open_book_by_grant)):
    """For tools/list, and for `steward-gateway mcp-grant add` to say until when and whether chat is on. No book name
    and no person's name (ruling I1b): Settings → Chat already says whose grant it is. Answers with chat off too
    (`chat` says so), so a grant can be added before chat is turned on; the tools themselves refuse until it is."""
    begin_write(db)                     # a GET that writes: the asker's alias, the first time
    on = chat_on(db)
    asker = Aliases(db, ctx.book, ctx.people).user(ctx.user_id)
    db.commit()
    until = request.state.grant_expires.astimezone(clock.household_tz()).date()
    return {"book_id": ctx.book.id, "book_kind": ctx.book.kind, "until": day_label(until, deps.today()),
            "asker": asker, "chat": on, "tools": offered(ctx.book.kind)}


@router.post("/tools/{name}")
@viewer_ok
@not_recorded(NOTE)
def call_tool(name: str, request: Request, body: dict = Depends(json_object), db: Session = Depends(grant_book_db),
              ctx: BookContext = Depends(open_book_by_grant)):
    if name not in offered(ctx.book.kind):
        raise HTTPException(404, detail={"error": NOT_OFFERED})
    _off(db)
    bind = db.get_bind()
    db.rollback()                      # no lock held while the tool computes
    books, today = request.app.state.books, deps.today()
    hexid = secrets.token_hex(8)
    call_id = f"mcp_{hexid}"
    result = run_call({"id": call_id, "name": name, "input": body.get("input", {})}, bind=bind, book=ctx.book,
                      user_id=ctx.user_id, people=ctx.people, today=today, plan_cache=books.plan_cache(ctx.book.id),
                      directory=books.directory)
    is_error = result["error"] is not None
    payload = {"tool_use_id": call_id, "name": name, "is_error": is_error,
               "content": {"error": result["error"]} if is_error else result["content"]}
    with Session(bind) as s:
        attach_people(s, lambda: ctx.people)
        idents = load_identifiers(s, ctx.book, ctx.people, books.directory, Aliases(s, ctx.book, ctx.people), today)
        s.commit()
    salt = secrets.token_hex(16)
    rest, approvable = turn_hash_sets(idents, salt)
    part = {"part": "tool_result", "payload": payload, "sha256": sha256_hex(payload), "bytes": len(canonical(payload))}
    now = deps.now()
    _rt(request).mcp.put(call_id, PendingCall(ctx.book.id, ctx.user_id, f"t_{hexid}", part,
                                              now + timedelta(seconds=PENDING_S)), now)
    # No store rows go over MCP, so every hash is checked against every part (plan B ruling 3 doesn't apply).
    return {"call_id": call_id, "book_id": ctx.book.id, "part": part,
            "fingerprints": {"salt": salt, "hashes": sorted(set(rest) | set(approvable))}}


@router.post("/calls/{call_id}")
@viewer_ok
@not_recorded(NOTE)
def finish_call(call_id: str, request: Request, body: dict = Depends(json_object),
                db: Session = Depends(grant_book_db), ctx: BookContext = Depends(open_book_by_grant)):
    outcome, check, path = body.get("outcome"), body.get("check"), body.get("path")
    if outcome not in ("sent", "stopped"):
        raise bad(NOT_UNDERSTOOD)
    if outcome == "stopped" and (check not in CHECK_WORDS or not isinstance(path, str) or not PATH_RE.match(path)):
        raise bad(NOT_UNDERSTOOD)
    now = deps.now()
    call = _rt(request).mcp.take(call_id, ctx.book.id, ctx.user_id, now)
    if call is None:
        raise HTTPException(404, detail={"error": EXPIRED})
    if outcome == "stopped":
        log_event(db, "warn", "chat", f"Steward stopped a Claude Code lookup before anything was returned: the "
                                      f"{CHECK_WORDS[check]} check fired at {path}.")
        db.commit()
        return {"recorded": False}
    record_parts(db, user_id=ctx.user_id, conversation_id=None, turn_id=call.turn_id, seq=1, channel="mcp",
                 model=None, parts=[call.part], now=now)
    db.commit()
    return {"recorded": True, "sha256": call.part["sha256"], "bytes": call.part["bytes"]}
