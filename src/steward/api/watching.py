"""Settings → Watching (README screen 5): the large amount, low-balance floors, known payees and email. Changes apply
to new transactions only (spec 4.1). Everyone in the book can read it; managers change it."""
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.books.history import names_for
from steward.db.models import Flag, InventoryItem, MailOutbox, WatchKnown
from steward.deps import BookContext, book_db, not_recorded, open_book, parent_only, recorded, viewer_ok
from steward.inventory.changes import record
from steward.inventory.present import article, at_label, joined, mask, mask_numbers, parent_name, safe_line, usd
from steward.mail import mail_ready
from steward.watch import vocab as V
from steward.watch.balances import balance_on, check_low, floored_items, low_key
from steward.watch.checks import day
from steward.watch.flags import FlagRefused, range_text, remove_known
from steward.watch.recipients import members, prefs, set_prefs, stop_mine
from steward.watch.store import CASH_FLOOR, LARGE, active_known, cash_floor_cents, large_cents, set_state
from steward.watch.views import local_day

router = APIRouter(prefix="/watching", dependencies=[Depends(open_book), Depends(parent_only)])
LARGE_RULE = "Enter an amount from $1.00 to $1,000,000.00."
FLOOR_ITEM = "Choose a checking, savings or CD account."
FLOOR_AMOUNT = "Enter a floor in dollars and cents, or leave it blank."
NO_SUCH_KNOWN = "No such known payee."
NOT_SET_UP = "Email isn't set up."
TEST_SUBJECT = "Steward test email"


def _floors(db: Session, today) -> list[dict]:
    out = []
    for item, d in floored_items(db):
        bal = balance_on(db, item.account_id, today)
        source = {"feed": f"now {usd(bal[1])}" if bal else None, "statement": "statements",
                  "manual": "typed in"}.get(item.data_source or "")
        head = " ".join(p for p in (item.institution, mask(item.last4)) if p)
        floor = d.get("floor_cents")
        out.append({"item_id": item.id, "name": item.name, "sub": " · ".join(p for p in (head, source) if p),
                    "balance_cents": bal[1] if bal else None, "floor_cents": floor,
                    "under": bool(bal and floor is not None and bal[1] < floor)})
    return out


def _mail(request: Request, db: Session, ctx: BookContext, today) -> dict:
    directory = request.app.state.books.directory
    sent = db.scalar(select(MailOutbox).where(MailOutbox.status == "sent").order_by(MailOutbox.sent_at.desc()).limit(1))
    failed = db.scalar(select(MailOutbox).where(MailOutbox.status == "failed").order_by(MailOutbox.failed_at.desc()).limit(1))
    ids = [*json.loads(sent.sent_to if sent else "[]"), *json.loads((failed.to_user_ids if failed else None) or "[]")]
    names = names_for(directory, ids)
    last = None
    if sent is not None:
        what = "daily summary" if sent.kind == "summary" else "an urgent email"
        last = (f"Last sent {at_label(sent.sent_at, today)} ({what} to "
                f"{joined([names.get(i, 'someone') for i in json.loads(sent.sent_to)])}).")
    failure = None
    if failed is not None and (sent is None or sent.sent_at < failed.failed_at):
        flag = db.get(Flag, failed.flag_id) if failed.flag_id else None
        label = safe_line(flag.title) if flag else mask_numbers(failed.subject or "")
        until = at_label(failed.failed_at, today).split(" at ")[-1]
        failure = {"title": "An urgent email couldn't be sent." if failed.kind == "urgent"
                   else "The daily summary couldn't be sent.",
                   "line": f'"{label}" to {joined([names.get(i, "someone") for i in json.loads(failed.to_user_ids or "[]")])}, '
                           f'{day(local_day(failed.created_at))}. Tried {failed.tries} times until {until}; the mail '
                           f'server said: "{failed.last_error or ""}".'}
    return {"ready": mail_ready(request.app.state.mailer), "last_sent": last, "failure": failure}


def view(request: Request, db: Session, ctx: BookContext) -> dict:
    today = deps.today()
    name = parent_name(o.label for o in ctx.owners)
    people = members(request.app.state.books.directory, ctx.book.id)
    switches = prefs(db, people)
    known = active_known(db)
    adders = names_for(request.app.state.books.directory, [k.added_by for k in known])
    return {
        "large_cents": large_cents(db), "cash_alert_floor_cents": cash_floor_cents(db), "default_cash_floor_cents": V.DEFAULT_CASH_FLOOR_CENTS, "default_cents": V.DEFAULT_LARGE_CENTS, "floors": _floors(db, today),
        "known": [{"id": k.id, "payee": mask_numbers(k.payee_name), "range": range_text(k.low_cents, k.high_cents),
                   "added": f"{adders.get(k.added_by, 'Someone')}, {day(local_day(k.added_at))}, from "
                            f"{article(V.check_label(k.check, name))} {V.check_label(k.check, name)} flag",
                   "note": k.note} for k in known],
        "mail": _mail(request, db, ctx, today),
        "people": [{"user_id": m.user_id, "name": m.name, "role": m.role, "role_label": m.role.capitalize(),
                    "urgent": switches[m.user_id][0], "summary": switches[m.user_id][1],
                    "can_change": ctx.is_manager and (m.user_id == ctx.user_id or m.role == "viewer"),
                    "is_me": m.user_id == ctx.user_id} for m in people],
        "can_edit": ctx.is_manager,
    }


