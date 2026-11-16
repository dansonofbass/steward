"""The outbox and the minute tick (spec 4.3 and 8; decisions 4 and 8; rulings 17 and 18). Urgent within 15 minutes;
the summary at 7:00 AM Pacific with nothing on a day with none; 3 tries over an hour that survive a restart, then a
book event; the household time zone across midnight and DST (Nov 1, 2026 and Mar 14, 2027)."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import delete, update

from steward.books.registry import open_books
from steward.db.directory_models import Membership
from steward.db.models import WatchRecipient
from tests.factories import make_person
from steward.db.directory_models import User
from steward.db.models import EventLog, Flag, FlagEvent, MailOutbox, Transaction
from steward.mail import FakeMailer
from steward.watch.store import DAILY_ON, SUMMARY_ON, add_flag, get_state
from steward.watch.tick import watch_tick
from tests.watch_helpers import NOW, account, history, txn

TICK = NOW + timedelta(minutes=1)          # 6:13 AM Pacific, before the 6:30 run


class BoomMailer(FakeMailer):
    def send(self, to, subject, body, html=None):
        raise RuntimeError("535 authentication failed")


def _urgent(books, margaret, at=NOW, title="$500.00 gift card at CVS Pharmacy", account_name="Joint checking"):
    with Session(books.engine_for(margaret)) as db:
        f = add_flag(db, check="scam", severity="urgent", summary=title, title=title, now=at, after="sync",
                     facts={"amount_cents": 50_000, "payee": "CVS Pharmacy", "account": account_name,
                            "posted_at": "2026-10-17", "kind": "gift_card"})
        db.commit()
        return f.id


def _normal(books, margaret, n, at=NOW):
    ids = []
    with Session(books.engine_for(margaret)) as db:
        for i in range(n):
            f = add_flag(db, check="monthly", severity="normal", summary=f"StreamBox, $15.{i}9 on Sep 18 and Oct 18",
                         title="StreamBox", now=at, after="sync",
                         facts={"amount_cents": 1599, "account": "Citi card", "payee": "StreamBox"})
            ids.append(f.id)
        db.commit()
    return ids


def _db(books, margaret) -> Session:
    return Session(books.engine_for(margaret))


def _jr(ddb) -> int:
    return ddb.scalar(select(User.id).where(User.username == "jr"))


def test_an_urgent_flag_is_emailed_on_the_next_tick(margaret, books, settings, ddb):
    fid = _urgent(books, margaret)
    mailer = FakeMailer()
    assert watch_tick(books, mailer, settings, TICK) == {"margaret-ellis": "1 tried"}
    [(to, subject, body)] = mailer.sent
    assert (to, subject) == ("jr@x.com", "Urgent, Margaret Ellis: $500.00 gift card at CVS Pharmacy")
    assert f"https://nas.tail1234.ts.net/b/margaret-ellis/look-into/{fid}" in body and mailer.html[0]
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, row.tries, json.loads(row.sent_to)) == ("sent", 1, [_jr(ddb)])
        event = db.scalar(select(FlagEvent).where(FlagEvent.kind == "emailed"))
        assert json.loads(event.user_ids) == [_jr(ddb)]
    assert watch_tick(books, mailer, settings, TICK + timedelta(minutes=1)) == {"margaret-ellis": "idle"}
    assert len(mailer.sent) == 1


def test_three_tries_over_an_hour_survive_a_restart(margaret, books, settings, ddb):
    fid = _urgent(books, margaret)
    boom = BoomMailer()
    watch_tick(books, boom, settings, TICK)
    watch_tick(books, boom, settings, TICK + timedelta(minutes=10))       # not due yet
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, row.tries, row.next_try_at) == ("pending", 1, TICK + timedelta(minutes=30))
    books.dispose()
    again = open_books(settings)                                          # Steward restarted
    try:
        watch_tick(again, boom, settings, TICK + timedelta(minutes=30))
        watch_tick(again, boom, settings, TICK + timedelta(minutes=60))
        with _db(again, margaret) as db:
            row = db.scalar(select(MailOutbox))
            assert (row.status, row.tries, row.last_error) == ("failed", 3, "535 authentication failed")
            assert db.get(Flag, fid).status == "open"
            [event] = db.scalars(select(EventLog).where(EventLog.kind == "mail")).all()
            assert (event.level, event.actionable, event.message) == (
                "error", True, 'An urgent email couldn\'t be sent. "$500.00 gift card at CVS Pharmacy", Oct 19. Tried 3 '
                               'times until 7:13 AM; the mail server said: "535 authentication failed".')
            failed = db.scalar(select(FlagEvent).where(FlagEvent.kind == "email_failed"))
            assert json.loads(failed.user_ids) == [_jr(ddb)]
            assert json.loads(failed.detail) == {"kind": "urgent", "error": "535 authentication failed"}
        _urgent(again, margaret, at=TICK + timedelta(hours=2), title="$1,200.00 by Zelle to J. Smith")
        watch_tick(again, FakeMailer(), settings, TICK + timedelta(hours=2, minutes=1))
        with _db(again, margaret) as db:
            assert db.scalar(select(EventLog.resolved_at).where(EventLog.kind == "mail")) is not None
    finally:
        again.dispose()


def test_the_daily_summary_lists_the_new_normal_flags_at_seven(margaret, books, settings):
    a, b, c = _normal(books, margaret, 3)
    with _db(books, margaret) as db:
        db.get(Flag, c).status = "expected"                 # marked before 7: not listed
        db.commit()
    mailer = FakeMailer()
    six_59 = datetime(2026, 10, 19, 13, 59, tzinfo=timezone.utc)
    watch_tick(books, mailer, settings, six_59)
    assert mailer.sent == []
    watch_tick(books, mailer, settings, six_59 + timedelta(minutes=1))
    [(to, subject, body)] = mailer.sent
    assert subject == "Margaret Ellis: 2 new to look into, Mon Oct 19"
    assert body.count("- New monthly charge: StreamBox") == 2
    with _db(books, margaret) as db:
        assert all(db.get(Flag, i).summarized_at is not None for i in (a, b, c))
        assert db.scalars(select(FlagEvent).where(FlagEvent.kind == "summary")).all() != []
    watch_tick(books, mailer, settings, six_59 + timedelta(hours=3))
    watch_tick(books, mailer, settings, six_59 + timedelta(days=1, minutes=1))   # Tuesday: nothing new
    assert len(mailer.sent) == 1


def test_the_morning_runs_follow_pacific_time_across_midnight_and_dst(margaret, books, settings):
    def ticks(*utc):
        for t in utc:
            watch_tick(books, FakeMailer(), settings, t)
        with _db(books, margaret) as db:
            return get_state(db, DAILY_ON), get_state(db, SUMMARY_ON)

    utc = timezone.utc
    # 11:30 PM Pacific on Oct 19 is 06:30 UTC on Oct 20: still the Pacific day Oct 19
    assert ticks(datetime(2026, 10, 20, 6, 30, tzinfo=utc)) == ("2026-10-19", "2026-10-19")
    assert ticks(datetime(2026, 10, 20, 7, 5, tzinfo=utc)) == ("2026-10-19", "2026-10-19")      # 12:05 AM Oct 20
    # Nov 1, 2026: clocks fall back; 7:00 AM PST is 15:00 UTC
    assert ticks(datetime(2026, 11, 1, 14, 30, tzinfo=utc)) == ("2026-11-01", "2026-10-19")     # 6:30 AM PST
    assert ticks(datetime(2026, 11, 1, 14, 59, tzinfo=utc)) == ("2026-11-01", "2026-10-19")
    assert ticks(datetime(2026, 11, 1, 15, 0, tzinfo=utc)) == ("2026-11-01", "2026-11-01")
    # Mar 14, 2027: clocks spring forward; 7:00 AM PDT is 14:00 UTC
    assert ticks(datetime(2027, 3, 14, 13, 59, tzinfo=utc)) == ("2027-03-14", "2026-11-01")
    assert ticks(datetime(2027, 3, 14, 14, 0, tzinfo=utc)) == ("2027-03-14", "2027-03-14")


def test_mail_that_isnt_set_up_is_skipped_quietly(margaret, books, settings):
    fid = _urgent(books, margaret)
    mailer = FakeMailer(configured=False)
    watch_tick(books, mailer, settings, TICK)
    assert mailer.sent == []
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, row.last_error) == ("skipped", "Email isn't set up.")
        assert db.scalars(select(EventLog).where(EventLog.kind == "mail")).all() == []
        assert db.get(Flag, fid).status == "open"


def test_the_morning_run_checks_transactions_nothing_else_has_checked(margaret, books, settings):
    """A typed-in transaction (or any write that didn't come through a sync or an import) is looked at at 6:30."""
    with _db(books, margaret) as db:
        acct = account(db)
        history(db, acct)
        t = txn(db, acct, 1, -150_000, "WALK-IN REPAIR SHOP", merchant="Walk-in Repair Shop")
        tid = t.id
    watch_tick(books, FakeMailer(), settings, NOW - timedelta(minutes=1))          # 6:11 AM: before the morning run
    with _db(books, margaret) as db:
        assert db.scalars(select(Flag)).all() == [] and db.get(Transaction, tid).watched_at is None
    watch_tick(books, FakeMailer(), settings, datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc))    # 6:30 AM
    with _db(books, margaret) as db:
        assert db.get(Transaction, tid).watched_at is not None
        [f] = db.scalars(select(Flag)).all()
        assert (f.transaction_id, f.check) == (tid, "large")


