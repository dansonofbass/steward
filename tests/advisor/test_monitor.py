from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.advisor.monitor import AdvisorMonitor, crosscheck
from steward.advisor.outgoing import record_payload
from steward.db.directory_models import DirectoryEvent
from steward.db.models import EventLog
from steward_boundary.canonical import canonical, sha256_hex
from tests.advisor.stubs import StubGateway

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)      # 4:00 AM Pacific


def test_a_hash_no_book_recorded_reaches_home_and_the_directory_once(books, ours, engine):
    kept = {"text": "How much is in savings?"}
    with Session(engine) as db:
        record_payload(db, user_id=1, conversation_id=1, turn_id="t_0000000000000001", seq=1, channel="chat",
                       part="question", payload=kept, now=NOW - timedelta(hours=3))
        db.commit()
    gw = StubGateway()
    gw.sent_since = lambda since: {"sent": [
        {"at": (NOW - timedelta(hours=3)).isoformat(), "sha256": sha256_hex(kept), "bytes": len(canonical(kept)),
         "book_id": ours.id, "channel": "chat"},
        {"at": "2026-10-20T09:12:00+00:00", "sha256": "f" * 64, "bytes": 99, "book_id": ours.id, "channel": "chat"},
        {"at": "2026-10-20T09:13:00+00:00", "sha256": "e" * 64, "bytes": 99, "book_id": None, "channel": "check"}]}
    assert crosscheck(books, gw, NOW) == 1
    assert crosscheck(books, gw, NOW) == 1
    assert crosscheck(books, gw, NOW + timedelta(days=1)) == 1      # the next night's look-back sees it again
    with Session(engine) as db:
        events = list(db.scalars(select(EventLog).where(EventLog.kind == "chat")))
    assert [(e.message, e.actionable) for e in events] == [
        ("Steward found something sent to Claude that isn't in the log, sent Oct 20, 2026 at 2:12 AM (ref ffffffff).",
         True)]
    with Session(books.directory) as ddb:
        msgs = list(ddb.scalars(select(DirectoryEvent.message).where(DirectoryEvent.kind == "chat")))
    assert len(msgs) == 1 and msgs[0].startswith("Steward found something sent to Claude that isn't in the log")


def test_fresh_reuses_a_recent_answer_and_tick_crosschecks_once_a_day(books):
    calls = []
    gw = StubGateway()
    gw.sent_since = lambda since: calls.append(since) or {"sent": []}
    clock = [NOW - timedelta(hours=2)]                              # 2:00 AM Pacific
    m = AdvisorMonitor(gw, books, now=lambda: clock[0])
    assert m.fresh(10)["key_set"] is True
    gw._health = {"key_set": False}
    assert m.fresh(10)["key_set"] is True                           # within 10 seconds: the same answer
    m.tick()
    assert calls == []                                              # before 3:30 AM
    clock[0] = NOW
    m.tick()
    m.tick()
    assert len(calls) == 1 and m.health == {"key_set": False}


def test_a_cross_check_gateway_slept_through_runs_at_the_next_tick(books):
    """The day is marked checked only after a check that worked (final review, finding 9)."""
    from steward.advisor.gateway import GatewayUnavailable
    calls, asleep = [], [True]

    def sent_since(since):
        calls.append(since)
        if asleep[0]:
            raise GatewayUnavailable()
        return {"sent": []}
    gw = StubGateway()
    gw.sent_since = sent_since
    m = AdvisorMonitor(gw, books, now=lambda: NOW)
    m.tick()                                                        # the gateway is asleep: nothing is marked
    assert len(calls) == 1 and m.checked_on is None
    asleep[0] = False
    m.tick()                                                        # awake a minute later: the check runs
    assert len(calls) == 2 and m.checked_on == NOW.date()
    m.tick()
    assert len(calls) == 2                                          # and only once that day


def test_away_is_remembered_as_none(books):
    m = AdvisorMonitor(StubGateway(away=True), books, now=lambda: NOW)
    assert m.poll() is None and m.last_ok is None


def test_away_for_counts_from_the_last_answer_or_the_start(books):
    from datetime import datetime, timedelta, timezone
    from steward.advisor.monitor import AdvisorMonitor
    from tests.advisor.stubs import StubGateway
    t0 = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
    clock = [t0]
    m = AdvisorMonitor(StubGateway(away=True), books, now=lambda: clock[0])
    clock[0] = t0 + timedelta(minutes=12)
    m.poll()
    assert m.away_for(clock[0]) == timedelta(minutes=12)
    m.client.away = False
    m.poll()
    assert m.away_for(clock[0]) == timedelta(0)