def _refused(e: FlagRefused):
    return bad(str(e), e.status)


@router.get("")
def settings(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return view(request, db, ctx)


@router.patch("/large")
@recorded
def set_large(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
              ctx: BookContext = Depends(open_book)):
    cents = body.get("cents")
    if isinstance(cents, bool) or not isinstance(cents, int) or not 100 <= cents <= 100_000_000:
        raise bad(LARGE_RULE)
    old = large_cents(db)
    if cents != old:
        set_state(db, LARGE, str(cents), deps.now())
        record(db, ctx, "watch.large", before={"large_cents": old}, after={"large_cents": cents}, note=body.get("note"))
    db.commit()
    return view(request, db, ctx)


@router.patch("/cash-floor")
@recorded
def set_cash_floor(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
                   ctx: BookContext = Depends(open_book)):
    cents = body.get("cents")
    if isinstance(cents, bool) or not isinstance(cents, int) or not 100 <= cents <= 100_000_000:
        raise bad(LARGE_RULE)
    old = cash_floor_cents(db)
    if cents != old:
        set_state(db, CASH_FLOOR, str(cents), deps.now())
        record(db, ctx, "watch.cash_floor", before={"cash_alert_floor_cents": old},
               after={"cash_alert_floor_cents": cents}, note=body.get("note"))
    db.commit()
    return view(request, db, ctx)


@router.put("/floors/{item_id}")
@recorded
def set_floor(item_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
              ctx: BookContext = Depends(open_book)):
    found = next(((i, d) for i, d in floored_items(db) if i.id == item_id), None)
    if found is None:
        raise bad(FLOOR_ITEM, 404 if db.get(InventoryItem, item_id) is None else 422)
    item, d = found
    cents = body.get("cents")
    if cents is not None and (isinstance(cents, bool) or not isinstance(cents, int) or not 0 <= cents <= 10**12):
        raise bad(FLOOR_AMOUNT)
    old, now = d.get("floor_cents"), deps.now()
    if cents != old:
        if cents is None:
            d.pop("floor_cents", None)
        else:
            d["floor_cents"] = cents
        item.details, item.updated_at, item.updated_by = json.dumps(d), now, ctx.user_id
        set_state(db, low_key(item.account_id), None, now)
        record(db, ctx, "watch.floor", target_id=item.id, item_id=item.id, before={"floor_cents": old},
               after={"floor_cents": cents}, note=body.get("note"))
        check_low(db, deps.today(), now, after="floor", account_id=item.account_id)       # ruling 11: a new floor is checked at once
    db.commit()
    return view(request, db, ctx)


@router.post("/known/{known_id}/remove")
@recorded
def remove(known_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    k = db.get(WatchKnown, known_id)
    if k is None:
        raise bad(NO_SUCH_KNOWN, 404)
    try:
        remove_known(db, ctx, k, body, deps.now())
    except FlagRefused as e:
        raise _refused(e) from None
    db.commit()
    return view(request, db, ctx)


@router.patch("/emails/{user_id}")
@recorded
def set_emails(user_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
               ctx: BookContext = Depends(open_book)):
    try:
        set_prefs(db, ctx, members(request.app.state.books.directory, ctx.book.id), user_id, body, deps.now())
    except FlagRefused as e:
        raise _refused(e) from None
    db.commit()
    return view(request, db, ctx)


@router.post("/emails/stop")
@viewer_ok
@recorded
def stop(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Viewers may call it (ruling 5): it only turns the caller's own emails off."""
    try:
        stop_mine(db, ctx, members(request.app.state.books.directory, ctx.book.id), deps.now())
    except FlagRefused as e:
        raise _refused(e) from None
    db.commit()
    return view(request, db, ctx)


@router.post("/test-email")
@not_recorded("A test email changes nothing in the book.")
def test_email(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    mailer = request.app.state.mailer
    if not mail_ready(mailer):
        raise bad(NOT_SET_UP, 409)
    me = next(m for m in members(request.app.state.books.directory, ctx.book.id) if m.user_id == ctx.user_id)
    body = (f"This is a test email from Steward for {ctx.book.name}. Urgent emails and the daily summary come from "
            f"this address.\n\nChange who gets them in Settings → Watching.")
    try:
        mailer.send(me.email, TEST_SUBJECT, body)
    except Exception as e:  # noqa: BLE001 - the server's reason is shown as is (README screen 5)
        raise bad(f'The mail server said: "{str(e)[:200]}"', 502) from None
    return {"sent_to": me.email}