def test_household_books_are_left_alone(margaret, books, settings):
    assert set(watch_tick(books, FakeMailer(), settings, TICK)) == {"margaret-ellis"}


def test_the_watch_scheduler_runs_outside_tests(settings, books):
    from steward.app import create_app
    prod = settings.model_copy(update={"env": "prod"})
    assert create_app(prod, books, mailer=FakeMailer()).state.watcher is not None
    assert create_app(settings, books).state.watcher is None


# Security: every try re-checks each stored recipient against the book's current members and their switch.
def _two_managers(books, ddb, margaret):
    ddb.rollback()
    sam = make_person(ddb, "sam", [(margaret.id, "manager")])
    return sam.id


def _first_try_fails(books, margaret, settings):
    fid = _urgent(books, margaret)
    watch_tick(books, BoomMailer(), settings, TICK)
    with _db(books, margaret) as db:
        assert db.scalar(select(MailOutbox)).tries == 1
    return fid


def test_a_member_removed_before_the_retry_gets_nothing(margaret, books, settings, ddb):
    sam = _two_managers(books, ddb, margaret)
    fid = _first_try_fails(books, margaret, settings)
    ddb.rollback()
    ddb.execute(delete(Membership).where(Membership.user_id == sam, Membership.book_id == margaret.id))
    ddb.commit()
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK + timedelta(minutes=30))
    assert [to for to, _, _ in mailer.sent] == ["jr@x.com"]
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, json.loads(row.sent_to), json.loads(row.to_user_ids)) == ("sent", [_jr(ddb)], [_jr(ddb)])
        dropped = db.scalar(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "email_failed",
                                                    FlagEvent.user_ids == json.dumps([sam])))
        assert json.loads(dropped.detail)["error"] == "no longer in the book"


