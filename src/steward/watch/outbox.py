"""The durable outbox (spec 4.3 and 8; ruling 18). Urgent flags queue a row when they are raised (store.add_flag); the
summary queues one at 7:00 AM (queue_summary). The first try fixes the recipients and renders the message; each try
reads addresses from the directory. Three tries, 30 minutes apart; then the row fails, one book event is logged
without names (spec 2.2), and each flag's History says who didn't get it. Without SMTP, rows are skipped quietly."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from steward.books.registry import BookInfo
from steward.db.directory_models import User
from steward.db.models import Flag, MailOutbox, WatchRecipient
from steward.events import log_event, resolve_events_matching
from steward.inventory.present import at_label, clean_account, mask_numbers, parent_name, scrub_text
from steward.watch import vocab as V
from steward.watch.checks import day
from steward.watch.emails import still_line, summary_email, urgent_email
from steward.watch.recipients import members, summary_to, urgent_to
from steward.watch.store import add_event, facts_of, large_cents
from steward.watch.views import account_label, email_facts, local_day, scrub

FAILED_PREFIX = {"urgent": "An urgent email couldn't be sent.", "summary": "The daily summary couldn't be sent."}
NOT_SET_UP = "Email isn't set up."
NOBODY = "Nobody gets these emails."


@dataclass(frozen=True)
class Sender:
    book: BookInfo
    directory: Engine
    base_url: str
    ready: bool


def queue_summary(db: Session, today: date, now: datetime) -> MailOutbox | None:
    """Decision 8: the normal flags raised since the last summary that aren't Done yet; nothing on a day with none."""
    new = list(db.scalars(select(Flag).where(Flag.severity == "normal", Flag.summarized_at.is_(None))
                          .order_by(Flag.created_at, Flag.id)))
    for f in new:
        f.summarized_at = now
    listed = [f.id for f in new if f.status in V.NOT_DONE]
    row = None
    if listed:
        row = MailOutbox(kind="summary", flag_ids=json.dumps(listed), status="pending", created_at=now,
                         next_try_at=now, tries=0, sent_to="[]")
        db.add(row)
    db.flush()
    return row


def due_rows(db: Session, now: datetime) -> list[MailOutbox]:
    return list(db.scalars(select(MailOutbox).where(MailOutbox.status == "pending", MailOutbox.next_try_at <= now)
                           .order_by(MailOutbox.id)))


def _flag_ids(row: MailOutbox) -> list[int]:
    return json.loads(row.flag_ids or "[]") or ([row.flag_id] if row.flag_id else [])


GONE = "no longer in the book"
SWITCHED_OFF = "turned these emails off"
NOW_VIEWER = "is now a viewer"
UNPREPARED = "The email couldn't be put together."
scrub_error = scrub_text


def _recheck(db: Session, row: MailOutbox, people: list, now: datetime) -> list[int]:
    """Security: before every try, each stored recipient who hasn't been sent this yet must still be in the book and
    still get this kind of email. Anyone who isn't is dropped from the row, and each flag's History says who and why.
    Returns the ids still to send to."""
    allowed = {m.user_id for m in (urgent_to(db, people) if row.kind == "urgent" else summary_to(db, people))}
    present = {m.user_id for m in people}
    stored = json.loads(row.to_user_ids or "[]")
    sent = set(json.loads(row.sent_to or "[]"))
    chosen = {r.user_id for r in db.scalars(select(WatchRecipient))}
    role = {m.user_id: m.role for m in people}
    dropped = {GONE: [], SWITCHED_OFF: [], NOW_VIEWER: []}
    for uid in stored:
        if uid not in sent and uid not in allowed:
            if uid not in present:
                dropped[GONE].append(uid)
            elif role[uid] == "viewer" and uid not in chosen:      # a manager who became a viewer never opted in
                dropped[NOW_VIEWER].append(uid)
            else:
                dropped[SWITCHED_OFF].append(uid)
    gone = {u for ids in dropped.values() for u in ids}
    if gone:
        row.to_user_ids = json.dumps([u for u in stored if u not in gone])
        for reason, ids in dropped.items():
            for fid in _flag_ids(row):
                if ids:
                    add_event(db, fid, "email_failed", now, user_ids=ids, detail={"kind": row.kind, "error": reason})
    return [u for u in json.loads(row.to_user_ids or "[]") if u not in sent]


