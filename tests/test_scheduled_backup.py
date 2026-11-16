"""Steward's own daily backup (release spec 2026-11-05, section 7, "Backups on a schedule"; guided setup spec 1.3 and
3.3): the settings, the schedule, the run and its record."""
import json
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from steward.db.directory_models import DirectoryMeta
from steward.services import backup as bk
from steward.services import scheduled_backup as sb
from steward.services.scheduled_backup import BackupSchedule, backup_schedule
from steward.settings import BACKUP_AT_RULE, PING_URL_RULE, Settings

PING_ID = "f3b1c2d4-9e8a-4b7c-a6d5-0e1f2a3b4c5d"
PING = f"https://hc-ping.example/{PING_ID}"


def make(monkeypatch, tmp_path, **env) -> Settings:
    for k in ("STEWARD_BACKUP_AT", "STEWARD_BACKUP_DIR", "STEWARD_BACKUP_PING_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWARD_BASE_URL", "https://steward.example.com")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_settings_default_to_three_am_into_the_data_folder_with_no_ping(monkeypatch, tmp_path):
    s = make(monkeypatch, tmp_path)
    assert (s.backup_at, s.backup_dir, s.backup_ping_url) == ("03:00", None, "")
    assert "backup_at" not in s.model_fields_set
    assert s.backups_dir == tmp_path / "backups"
    assert backup_schedule(s) == BackupSchedule(at=time(3, 0), ping_url=None)


def test_an_empty_backup_at_is_set_and_turns_the_schedule_off(monkeypatch, tmp_path):
    """JR's NAS: STEWARD_BACKUP_AT= is present, so it is set (guided setup spec 4.3), and it is off."""
    s = make(monkeypatch, tmp_path, STEWARD_BACKUP_AT="")
    assert s.backup_at == "" and "backup_at" in s.model_fields_set
    assert backup_schedule(s).at is None


@pytest.mark.parametrize("given, kept", [("03:00", "03:00"), ("3:00", "03:00"), (" 07:30 ", "07:30"), ("23:59", "23:59"),
                                         ("0:05", "00:05")])
def test_backup_at_takes_a_24_hour_time(monkeypatch, tmp_path, given, kept):
    assert make(monkeypatch, tmp_path, STEWARD_BACKUP_AT=given).backup_at == kept


@pytest.mark.parametrize("bad", ["24:00", "3", "03:60", "3am", "03:00:00", "off", "٠٣:٠٠", "-1:00"])
def test_backup_at_refuses_anything_else(monkeypatch, tmp_path, bad):
    with pytest.raises(ValidationError, match="STEWARD_BACKUP_AT must be a time like 03:00"):
        make(monkeypatch, tmp_path, STEWARD_BACKUP_AT=bad)


def test_backup_dir_moves_every_backup_and_empty_is_unset(monkeypatch, tmp_path):
    assert make(monkeypatch, tmp_path, STEWARD_BACKUP_DIR="/backups").backups_dir == Path("/backups")
    assert make(monkeypatch, tmp_path, STEWARD_BACKUP_DIR="  ").backups_dir == tmp_path / "backups"


def test_a_good_ping_url_is_kept(monkeypatch, tmp_path):
    s = make(monkeypatch, tmp_path, STEWARD_BACKUP_PING_URL=PING)
    assert backup_schedule(s).ping_url == PING


@pytest.mark.parametrize("bad", [f"ftp://hc-ping.example/{PING_ID}", f"https://user:pw@hc-ping.example/{PING_ID}",
                                 f"hc-ping.example/{PING_ID}", f"https:///{PING_ID}", f"https://hc-ping.example/{PING_ID} x",
                                 f"https://hc-ping.example/{PING_ID}" + "a" * 500, f"https://hc-ping.example:99999/{PING_ID}"])
def test_a_bad_ping_url_is_refused_without_showing_it(monkeypatch, tmp_path, bad):
    with pytest.raises(ValidationError) as e:
        make(monkeypatch, tmp_path, STEWARD_BACKUP_PING_URL=bad)
    assert PING_URL_RULE in str(e.value) and PING_ID not in str(e.value)