def test_someone_who_turns_urgent_off_before_the_retry_gets_nothing(margaret, books, settings, ddb):
    sam = _two_managers(books, ddb, margaret)
    fid = _first_try_fails(books, margaret, settings)
    with _db(books, margaret) as db:
        db.add(WatchRecipient(user_id=sam, urgent=False, summary=True, updated_at=TICK, updated_by=sam))
        db.commit()
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK + timedelta(minutes=30))
    assert [to for to, _, _ in mailer.sent] == ["jr@x.com"]
    with _db(books, margaret) as db:
        dropped = db.scalar(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "email_failed",
                                                    FlagEvent.user_ids == json.dumps([sam])))
        assert json.loads(dropped.detail)["error"] == "turned these emails off"


def test_everyone_still_allowed_gets_the_retry(margaret, books, settings, ddb):
    sam = _two_managers(books, ddb, margaret)
    _first_try_fails(books, margaret, settings)
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK + timedelta(minutes=30))
    assert sorted(to for to, _, _ in mailer.sent) == ["jr@x.com", "sam@x.com"]
    with _db(books, margaret) as db:
        assert db.scalars(select(FlagEvent).where(FlagEvent.kind == "email_failed")).all() == []


def test_nobody_left_on_the_retry_finishes_the_row(margaret, books, settings, ddb):
    _first_try_fails(books, margaret, settings)
    with _db(books, margaret) as db:
        db.add(WatchRecipient(user_id=_jr(ddb), urgent=False, summary=True, updated_at=TICK, updated_by=1))
        db.commit()
    ddb.rollback()
    ddb.execute(delete(Membership).where(Membership.user_id == _jr(ddb), Membership.book_id == margaret.id))
    ddb.commit()
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK + timedelta(minutes=30))
    assert mailer.sent == []
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, row.last_error) == ("skipped", "Nobody gets these emails.")


