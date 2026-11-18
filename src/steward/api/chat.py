"""Chat in a book (spec 5): its switch and disclosure, the preview, asking, the person's own conversations, the book's
log of what was sent, and spending. Asking changes nothing in the book's money, so viewers may (spec 5.1). Every
route goes through open_book; a person's conversations are listed only for them; every member reads the log."""
from __future__ import annotations

import json
import re
import secrets
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import date, datetime, time, timedelta

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward import clock, deps, gateway_name
from steward.advisor.about import AboutGone, AboutRefused, chips_for, parse_about, resolve
from steward.advisor.aliases import Aliases
from steward.advisor.gateway import GatewayRefused, GatewayUnavailable
from steward.advisor.history import conversation_detail, conversation_rows
from steward.advisor.identifiers import load_identifiers
from steward.advisor.outgoing import WHAT_FILTERS, export, record_payload, request_detail, requests_page
from steward.advisor.redact import Refused, exact_redact, issued_now
from steward.advisor.state import (
    DISCLOSURE, OFF_LINE, budget_lines, changed, chat_on, gateway_line, gateway_state, mark_seen, money, seen,
    set_chat_on,
)
from steward.advisor.turn import (
    MAX_QUESTION, NO_CONVERSATION, NOT_RUNNING, NOT_WAITING, TOO_LONG_QUESTION, AskEnv, ChatRefused, run_turn,
    start_turn,
)
from steward.api.body import NOT_UNDERSTOOD, bad, json_object, one_of, whole
from steward.db.directory_models import Membership, User
from steward.db.models import AdvisorOutgoing, ChatConversation
from steward.books.people import names_of
from steward.books.registry import household_book_id, household_name
from steward.deps import (
    BookContext, book_db, install_household, managers_only, not_recorded, open_book, real_book_only, sample_ok, viewer_ok,
)
from steward.inventory.present import at_label, day_label, month_year
from steward_boundary import tools as T
from steward_boundary.about import about_text
from steward_boundary.canonical import canonical, sha256_hex
from steward_boundary.protocol import LINES
from steward_boundary.spans import Edit, apply, shift

