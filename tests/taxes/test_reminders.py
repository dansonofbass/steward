"""The quarterly taxes email (ruling 11): off by default; once per due date at 7:00 AM Pacific on the first day of the
window, to those who turned it on; three tries, then one event."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import EventLog
from steward.mail import FakeMailer
from steward.taxes import reminders, store
from steward.taxes.reminders import FAILED, reminders_tick
from tests.factories import make_person
from tests.taxes.helpers import AT, household

SEVEN = datetime(2027, 1, 1, 15, 0, tzinfo=timezone.utc)      # 7:00 AM Pacific (UTC-8) on January 1, 2027
DUE = date(2027, 1, 15)


class BoomMailer(FakeMailer):
    def send(self, to, subject, body, html=None):
        raise OSError("connection refused")


def _setup(db, ddb, ours, on=("jr",), salary="0"):
    people = {name: make_person(ddb, name, [(ours.id, "manager")]) for name in ("jr", "sam")}
    household(db, profit_cents=15_000_000, salary=salary)
    for name in on:
        store.set_email(db, people[name].id, True, AT)
    db.commit()
    return people


def test_off_by_default_nothing_is_sent(books, settings, db, ddb, ours):
    _setup(db, ddb, ours, on=())
    mailer = FakeMailer()
    assert reminders_tick(books, mailer, settings, SEVEN) == {"ours": "idle"}
    assert mailer.sent == []


def test_once_at_seven_on_the_first_day_to_those_who_turned_it_on(books, settings, db, ddb, ours):
    _setup(db, ddb, ours)
    mailer = FakeMailer()
    assert reminders_tick(books, mailer, settings, SEVEN - timedelta(minutes=1)) == {"ours": "idle"}   # 6:59
    assert reminders_tick(books, mailer, settings, SEVEN - timedelta(days=1)) == {"ours": "idle"}      # December 31
    assert reminders_tick(books, mailer, settings, SEVEN) == {"ours": "1 sent"}
    assert [to for to, _, _ in mailer.sent] == ["jr@x.com"]
    _, subject, body = mailer.sent[0]
    assert subject == f"{ours.name}: quarterly taxes due January 15"
    assert "Due Friday, January 15, 2027" in body and "Federal (IRS): $" in body and "California (FTB): $" in body
    assert "Steward never pays or files anything." in body and "https://nas.tail1234.ts.net/b/ours/taxes" in body
    assert mailer.html[0] is not None and "January 15, 2027" in mailer.html[0]
    assert reminders_tick(books, mailer, settings, SEVEN + timedelta(hours=2)) == {"ours": "idle"}
    assert reminders_tick(books, mailer, settings, SEVEN + timedelta(days=3)) == {"ours": "idle"}
    assert len(mailer.sent) == 1


def test_a_late_start_still_sends_once_inside_the_window(books, settings, db, ddb, ours):
    _setup(db, ddb, ours)
    mailer = FakeMailer()
    assert reminders_tick(books, mailer, settings, SEVEN + timedelta(days=5)) == {"ours": "1 sent"}
    assert reminders_tick(books, mailer, settings, SEVEN + timedelta(days=15)) == {"ours": "idle"}    # past the due date
    assert len(mailer.sent) == 1


def test_missing_withholding_or_mail_holds_it(books, settings, db, ddb, ours):
    _setup(db, ddb, ours, salary="16500000")                  # wages and no withholding entered (ruling 4)
    mailer = FakeMailer()
    assert reminders_tick(books, mailer, settings, SEVEN) == {"ours": "idle"} and mailer.sent == []
    assert reminders_tick(books, FakeMailer(configured=False), settings, SEVEN) == {"ours": "idle"}


def test_someone_not_in_the_book_never_gets_it(books, settings, db, ddb, ours):
    _setup(db, ddb, ours, on=())
    store.set_email(db, 999, True, AT)
    db.commit()
    mailer = FakeMailer()
    reminders_tick(books, mailer, settings, SEVEN)
    assert mailer.sent == []


def test_three_tries_then_one_event(books, settings, db, ddb, ours):
    _setup(db, ddb, ours)
    boom = BoomMailer()
    for minutes in (0, 10, 30, 60, 90):
        reminders_tick(books, boom, settings, SEVEN + timedelta(minutes=minutes))
    with Session(books.engine_for(ours)) as s:
        mark = store.sent_mark(s, DUE)
        assert (mark["status"], mark["tries"]) == ("failed", 3)
        events = list(s.scalars(select(EventLog).where(EventLog.kind == "mail")))
        assert len(events) == 1 and events[0].message.startswith(FAILED) and events[0].actionable


def test_no_write_lock_unless_someone_turned_the_email_on(books, settings, db, ddb, ours, monkeypatch):
    # final review m3: the tick runs every minute from 7:00 AM; with the email off everywhere it only reads
    opened = []

    class Spy(Session):
        def __init__(self, bind=None, **kw):
            opened.append(bool(bind.get_execution_options().get("immediate")))
            super().__init__(bind, **kw)

    monkeypatch.setattr(reminders, "Session", Spy)
    people = _setup(db, ddb, ours, on=())
    assert reminders_tick(books, FakeMailer(), settings, SEVEN) == {"ours": "idle"}
    assert opened and not any(opened)
    store.set_email(db, people["jr"].id, True, AT)
    db.commit()
    opened.clear()
    assert reminders_tick(books, FakeMailer(), settings, SEVEN) == {"ours": "1 sent"}
    assert any(opened)


def test_parent_books_are_skipped(books, settings, margaret):
    out = reminders_tick(books, FakeMailer(), settings, SEVEN)
    assert "margaret-ellis" not in out