LA, CHICAGO, UTC = ZoneInfo("America/Los_Angeles"), ZoneInfo("America/Chicago"), timezone.utc
THREE = time(3, 0)


def at(tz, *args):
    return datetime(*args, tzinfo=tz).astimezone(UTC)


class FakeHttp:
    def __init__(self, status=200, error=None):
        self.calls, self.status, self.error = [], status, error

    def get(self, url, timeout):
        self.calls.append(url)
        if self.error:
            raise self.error
        return type("R", (), {"status_code": self.status})()


@pytest.mark.parametrize("now, since, expected", [
    (at(LA, 2026, 10, 30, 2, 59), at(LA, 2026, 10, 29, 3, 0), False),   # before today's time
    (at(LA, 2026, 10, 30, 3, 0), at(LA, 2026, 10, 29, 3, 0), True),     # at it
    (at(LA, 2026, 10, 30, 9, 0), at(LA, 2026, 10, 29, 3, 0), True),     # the box was off at 3: once, on return
    (at(LA, 2026, 10, 30, 3, 1), at(LA, 2026, 10, 30, 3, 0), False),    # already ran today
    (at(LA, 2026, 10, 30, 9, 0), at(LA, 2026, 10, 27, 3, 0), True),     # off for days: one run, not three
    (at(LA, 2026, 10, 30, 11, 0), at(LA, 2026, 10, 30, 10, 0), False),  # no record: started after today's 3:00
    (at(LA, 2026, 10, 31, 3, 0), at(LA, 2026, 10, 30, 10, 0), True),    # ...so the first copy is the next 3:00
])
def test_due(now, since, expected):
    assert sb.due(now, THREE, LA, since) is expected


@pytest.mark.parametrize("day, hhmm", [((2027, 3, 14), time(2, 30)),    # spring forward: 2:30 doesn't exist
                                       ((2026, 11, 1), time(1, 30))])   # fall back: 1:30 happens twice
def test_due_runs_exactly_once_on_a_daylight_saving_day(day, hhmm):
    since = at(CHICAGO, *day, 0, 0) - timedelta(hours=20)            # the day before's run
    tick, runs = at(CHICAGO, *day, 0, 0), 0
    for _ in range(24 * 60):        # 24 hours of ticks from local midnight: all of a 23- or 25-hour day, none of the next's time
        if sb.due(tick, hhmm, CHICAGO, since):
            runs, since = runs + 1, tick
        tick += timedelta(minutes=1)
    assert runs == 1


@pytest.fixture
def stamps(monkeypatch):
    n = iter(range(1000))
    monkeypatch.setattr(bk, "_stamp", lambda: f"20261030-0300{next(n):02d}")


def run(books, http, *, when=at(LA, 2026, 10, 30, 3, 0), started=at(LA, 2026, 10, 29, 12, 0), **update):
    s = books.settings.model_copy(update={"backup_at": "03:00", "backup_ping_url": "", **update})
    return sb.backup_tick(books, http, s, when, started)


def test_a_due_tick_backs_up_records_and_pings(books, stamps):
    http = FakeHttp()
    rec = run(books, http, backup_ping_url=PING)
    assert rec == {"at": at(LA, 2026, 10, 30, 3, 0).isoformat(), "ok": True, "why": None, "ping_ok": True}
    assert http.calls == [PING]
    assert sb.read_last(books.directory) == rec
    assert any(p.name.startswith("steward-directory-") for p in books.settings.backups_dir.iterdir())


def test_the_next_tick_the_same_day_does_nothing(books, stamps):
    http = FakeHttp()
    run(books, http, backup_ping_url=PING)
    assert run(books, http, when=at(LA, 2026, 10, 30, 3, 1), backup_ping_url=PING) is None
    assert http.calls == [PING]