class _FailFor(FakeMailer):
    def __init__(self, bad):
        super().__init__()
        self.bad = bad

    def send(self, to, subject, body, html=None):
        if to == self.bad:
            raise RuntimeError("451 try later")
        super().send(to, subject, body, html=html)


def test_partly_sent_then_the_rest_dropped_still_records_who_got_it(margaret, books, settings, ddb):
    sam = _two_managers(books, ddb, margaret)
    fid = _urgent(books, margaret)
    first = _FailFor("sam@x.com")
    watch_tick(books, first, settings, TICK)
    assert [to for to, _, _ in first.sent] == ["jr@x.com"]
    ddb.rollback()
    ddb.execute(delete(Membership).where(Membership.user_id == sam, Membership.book_id == margaret.id))
    ddb.commit()
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK + timedelta(minutes=30))
    assert mailer.sent == []
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, json.loads(row.sent_to)) == ("sent", [_jr(ddb)])
        emailed = db.scalar(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "emailed"))
        assert json.loads(emailed.user_ids) == [_jr(ddb)]
        dropped = db.scalar(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "email_failed"))
        assert json.loads(dropped.user_ids) == [sam]


# Final review: one bad email, double sends, addresses and numbers in book events.
def test_one_email_that_cannot_be_rendered_fails_alone(margaret, books, settings, ddb, monkeypatch):
    bad = _urgent(books, margaret, title="BAD one")
    good = _urgent(books, margaret, title="Good one")
    from steward.watch import outbox
    real = outbox.urgent_email

    def picky(f, *a, **kw):
        if f.id == bad:
            raise ValueError("odd facts")
        return real(f, *a, **kw)

    monkeypatch.setattr(outbox, "urgent_email", picky)
    mailer = FakeMailer()
    at = NOW + timedelta(minutes=30)              # 6:42 AM: the morning run is due as well
    assert watch_tick(books, mailer, settings, at) == {"margaret-ellis": "1 tried"}
    assert [subject for _, subject, _ in mailer.sent] == ["Urgent, Margaret Ellis: Good one"]
    with _db(books, margaret) as db:
        assert get_state(db, DAILY_ON) == "2026-10-19"
        rows = {r.flag_id: r for r in db.scalars(select(MailOutbox))}
        assert (rows[bad].status, rows[good].status) == ("failed", "sent")
        [event] = db.scalars(select(EventLog).where(EventLog.kind == "mail")).all()
        assert event.actionable and 'BAD one' in event.message
        assert db.scalar(select(FlagEvent).where(FlagEvent.flag_id == bad, FlagEvent.kind == "email_failed"))
    assert watch_tick(books, mailer, settings, at + timedelta(minutes=1)) == {"margaret-ellis": "idle"}


def test_a_failed_commit_after_sending_never_resends_at_once(margaret, books, settings, ddb, monkeypatch):
    _urgent(books, margaret)
    mailer = FakeMailer()
    from steward.watch import tick

    def broken(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(tick, "after_try", broken)
    assert watch_tick(books, mailer, settings, TICK) == {"margaret-ellis": "failed"}
    assert len(mailer.sent) == 1
    monkeypatch.undo()
    for minutes in (2, 3, 20):
        watch_tick(books, mailer, settings, TICK + timedelta(minutes=minutes))
    assert len(mailer.sent) == 1                    # claimed before sending: next try is 30 minutes away
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, row.tries, row.next_try_at) == ("pending", 1, TICK + timedelta(minutes=30))


class _AddressMailer(FakeMailer):
    def send(self, to, subject, body, html=None):
        raise RuntimeError(f"550 5.1.1 <{to}> user unknown; see postmaster@mail.example.com")


def test_failed_send_events_hold_no_addresses_or_account_numbers(margaret, books, settings, ddb):
    fid = _urgent(books, margaret, title="Checking123456789 is low", account_name="Checking123456789")
    boom = _AddressMailer()
    for minutes in (0, 30, 60):
        watch_tick(books, boom, settings, TICK + timedelta(minutes=minutes))
    with _db(books, margaret) as db:
        [event] = db.scalars(select(EventLog).where(EventLog.kind == "mail")).all()
        failed = db.scalar(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "email_failed"))
        row = db.scalar(select(MailOutbox))
        for text in (event.message, failed.detail, row.last_error):
            assert "@" not in text and "123456789" not in text
        assert "user unknown" in event.message