def prepare(db: Session, row: MailOutbox, s: Sender, today: date, now: datetime) -> bool:
    """False when the row won't be sent (no SMTP, nobody to send to). Every try, the first included, re-checks the
    recipients against the book as it is now."""
    if not s.ready:
        row.status, row.last_error = "skipped", NOT_SET_UP
        return False
    people = members(s.directory, s.book.id)
    if row.to_user_ids is not None:
        if not _recheck(db, row, people, now):
            sent = json.loads(row.sent_to or "[]")
            if sent:
                row.status, row.sent_at, row.last_error = "sent", now, None
                kind = "emailed" if row.kind == "urgent" else "summary"
                for fid in _flag_ids(row):
                    add_event(db, fid, kind, now, user_ids=sent)
                for prefix in FAILED_PREFIX.values():
                    resolve_events_matching(db, "mail", prefix, now)
            else:
                row.status, row.last_error = "skipped", NOBODY
            return False
        return True
    to = urgent_to(db, people) if row.kind == "urgent" else summary_to(db, people)
    if not to:
        row.status, row.last_error = "skipped", NOBODY
        return False
    name = parent_name(o.label for o in s.book.owner_names)
    common = {"book_name": s.book.name, "slug": s.book.slug, "base_url": s.base_url, "name": name}
    if row.kind == "urgent":
        f = db.get(Flag, row.flag_id)
        e = urgent_email(f, email_facts(db, f), large_cents=large_cents(db), account=account_label(db, f), **common)
    else:
        ids = _flag_ids(row)
        flags = [f for f in (db.get(Flag, i) for i in ids) if f is not None]
        not_done = list(db.scalars(select(Flag).where(Flag.status.in_(V.NOT_DONE))))
        e = summary_email(flags, today=today, still=still_line(not_done, set(ids)),
                          accounts={x.id: account_label(db, x) for x in flags}, **common)
    row.to_user_ids = json.dumps([m.user_id for m in to])
    row.subject, row.text_body, row.html_body = e.subject, e.text, e.html
    return True


def addresses(directory: Engine, ids) -> dict[int, str]:
    wanted = set(ids)
    if not wanted:
        return {}
    with Session(directory) as s:
        return dict(s.execute(select(User.id, User.email).where(User.id.in_(wanted))).all())


def deliver(mailer, to_ids: list[int], sent_ids: list[int], subject: str, text: str, html: str | None,
            emails: dict[int, str]) -> tuple[list[int], list[int], str | None]:
    ok, failed, error = [], [], None
    for uid in to_ids:
        if uid in sent_ids or uid not in emails:
            continue
        try:
            mailer.send(emails[uid], subject, text, html=html)
            ok.append(uid)
        except Exception as e:  # noqa: BLE001 - any mail failure is retried, then reported (spec 8)
            failed.append(uid)
            error = scrub_error((str(e) or type(e).__name__)[:200])
    return ok, failed, error


def claim(row: MailOutbox, now: datetime) -> None:
    """Before the mail server is contacted: count the try and push the next one back, so a crash or a failed commit
    after sending can never cause an immediate re-send. after_try finishes the job."""
    row.tries += 1
    row.next_try_at = now + timedelta(minutes=V.RETRY_MINUTES)


def fail_unprepared(db: Session, row: MailOutbox, now: datetime) -> None:
    """A row whose email can't be rendered: failed, with one book event and no names or addresses."""
    row.status, row.failed_at, row.last_error = "failed", now, UNPREPARED
    flag = db.get(Flag, row.flag_id) if row.kind == "urgent" and row.flag_id else None
    label = scrub(flag.title, facts_of(flag)) if flag is not None else "daily summary"
    log_event(db, "error", "mail", f'{FAILED_PREFIX[row.kind]} "{label}", {day(local_day(row.created_at))}. '
                                   f"{UNPREPARED} Steward will not try again.", actionable=True)
    for fid in _flag_ids(row):
        add_event(db, fid, "email_failed", now, user_ids=json.loads(row.to_user_ids or "[]"),
                  detail={"kind": row.kind, "error": UNPREPARED})
    db.flush()


def after_try(db: Session, row: MailOutbox, ok: list[int], failed: list[int], error: str | None, now: datetime) -> None:
    """Finish a try that claim() counted."""
    sent = sorted(set(json.loads(row.sent_to or "[]")) | set(ok))
    row.sent_to = json.dumps(sent)
    flag_ids = _flag_ids(row)
    kind = "emailed" if row.kind == "urgent" else "summary"
    if not failed and not sent:      # everyone left had no address on file: nothing went out, so say nothing did
        row.status, row.last_error = "skipped", NOBODY
        return
    if not failed:
        row.status, row.sent_at, row.last_error = "sent", now, None
        for fid in flag_ids:
            add_event(db, fid, kind, now, user_ids=sent)
        for prefix in FAILED_PREFIX.values():
            resolve_events_matching(db, "mail", prefix, now)
        return
    row.last_error = scrub_error(error)
    if row.tries < V.TRIES:
        row.next_try_at = now + timedelta(minutes=V.RETRY_MINUTES)
        return
    row.status, row.failed_at = "failed", now
    flag = db.get(Flag, row.flag_id) if row.kind == "urgent" and row.flag_id else None
    label = scrub(flag.title, facts_of(flag)) if flag is not None else mask_numbers(row.subject or "")
    until = at_label(now, local_day(now)).split(" at ")[-1]
    log_event(db, "error", "mail", f'{FAILED_PREFIX[row.kind]} "{label}", {day(local_day(row.created_at))}. Tried '
                                   f'{row.tries} times until {until}; the mail server said: "{scrub_error(error)}".', actionable=True)
    for fid in flag_ids:
        if sent:
            add_event(db, fid, kind, now, user_ids=sent)
        add_event(db, fid, "email_failed", now, user_ids=failed, detail={"kind": row.kind, "error": scrub_error(error)})
    db.flush()