@pytest.mark.parametrize("url", [PING, PING + "/"])
def test_a_failed_backup_records_why_and_pings_fail(books, monkeypatch, url):
    monkeypatch.setattr(bk, "backup_all", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")))
    http = FakeHttp()
    rec = run(books, http, backup_ping_url=url)
    assert (rec["ok"], rec["why"], rec["ping_ok"]) == (False, sb.WHY_DISK, True)
    assert http.calls == [PING.rstrip("/") + "/fail"]


def test_a_skipped_book_counts_as_a_failure(books, monkeypatch):
    monkeypatch.setattr(bk, "backup_all", lambda *a, **k: ([], ["Skipped mom: The book's file is missing."]))
    rec = run(books, FakeHttp())
    assert (rec["ok"], rec["why"], rec["ping_ok"]) == (False, sb.WHY_SKIPPED, None)


@pytest.mark.parametrize("http", [FakeHttp(status=500), FakeHttp(error=httpx2.ConnectError("down")),
                                  FakeHttp(error=UnicodeError("odd url"))])
def test_a_ping_that_fails_is_recorded_and_never_logged(books, stamps, caplog, http):
    caplog.set_level(logging.DEBUG)
    rec = run(books, http, backup_ping_url=PING)
    assert rec["ok"] is True and rec["ping_ok"] is False
    assert PING_ID not in caplog.text and PING_ID not in json.dumps(rec)


def test_off_never_backs_up_or_pings(books):
    http = FakeHttp()
    assert run(books, http, backup_at="", backup_ping_url=PING) is None
    assert http.calls == [] and sb.read_last(books.directory) is None


def test_the_scheduled_backup_never_holds_the_key(books, stamps):
    run(books, FakeHttp())
    key = books.settings.key_path.read_bytes().strip()
    for p in books.settings.backups_dir.rglob("*"):
        assert p.name != books.settings.key_path.name
        assert not p.is_file() or key not in p.read_bytes()
    rec = run(books, FakeHttp(), when=at(LA, 2026, 10, 31, 3, 0), backup_dir=books.settings.data_dir)
    assert (rec["ok"], rec["why"]) == (False, sb.WHY_FOLDER)
    assert not list(books.settings.data_dir.glob("steward-directory-*.db"))


def test_a_broken_record_reads_as_none_and_the_start_time_counts(books, stamps):
    with Session(books.directory) as s:
        s.add(DirectoryMeta(key=sb.LAST_KEY, value="not json"))
        s.commit()
    assert sb.read_last(books.directory) is None
    assert run(books, FakeHttp(), started=at(LA, 2026, 10, 30, 4, 0)) is None     # started after today's 3:00


GOOD_AT = "2026-10-30T03:00:00+00:00"


@pytest.mark.parametrize("record", [
    {"at": "x", "ok": True, "why": None, "ping_ok": None},                  # not a time
    {"at": "2026-10-30T03:00:00", "ok": True, "why": None, "ping_ok": None},  # naive
    {"at": GOOD_AT, "ok": "yes", "why": None, "ping_ok": None},
    {"at": GOOD_AT, "ok": True, "why": 3, "ping_ok": None},
    {"at": GOOD_AT, "ok": True, "why": None, "ping_ok": 1},
    {"at": GOOD_AT, "ok": True, "why": None},                               # a key short
    [1, 2],
])
def test_a_record_that_is_not_a_record_reads_as_none(books, record):
    with Session(books.directory) as s:
        s.add(DirectoryMeta(key=sb.LAST_KEY, value=json.dumps(record)))
        s.commit()
    assert sb.read_last(books.directory) is None


def test_backup_line_says_when_and_where_never_the_url(settings):
    assert sb.backup_line(settings.model_copy(update={"backup_at": ""})) == "Backups: off"
    on = settings.model_copy(update={"backup_at": "03:00", "backup_ping_url": PING})
    assert sb.backup_line(on) == f"Backups: daily at 03:00 to {settings.backups_dir}, with a ping"
    assert sb.backup_line(settings) == f"Backups: daily at 03:00 to {settings.backups_dir}"


def test_the_watcher_runs_the_backup_tick_and_survives_its_failure(client, monkeypatch):
    seen = []

    def boom(books, http, settings, now, started, store=None):
        seen.append((books, settings))
        raise RuntimeError("no")
    monkeypatch.setattr(sb, "backup_tick", boom)
    client.app.state.watch_job()                  # logs, never raises
    assert seen == [(client.app.state.books, client.app.state.settings)]
