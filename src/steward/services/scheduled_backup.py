"""Steward's own daily backup (release spec 2026-11-05, section 7, "Backups on a schedule"; guided setup spec 1.3 and
3.3): when it runs, where it pings, the run and its record. PR A of the guided setup spec routes `backup_schedule`
through `effective()`; nothing else reads the backup settings for the schedule."""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, TypedDict
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from steward import clock
from steward.db.directory_models import DirectoryMeta
from steward.db.engine import WRITE
from steward.inventory.present import log_safe
from steward.services import backup
from steward.settings import Settings

if TYPE_CHECKING:
    from steward.app_settings import AppSettings

log = logging.getLogger("steward.backup")

LAST_KEY = "backup.last"
WHY_FOLDER, WHY_DISK, WHY_SKIPPED, WHY_FAILED = "bad folder", "disk error", "books skipped", "failed"


@dataclass(frozen=True)
class BackupSchedule:
    at: time | None          # None: the built-in backup is off
    ping_url: str | None     # None: nothing to ping


class BackupRecord(TypedDict):
    at: str
    ok: bool
    why: str | None
    ping_ok: bool | None


def backup_schedule(settings: Settings, store: "AppSettings | None" = None) -> BackupSchedule:
    """With a store, the effective time and ping (env, then the app, then the default); without, Settings alone."""
    if store is None:
        at, ping_url = settings.backup_at, settings.backup_ping_url
    else:
        at, ping_url = store.value("backup.at"), store.secret("backup.ping_url")
    return BackupSchedule(at=time.fromisoformat(at) if at else None, ping_url=ping_url or None)


def due(now: datetime, at: time, tz: ZoneInfo, since: datetime) -> bool:
    """True when the latest scheduled moment at or before now came after since (the last run, or the watcher's
    start). Compared in UTC. On a spring-forward day a time that doesn't exist (2:30) is read in standard time, so it
    runs once, at 3:30 daylight time; on a fall-back day a repeated time runs once, at its first occurrence. A missed
    night runs once when the box is back."""
    day = now.astimezone(tz).date()
    moment = datetime.combine(day, at, tzinfo=tz).astimezone(timezone.utc)
    if moment > now:
        moment = datetime.combine(day - timedelta(days=1), at, tzinfo=tz).astimezone(timezone.utc)
    return moment > since


def _is_record(d: object) -> bool:
    if not isinstance(d, dict) or set(d) != {"at", "ok", "why", "ping_ok"}:
        return False
    try:
        when = datetime.fromisoformat(d["at"])
    except (TypeError, ValueError):
        return False
    return (when.tzinfo is not None and isinstance(d["ok"], bool) and (d["why"] is None or isinstance(d["why"], str))
            and (d["ping_ok"] is None or isinstance(d["ping_ok"], bool)))


def read_last(directory: Engine) -> BackupRecord | None:
    with Session(directory) as s:
        row = s.get(DirectoryMeta, LAST_KEY)
        value = row.value if row else None
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if _is_record(parsed) else None


def write_last(directory: Engine, record: BackupRecord) -> None:
    with Session(directory.execution_options(**WRITE)) as s:
        s.merge(DirectoryMeta(key=LAST_KEY, value=json.dumps(record, separators=(",", ":"))))
        s.commit()


def ping(http, url: str, ok: bool) -> bool:
    """One GET to the user's monitor: the URL on success, the URL plus /fail on failure. Never logs the URL."""
    target = url if ok else url.rstrip("/") + "/fail"
    try:
        good = 200 <= http.get(target, timeout=10).status_code < 300
    except Exception:  # noqa: BLE001 - after the backup ran: a strange URL must not stop the record being written
        good = False
    if not good:
        log.warning("The backup ping didn't go through.")
    return good


def backup_tick(books, http, settings: Settings, now: datetime, started: datetime,
                store: "AppSettings | None" = None) -> BackupRecord | None:
    sched = backup_schedule(settings, store)
    if sched.at is None:
        return None
    last = read_last(books.directory)
    since = datetime.fromisoformat(last["at"]) if last else started
    if not due(now, sched.at, clock.household_tz(), since):
        return None
    why: str | None = None
    written: list = []
    try:
        written, skipped = backup.backup_all(books, settings.backups_dir.resolve())
        if skipped:
            why = WHY_SKIPPED
    except ValueError:
        why = WHY_FOLDER
    except OSError:
        why = WHY_DISK
    except Exception as e:  # noqa: BLE001 - the record says it failed; the log says what kind
        why = WHY_FAILED
        log.warning("The scheduled backup hit %s.", log_safe(e))
    ok = why is None
    ping_ok = ping(http, sched.ping_url, ok) if sched.ping_url else None
    record: BackupRecord = {"at": now.isoformat(), "ok": ok, "why": why, "ping_ok": ping_ok}
    write_last(books.directory, record)
    if ok:
        log.info("The scheduled backup wrote %d copies.", len(written))
    else:
        log.warning("The scheduled backup failed: %s.", why)
    return record


def backup_line(settings: Settings, store: "AppSettings | None" = None) -> str:
    sched = backup_schedule(settings, store)
    if sched.at is None:
        return "Backups: off"
    return (f"Backups: daily at {sched.at.strftime('%H:%M')} to {settings.backups_dir}"
            + (", with a ping" if sched.ping_url else ""))
