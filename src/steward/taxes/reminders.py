"""The quarterly taxes email (spec 7.1; ruling 11). Off by default: each person turns it on for themselves. Once per
due date per household book, at 7:00 AM household time on the first day of the Home window, or the first minute after it up
to the due date, while something is still due and withholding isn't missing. Three tries, 30 minutes apart, then one
book event. Recipients are re-checked against the book at each try; mail goes out outside any database transaction,
and one book's failure never stops the others. Amounts and dates only; never an account number."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from html import escape

from sqlalchemy.orm import Session

from steward.books.registry import BookInfo, BookRegistry
from steward import clock
from steward.engine.inputs import InputError
from steward.engine.tax.rules import RulesError
from steward.events import log_event, resolve_events_matching
from steward.inventory.present import log_safe
from steward.mail import mail_ready
from steward.taxes import store
from steward.taxes.household import NotReady
from steward.taxes.quarterly import NEVER, NextDue, Quarterly, agency_label, dollars, long_date, notice, quarterly, short_date
from steward.watch.outbox import addresses
from steward.watch.recipients import members

log = logging.getLogger("steward.taxes")
SEND_AT = time(7, 0)
TRIES = 3
RETRY = timedelta(minutes=30)
FAILED = "The quarterly taxes email couldn't be sent."
FOOT = "You get this email because you turned it on in Quarterly taxes. Turn it off there."
MUTED = "opacity:0.72;font-size:13px"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


def reminder_email(q: Quarterly, n: NextDue, *, book_name: str, slug: str, base_url: str) -> Email:
    when = f"{n.due:%A}, {long_date(n.due)}"
    rows = [(agency_label(a, q.state), dollars(c)) for a, c in (("federal", n.federal_cents), ("state", n.state_cents)) if c]
    link = f"{base_url.rstrip('/')}/b/{slug}/taxes"
    text = (f"QUARTERLY TAXES, {book_name.upper()}\n\nDue {when}\n\n" + "".join(f"{k}: {v}\n" for k, v in rows)
            + f"\n{NEVER}\n\nOpen Quarterly taxes:\n{link}\n\n{FOOT}\n")
    table = "".join(f"<tr><td style=\"{MUTED};padding:2px 16px 2px 0\">{escape(k)}</td><td><b>{escape(v)}</b></td></tr>"
                    for k, v in rows)
    html = ("<!doctype html><html><body style=\"margin:0;padding:24px;font-family:-apple-system,'Segoe UI',Roboto,"
            "Helvetica,Arial,sans-serif;line-height:1.5\"><div style=\"max-width:560px\">"
            f"<p style=\"{MUTED};letter-spacing:0.06em;text-transform:uppercase;font-weight:600\">{escape(book_name)} · "
            "Quarterly taxes</p>"
            f"<h1 style=\"font:400 22px/1.3 Georgia,serif;margin:0 0 16px\">Due {escape(when)}</h1>"
            f"<table style=\"border-collapse:collapse;font-size:15px\">{table}</table><p>{escape(NEVER)}</p>"
            f"<p><a href=\"{escape(link)}\" style=\"color:#6b3f73;font-weight:600\">Open Quarterly taxes</a></p>"
            f"<p style=\"{MUTED};border-top:1px solid rgba(128,128,128,0.35);padding-top:12px\">{escape(FOOT)}</p>"
            "</div></body></html>")
    return Email(f"{book_name}: quarterly taxes due {short_date(n.due)}", text, html)


def _blank_mark() -> dict:
    return {"status": "pending", "tries": 0, "sent_to": [], "next_try": None}


def remind_book(books: BookRegistry, book: BookInfo, mailer, settings, now: datetime) -> str:
    local = now.astimezone(clock.household_tz())
    today = local.date()
    if local.time() < SEND_AT or not mail_ready(mailer):
        return "idle"
    engine = books.engine_for(book)
    with Session(engine) as db:                         # a plain read: no write lock while the email is off (m3)
        if not store.email_users(db):
            return "idle"
    immediate = engine.execution_options(immediate=True)
    with Session(immediate) as db:
        wanted = store.email_users(db)
        if not wanted:
            return "idle"
        try:
            q = quarterly(db, today)
        except (NotReady, InputError, RulesError):
            return "idle"
        n = notice(q, today)
        if n is None:
            return "idle"
        mark = store.sent_mark(db, n.due) or _blank_mark()
        if mark["status"] != "pending" or (mark["next_try"] and datetime.fromisoformat(mark["next_try"]) > now):
            return "idle"
        in_book = {m.user_id for m in members(books.directory, book.id)}
        to = [u for u in wanted if u in in_book and u not in mark["sent_to"]]
        if not to:
            return "idle"
        mark = {**mark, "tries": mark["tries"] + 1, "next_try": (now + RETRY).isoformat()}
        store.put_sent_mark(db, n.due, mark, now)          # claimed before the mail server is contacted
        e = reminder_email(q, n, book_name=book.name, slug=book.slug, base_url=settings.base_url)
        db.commit()
    emails = addresses(books.directory, to)
    ok, failed = [], []
    for uid in to:
        if uid not in emails:
            continue
        try:
            mailer.send(emails[uid], e.subject, e.text, html=e.html)
            ok.append(uid)
        except Exception as ex:  # noqa: BLE001 - retried, then reported once
            log.error("The quarterly taxes email to user %s failed: %s", uid, log_safe(ex))
            failed.append(uid)
    with Session(immediate) as db:
        sent = sorted(set(mark["sent_to"]) | set(ok))
        if not failed:
            store.put_sent_mark(db, n.due, {**mark, "status": "sent", "sent_to": sent}, now)
            resolve_events_matching(db, "mail", FAILED, now)
        elif mark["tries"] >= TRIES:
            store.put_sent_mark(db, n.due, {**mark, "status": "failed", "sent_to": sent}, now)
            log_event(db, "error", "mail", f"{FAILED} It was for {long_date(n.due)}; Steward tried {TRIES} times.",
                      actionable=True)
        else:
            store.put_sent_mark(db, n.due, {**mark, "sent_to": sent}, now)
        db.commit()
    return f"{len(ok)} sent"


def reminders_tick(books: BookRegistry, mailer, settings, now: datetime) -> dict[str, str]:
    out: dict[str, str] = {}
    for book in books.books():
        if book.kind != "household":
            continue
        if book.id in books.unavailable:
            out[book.slug] = "unavailable"
            continue
        try:
            out[book.slug] = remind_book(books, book, mailer, settings, now)
        except Exception as e:  # noqa: BLE001 - one book must not stop the others
            log.error("The quarterly taxes email failed for book %s: %s", book.id, log_safe(e))
            out[book.slug] = "failed"
    return out