def test_a_manager_who_became_a_viewer_is_dropped_with_the_right_reason(margaret, books, settings, ddb):
    sam = _two_managers(books, ddb, margaret)
    fid = _first_try_fails(books, margaret, settings)
    ddb.rollback()
    ddb.execute(update(Membership).where(Membership.user_id == sam, Membership.book_id == margaret.id)
                .values(role="viewer"))
    ddb.commit()
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK + timedelta(minutes=30))
    assert [to for to, _, _ in mailer.sent] == ["jr@x.com"]
    with _db(books, margaret) as db:
        dropped = db.scalar(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "email_failed",
                                                    FlagEvent.user_ids == json.dumps([sam])))
        assert json.loads(dropped.detail)["error"] == "is now a viewer"


class _SmtpMailer(FakeMailer):
    def send(self, to, subject, body, html=None):
        raise RuntimeError(f"550 5.1.1 RCPT TO:<{to}> refused; 5.7.1 sam@y.org blocked; acct 4929 3813 7264 5019")


def _leaks(text) -> bool:
    bare = re.sub(r"[ .\-]", "", text or "")
    return "@" in (text or "") or "4929381372645019"[:5] in bare or "3813" in bare


def test_nothing_the_tick_writes_holds_an_address_or_a_grouped_number(margaret, books, settings, ddb, caplog):
    fid = _urgent(books, margaret, title="Visa 4929 3813 7264 5019 is odd", account_name="Visa 4929 3813 7264 5019")
    caplog.set_level(logging.DEBUG)
    for minutes in (0, 30, 60):
        watch_tick(books, _SmtpMailer(), settings, TICK + timedelta(minutes=minutes))
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        events = [e.message for e in db.scalars(select(EventLog))]
        details = [fe.detail or "" for fe in db.scalars(select(FlagEvent))]
    assert row.status == "failed" and "refused" in row.last_error
    for text in (row.last_error, *events, *details, caplog.text):
        assert not _leaks(text), text