router = APIRouter(prefix="/chat", dependencies=[Depends(open_book), Depends(real_book_only)])
MODELS = [{"id": "claude-opus-5-5", "label": "Claude Opus 5.5 (the default)"},
          {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 (about half the cost)"}]


def _stopped() -> HTTPException:
    return HTTPException(422, detail={"error": LINES["stopped_check"], "stop": "stopped_check"})


def _rt(request: Request):
    return request.app.state.advisor


def _install_household_id(request: Request) -> int | None:
    with Session(request.app.state.books.directory) as ddb:
        return household_book_id(ddb)


def _household_name(request: Request) -> str:
    with Session(request.app.state.books.directory) as ddb:
        return household_name(ddb)


def _env(request: Request, db: Session, ctx: BookContext) -> AskEnv:
    books = request.app.state.books
    return AskEnv(bind=db.get_bind(), directory=books.directory, book=ctx.book, user_id=ctx.user_id,
                  people=lambda: books.people(ctx.book.id), plan_cache=books.plan_cache(ctx.book.id),
                  gateway=_rt(request).client, now=deps.now, today=deps.today, household_name=_household_name(request),
                  control=_rt(request).control)


def _roles(request: Request, ctx: BookContext) -> dict[int, str]:
    with Session(request.app.state.books.directory) as d:
        return dict(d.execute(select(Membership.user_id, Membership.role)
                              .where(Membership.book_id == ctx.book.id)).all())


def _sent_month(db: Session, today: date) -> dict:
    start = datetime.combine(today.replace(day=1), time(0), clock.household_tz())
    sub = select(AdvisorOutgoing.turn_id, AdvisorOutgoing.seq).where(AdvisorOutgoing.at >= start).distinct().subquery()
    last = db.scalar(select(AdvisorOutgoing.at).order_by(AdvisorOutgoing.id.desc()).limit(1))
    return {"requests": int(db.scalar(select(func.count()).select_from(sub)) or 0),
            "last": at_label(last, today) if last else None}


@router.get("")
@sample_ok
def status(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    rt = _rt(request)
    health = rt.monitor.fresh(10.0)          # before the first query: no transaction is open while it waits
    state = gateway_state(health, rt.client is not None)
    who = changed(db)
    names = names_of(ctx.people, mid=True)          # "Turned on by {name}"
    change = None
    if who is not None:
        by, at, on = who
        day = day_label(at.astimezone(clock.household_tz()).date(), deps.today())
        change = {"by": names.get(by), "at": at.isoformat(),
                  "line": f"Turned {'on' if on else 'off'} by {names.get(by, 'someone')}, {day}"}
    budget = (health or {}).get("budget")
    mon, today = rt.monitor, deps.today()
    roles = _roles(request, ctx)
    gateway = {"state": state, "line": gateway_line(state),
               "last_answered": at_label(mon.last_ok, today) if mon.last_ok else None,
               "checked": at_label(mon.checked_at, today) if mon.checked_at else None,
               "checks": None if health is None else {"redaction": bool(health.get("redaction_ready")),
                                                      "key": bool(health.get("key_set")),
                                                      "categorizer": bool(health.get("categorizer"))},
               "paired": rt.client is not None, "url_set": bool(request.app.state.settings.gateway_url),
               "pdf_place": request.app.state.statements.place,
               # Release spec 2026-11-05, section 6: whether Claude Code is on at the gateway. One from before the
               # setting sends nothing, and always listened; away, nobody knows (None keeps the section, for Revoke).
               "mcp": None if health is None else bool(health.get("mcp", True)),
               "away_long": state == "away" and mon.away_for(deps.now()) >= timedelta(minutes=10)}
    out = {"on": chat_on(db), "can_change": ctx.is_manager, "changed": change, "seen": seen(db, ctx.user_id),
           "disclosure": DISCLOSURE, "off_line": OFF_LINE, "gateway": gateway,
           "members": [p.display_name for p in ctx.people],
           # who still sees the disclosure once: everyone but the person reading this (INS-18)
           "others": [p.display_name for p in ctx.people if p.id != ctx.user_id],
           "managers": [p.display_name for p in ctx.people if roles.get(p.id) == "manager"],
           "sent_month": _sent_month(db, today),
           "budget": None if not budget else {**budget_lines(budget, _household_name(request), deps.today()),
                                              "spent_cents": budget["spent_cents"], "cap_cents": budget["cap_cents"],
                                              "questions": budget["questions"], "model": budget["model"]},
           "can_budget": ctx.is_manager and ctx.book.id == _install_household_id(request),
           "models": MODELS}
    db.rollback()
    return out


@router.post("/on")
@not_recorded("Chat on or off is shown in Settings → Chat with who changed it and when.")
def set_on(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    on = body.get("on")
    if not isinstance(on, bool):
        raise bad("Choose on or off.")
    set_chat_on(db, on, ctx.user_id, deps.now())
    if on:
        mark_seen(db, ctx.user_id, deps.now())    # the manager read the disclosure before turning chat on
    db.commit()
    return status(request, db, ctx)


@router.post("/seen")
@viewer_ok
@not_recorded("Reading the chat disclosure changes nothing in the book.")
def mark(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    mark_seen(db, ctx.user_id, deps.now())
    db.commit()
    return {"seen": True}


@router.post("/preview")
@viewer_ok
@not_recorded("A preview sends nothing to Claude and changes nothing in the book.")
def preview(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
            ctx: BookContext = Depends(open_book)):
    text = body.get("text")
    if not isinstance(text, str):
        raise bad(NOT_UNDERSTOOD)
    text = text.strip()
    if len(text) > MAX_QUESTION:
        raise bad(TOO_LONG_QUESTION)
    if not chat_on(db):
        raise bad(OFF_LINE, 409)
    aliases = Aliases(db, ctx.book, ctx.people, save=False)
    idents = load_identifiers(db, ctx.book, ctx.people, request.app.state.books.directory, aliases, deps.today())
    labels = aliases.labels()
    try:
        first, chips = exact_redact(text, idents)
    except Refused:
        db.rollback()
        raise _stopped() from None
    db.rollback()
    gw = _rt(request).client
    if gw is None:
        raise bad(gateway_name.fill(LINES["not_set_up"]), 503)
    try:
        r = gw.redact(first, issued_now(chips))
    except GatewayUnavailable:
        raise bad(gateway_name.fill(LINES["away"]), 503) from None
    except GatewayRefused as e:
        raise bad(e.message, 503) from None
    try:
        edits = [Edit(**e) for e in r["edits"]]
        merged = sorted(shift(chips, edits) + apply(first, edits)[1], key=lambda c: c["start"])
    except (ValueError, TypeError):             # an edit that reaches into an alias chip is never guessed at
        raise _stopped() from None
    return {"text": r["text"], "as_written": r["text"] == text, "chips": merged,
            "labels": {c["label"]: labels[c["label"]] for c in merged if c["label"] in labels}}


@router.post("/about")
@viewer_ok
@not_recorded("Working out what a question is about sends nothing and changes nothing.")
def about_preview(body: dict = Depends(json_object), db: Session = Depends(book_db),
                  ctx: BookContext = Depends(open_book)):
    """{about} (Ask about this P8): the chip and its line, worked out on the NAS alone with Aliases(save=False) and no
    gateway call, so it answers while the gateway is away. `labels` put the account's name back on the chip on screen;
    they are never in `sent` or the wire."""
    if set(body) != {"about"}:
        raise bad(NOT_UNDERSTOOD)
    try:
        wanted = parse_about(body["about"])
    except AboutRefused as e:
        raise bad(e.message) from None
    if wanted is None:
        raise bad(NOT_UNDERSTOOD)
    if not chat_on(db):
        db.rollback()
        raise bad(OFF_LINE, 409)
    aliases = Aliases(db, ctx.book, ctx.people, save=False)
    try:
        wire = resolve(db, ctx.book, aliases, wanted, deps.today())
    except AboutGone as e:
        db.rollback()
        raise bad(e.message, 404) from None
    except AboutRefused as e:
        db.rollback()
        raise bad(e.message) from None
    labels = aliases.labels()
    db.rollback()
    sent = about_text(wire)
    chips = chips_for(sent, wire)
    return {"about": wire, "sent": sent, "chips": chips,
            "labels": {c["label"]: labels[c["label"]] for c in chips if c["label"] in labels}}


@router.post("/prewarm")
@viewer_ok
@not_recorded("Getting ready sends only Steward's fixed instructions, and it is listed in the log of what was sent.")
def prewarm(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    gw = _rt(request).client
    if gw is None or not chat_on(db):
        db.rollback()
        return {"sent": False}
    db.rollback()
    try:
        plan = gw.prewarm_plan(ctx.book.id, ctx.user_id)
    except (GatewayUnavailable, GatewayRefused):
        return {"sent": False}
    if not plan["due"] or sha256_hex(plan["payload"]) != plan["sha256"]:
        return {"sent": False}
    record_payload(db, user_id=ctx.user_id, conversation_id=None, turn_id="p_" + secrets.token_hex(8), seq=1,
                   channel="prewarm", part="system", payload=plan["payload"], now=deps.now(), model=plan.get("model"))
    db.commit()
    try:
        return {"sent": bool(gw.prewarm(ctx.book.id, ctx.user_id, plan["sha256"]).get("sent"))}
    except (GatewayUnavailable, GatewayRefused):
        return {"sent": False}


@router.post("/ask")
@viewer_ok
@not_recorded("Conversations have their own log of what was sent.")
def ask(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
        ctx: BookContext = Depends(open_book)):
    question, cid = body.get("question"), body.get("conversation_id")
    if not isinstance(question, str) or (cid is not None and (isinstance(cid, bool) or not isinstance(cid, int))):
        raise bad(NOT_UNDERSTOOD)
    try:
        wanted = parse_about(body.get("about"))
    except AboutRefused as e:
        raise bad(e.message) from None
    env = _env(request, db, ctx)
    db.rollback()
    try:
        prep = start_turn(env, question, cid, wanted)
    except ChatRefused as e:
        if e.stop:
            raise HTTPException(e.status, detail={"error": e.message, "stop": e.stop}) from None
        raise bad(e.message, e.status) from None

    control = _rt(request).control
    return StreamingResponse(stream_turn(run_turn(env, prep), lambda: control.release(prep.turn_id)),
                             media_type="application/x-ndjson")


_END = object()


class _Steps:
    """Steps a turn's generator in worker threads, one event at a time. Whoever is last to touch it after the browser
    leaves closes it: the stream at once if no step is running, or the running step when it returns."""

    def __init__(self, turn: Iterator[dict]):
        self.turn, self.lock, self.busy, self.left = turn, threading.Lock(), False, False

    def step(self):
        with self.lock:
            if self.left:
                return _END
            self.busy = True
        try:
            return next(self.turn, _END)
        finally:
            with self.lock:
                self.busy, left = False, self.left
            if left:
                self.turn.close()

    def leave(self) -> None:
        with self.lock:
            self.left, busy = True, self.busy
        if not busy:
            self.turn.close()


async def stream_turn(turn: Iterator[dict], release: Callable[[], None]) -> AsyncIterator[str]:
    """The turn as NDJSON lines (Task 6.5). Starlette cancels the response when the browser disconnects; Starlette's
    own iterate_in_threadpool would wait for the worker thread first, which in a store-names card's wait is up to
    10 minutes, holding the worker and the gateway's socket. Here the wait for each step is abandoned on cancel, and
    release() ends the card's wait or the reply poll at once, so the worker cancels at the gateway, closes the
    socket and finishes the turn within a moment."""
    steps = _Steps(turn)
    try:
        while True:
            event = await anyio.to_thread.run_sync(steps.step, abandon_on_cancel=True)
            if event is _END:
                return
            yield json.dumps(event, ensure_ascii=False) + "\n"
    finally:
        release()
        with anyio.CancelScope(shield=True):    # closing writes the book's events: off the event loop
            await anyio.to_thread.run_sync(steps.leave)


_TICK = re.compile(r"[rp][0-9]{1,3}")


def _ticks_ok(ticked: object) -> bool:
    """At most one tick per row and payee a card can hold, each "r<i>" or "p<i>"."""
    return (isinstance(ticked, list) and len(ticked) <= T.MERCHANT_ROWS + 50
            and all(isinstance(t, str) and _TICK.fullmatch(t) for t in ticked))


@router.post("/approvals")
@not_recorded("An approval is kept in the book's log of what was sent, with who approved it.")
def approve(request: Request, body: dict = Depends(json_object), ctx: BookContext = Depends(open_book)):
    turn_id, call_id, send, digest = body.get("turn_id"), body.get("call_id"), body.get("send"), body.get("hash")
    ticked = body.get("ticked", [])
    if (not isinstance(turn_id, str) or not isinstance(call_id, str) or not isinstance(send, bool)
            or not isinstance(digest, str | None) or not _ticks_ok(ticked)):
        raise bad(NOT_UNDERSTOOD)
    # Viewers never reach here (no viewer_ok: open_book gives them 403, so only a manager now). The live turn takes the
    # answer only from its own person in its own book, for the call it is waiting on, with the hash of the card it
    # showed (Task 6.5); the turn checks again that the person is still a manager before anything is sent.
    # `ticked` names the rows whose recipient's name goes too (public issue #1); the turn takes only keys its card offered.
    if not ctx.is_manager or not _rt(request).control.answer(turn_id, call_id, ctx.user_id, ctx.book.id, send, digest,
                                                             ticked):
        raise bad(NOT_WAITING, 404)
    return {"ok": True}


@router.post("/turns/{turn_id}/stop")
@viewer_ok
@not_recorded("Stopping an answer changes nothing in the book.")
def stop_turn(turn_id: str, request: Request, ctx: BookContext = Depends(open_book)):
    if not _rt(request).control.stop(turn_id, ctx.user_id, ctx.book.id):
        raise bad(NOT_RUNNING, 404)
    return {"ok": True}


@router.get("/conversations")
def conversations(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    labels = Aliases(db, ctx.book, ctx.people, save=False).labels()
    out = conversation_rows(db, ctx.user_id, labels, deps.today())
    db.rollback()
    return {"conversations": out}


def _own(db: Session, cid: int, ctx: BookContext) -> ChatConversation:
    c = db.get(ChatConversation, cid)
    if c is None or c.user_id != ctx.user_id or c.deleted_at is not None:
        raise bad(NO_CONVERSATION, 404)
    return c


@router.get("/conversations/{cid}")
def conversation(cid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    c = _own(db, cid, ctx)
    labels = Aliases(db, ctx.book, ctx.people, save=False).labels()
    out = conversation_detail(db, c, labels, names_of(ctx.people), ctx.book.kind, deps.today())
    db.rollback()
    return out


@router.delete("/conversations/{cid}")
@viewer_ok
@not_recorded("Deleting a conversation takes it off the person's own list; what it sent stays in the book's log.")
def delete_conversation(cid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    c = _own(db, cid, ctx)
    c.deleted_at = deps.now()
    db.commit()
    return {"deleted": True}


@router.get("/sent")
def sent(request: Request, offset: int = 0, who: int | None = None, what: str | None = None,
         db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    if offset < 0:
        raise bad(NOT_UNDERSTOOD)
    if what is not None and what not in WHAT_FILTERS:
        raise bad("That filter wasn't understood.")
    out = requests_page(db, request.app.state.books.directory, offset=offset, today=deps.today(), people=ctx.people,
                        who=who, what=what)
    db.rollback()
    return out


@router.get("/sent/{key}")
def sent_one(key: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    labels = Aliases(db, ctx.book, ctx.people, save=False).labels()
    d = request_detail(db, key, names=names_of(ctx.people), labels=labels, today=deps.today())
    db.rollback()
    if d is None:
        raise bad("That isn't in the log.", 404)
    return d


@router.get("/export", dependencies=[Depends(managers_only)])
def export_log(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return JSONResponse(export(db), headers={
        "Content-Disposition": f'attachment; filename="steward-{ctx.book.slug}-sent-to-anthropic.json"'})


@router.get("/instructions")
def instructions(request: Request, ctx: BookContext = Depends(open_book)):
    """Steward's fixed instructions to Claude and its tool definitions, whole, with their hash (public issue #3): what a
    Getting ready row's prefix_sha256 stands for. They hold no household data and are the same for every install of a
    version. Shown only when the text the gateway sends hashes to the hash it gives, else None, as when it is away."""
    gw = _rt(request).client
    if gw is None:
        return {"instructions": None}
    try:
        x = gw.instructions()
    except (GatewayUnavailable, GatewayRefused):
        return {"instructions": None}
    content = x.get("content") if isinstance(x, dict) else None
    try:
        system = "\n\n".join(b["text"] for b in content["system"])
        tools = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                 for t in content["tools"]]
    except (KeyError, TypeError):
        return {"instructions": None}
    if not isinstance(x.get("prefix_sha256"), str) or sha256_hex(content) != x["prefix_sha256"]:
        return {"instructions": None}
    # `hashed` is the exact text the hash is of (canonical JSON, with each tool's flags and the cache marks), so a reader
    # can hash it themselves rather than take "the same as this row's" on trust.
    return {"instructions": {"prefix": x.get("prefix"), "sha256": x["prefix_sha256"], "system": system, "tools": tools,
                             "hashed": canonical(content).decode("utf-8")}}


@router.get("/usage")
def usage(request: Request, ctx: BookContext = Depends(open_book)):
    gw = _rt(request).client
    if gw is None:
        return {"usage": None}
    try:
        u = gw.usage()
    except (GatewayUnavailable, GatewayRefused):
        return {"usage": None}
    books = request.app.state.books
    with Session(books.directory) as ddb:
        mine = set(ddb.scalars(select(Membership.book_id).where(Membership.user_id == ctx.user_id)))
        names = dict(ddb.execute(select(User.id, User.display_name)).all())
    book_names = {b.id: b.name for b in books.books()}
    return {"usage": {
        "months": [{"month": month_year(date.fromisoformat(m["month"] + "-01")), "spent": money(m["spent_cents"]),
                    "questions": m["questions"]} for m in reversed(u["months"])],
        "by_book": [{"book": book_names.get(b["book_id"], "A book"), "spent": money(b["spent_cents"]),
                     "questions": b["questions"]} for b in u["by_book"] if b["book_id"] in mine],
        "by_person": [{"book": book_names.get(p["book_id"], "A book"),
                       "person": names.get(p["user_id"], "Someone no longer in the book"),
                       "spent": money(p["spent_cents"]), "questions": p["questions"]}
                      for p in u["by_person"] if p["book_id"] in mine]}}


@router.post("/budget", dependencies=[Depends(install_household)])
@not_recorded("The chat budget and model are household-wide settings kept on the gateway and shown in Settings → Chat.")
def budget(request: Request, body: dict = Depends(json_object)):
    fields = {}
    if body.get("cap_dollars") is not None:
        fields["cap_cents"] = whole(body["cap_dollars"], "Choose a budget from $1 to $100.", 1, 100) * 100
    if body.get("model") is not None:
        fields["model"] = one_of(body["model"], [m["id"] for m in MODELS], "Choose Claude Opus 5.5 or Claude Sonnet 5.5.")
    if not fields:
        raise bad(NOT_UNDERSTOOD)
    gw = _rt(request).client
    if gw is None:
        raise bad(gateway_name.fill(LINES["not_set_up"]), 503)
    try:
        gw.set_settings(**fields)
    except GatewayUnavailable:
        raise bad(gateway_name.fill(LINES["away"]), 503) from None
    except GatewayRefused as e:
        raise bad(e.message, 422 if e.status == 422 else 503) from None
    _rt(request).monitor.poll()
    return {"ok": True}