def test_a_crash_in_the_tick_logs_no_traceback_address_or_number(margaret, books, settings, ddb, caplog, monkeypatch):
    _urgent(books, margaret)
    from steward.watch import tick

    def broken(*a, **kw):
        raise RuntimeError("database said <jr@x.com> Subject: Payee Alice 4929 3813 7264 5019")

    monkeypatch.setattr(tick, "after_try", broken)
    monkeypatch.setattr(tick, "prepare", lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad jr@x.com 4929 3813 7264 5019")))
    caplog.set_level(logging.DEBUG)
    watch_tick(books, FakeMailer(), settings, NOW + timedelta(minutes=30))
    assert "ValueError" in caplog.text and not _leaks(caplog.text)
    assert all(r.exc_info is None for r in caplog.records)


def test_a_brief_database_lock_while_preparing_leaves_the_row_to_try_again(margaret, books, settings, ddb, monkeypatch):
    import sqlcipher3
    from sqlalchemy.exc import OperationalError
    from steward.watch import tick
    _urgent(books, margaret)
    real, calls = tick.prepare, []

    def locked_once(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("UPDATE mail_outbox", {}, sqlcipher3.OperationalError("database is locked"))
        return real(*a, **kw)

    monkeypatch.setattr(tick, "prepare", locked_once)
    mailer = FakeMailer()
    assert watch_tick(books, mailer, settings, TICK) == {"margaret-ellis": "idle"}
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert (row.status, row.tries, row.last_error) == ("pending", 0, None)
        assert row.next_try_at == TICK + timedelta(minutes=2)
        assert not db.scalars(select(EventLog).where(EventLog.kind == "mail")).all()
    assert mailer.sent == []
    assert watch_tick(books, mailer, settings, TICK + timedelta(minutes=2)) == {"margaret-ellis": "1 tried"}
    assert len(mailer.sent) == 1


def test_an_operational_error_that_is_not_a_lock_fails_the_row_at_once(margaret, books, settings, ddb, monkeypatch):
    import sqlcipher3
    from sqlalchemy.exc import OperationalError
    from steward.watch import tick
    _urgent(books, margaret)

    def broken(*a, **kw):
        raise OperationalError("SELECT", {}, sqlcipher3.OperationalError("no such table: flag"))

    monkeypatch.setattr(tick, "prepare", broken)
    watch_tick(books, FakeMailer(), settings, TICK)
    with _db(books, margaret) as db:
        assert db.scalar(select(MailOutbox)).status == "failed"


def _locking(monkeypatch, state):
    import sqlcipher3
    from sqlalchemy.exc import OperationalError
    from steward.watch import tick
    real = tick.prepare

    def maybe(*a, **kw):
        if state["locked"]:
            raise OperationalError("UPDATE", {}, sqlcipher3.OperationalError("database is locked"))
        return real(*a, **kw)

    monkeypatch.setattr(tick, "prepare", maybe)


def _status(books, margaret):
    with _db(books, margaret) as db:
        return db.scalar(select(MailOutbox))


def test_a_lock_streak_over_thirty_minutes_fails_the_row_with_its_event(margaret, books, settings, ddb, monkeypatch):
    _urgent(books, margaret)
    _locking(monkeypatch, {"locked": True})
    for minutes in (1, 20):
        watch_tick(books, FakeMailer(), settings, NOW + timedelta(minutes=minutes))
        assert _status(books, margaret).status == "pending"
    watch_tick(books, FakeMailer(), settings, NOW + timedelta(minutes=40))
    row = _status(books, margaret)
    assert row.status == "failed"
    with _db(books, margaret) as db:
        assert db.scalars(select(EventLog).where(EventLog.kind == "mail")).all()


def test_a_brief_lock_during_the_third_try_does_not_fail_the_row(margaret, books, settings, ddb, monkeypatch):
    _urgent(books, margaret)
    with _db(books, margaret) as db:
        db.execute(update(MailOutbox).values(tries=2, next_try_at=NOW + timedelta(minutes=60)))
        db.commit()
    state = {"locked": True}
    _locking(monkeypatch, state)
    watch_tick(books, FakeMailer(), settings, NOW + timedelta(minutes=70))     # created 70 minutes ago
    assert _status(books, margaret).status == "pending"
    state["locked"] = False
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, NOW + timedelta(minutes=73))
    assert len(mailer.sent) == 1 and _status(books, margaret).status == "sent"


def test_a_successful_prepare_resets_the_lock_streak(margaret, books, settings, ddb, monkeypatch):
    _urgent(books, margaret)
    state = {"locked": True}
    _locking(monkeypatch, state)
    watch_tick(books, FakeMailer(), settings, NOW + timedelta(minutes=1))
    assert _status(books, margaret).locked_since is not None
    state["locked"] = False
    watch_tick(books, BoomMailer(), settings, NOW + timedelta(minutes=5))      # prepares, the send fails
    row = _status(books, margaret)
    assert (row.status, row.tries, row.locked_since) == ("pending", 1, None)
    state["locked"] = True
    watch_tick(books, FakeMailer(), settings, NOW + timedelta(minutes=45))     # a new streak, not the old one
    assert _status(books, margaret).status == "pending"


def test_a_recipient_with_no_address_leaves_the_row_skipped_and_writes_no_emailed_line(
        margaret, books, settings, ddb, monkeypatch):
    fid = _urgent(books, margaret)
    monkeypatch.setattr("steward.watch.tick.addresses", lambda directory, ids: {})
    mailer = FakeMailer()
    watch_tick(books, mailer, settings, TICK)
    assert mailer.sent == []
    with _db(books, margaret) as db:
        row = db.scalar(select(MailOutbox))
        assert row.status != "sent"
        assert (row.status, row.last_error) == ("skipped", "Nobody gets these emails.")
        assert db.scalars(select(FlagEvent).where(FlagEvent.flag_id == fid, FlagEvent.kind == "emailed")).all() == []


def test_a_claim_that_fails_once_for_another_reason_is_tried_again_before_the_row_fails(
        margaret, books, settings, ddb, monkeypatch):
    from steward.watch import tick
    _urgent(books, margaret)
    real, calls = tick.prepare, []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("something cleared a moment later")
        return real(*a, **kw)

    monkeypatch.setattr(tick, "prepare", flaky)
    mailer = FakeMailer()
    assert watch_tick(books, mailer, settings, TICK) == {"margaret-ellis": "1 tried"}
    assert len(mailer.sent) == 1 and _status(books, margaret).status == "sent"
