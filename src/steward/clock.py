"""Steward's one clock. Everything that needs the time asks here, through the module (`clock.now()`, never
`from steward.clock import now`), so a test freezes all of it with one patch (tests/conftest.py, fake_clock;
flaky-test audit S2). In the app it is exactly datetime.now(timezone.utc).

The household's time zone (spec 2026-11-05, section 7) is STEWARD_TIMEZONE; unset, the TZ variable when it names a
zone, else UTC. configure() sets it at app and CLI start; a script that never calls it reads the same variables
itself, once. Ask for it with household_tz() at the moment it's needed, never into a module-level name."""
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ZONE_RULE = "STEWARD_TIMEZONE must be a time zone name like America/Chicago or UTC; {name} isn't one."
_tz: ZoneInfo | None = None


def zone(name: str) -> ZoneInfo:
    """The zone a STEWARD_TIMEZONE names. ValueError, in plain words, for anything else."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(ZONE_RULE.format(name=name)) from None


def resolve(setting: str | None, tz_env: str | None) -> ZoneInfo:
    name = (setting or "").strip()
    if name:
        return zone(name)
    env = (tz_env or "").strip().lstrip(":")
    if env:
        try:
            return ZoneInfo(env)
        except (ZoneInfoNotFoundError, ValueError):
            pass        # a POSIX rule or a file path, not a zone name: as if TZ were unset
    return ZoneInfo("UTC")


def configure(setting: str | None) -> ZoneInfo:
    global _tz
    _tz = resolve(setting, os.environ.get("TZ"))
    return _tz


def reset() -> None:
    global _tz
    _tz = None


def household_tz() -> ZoneInfo:
    global _tz
    if _tz is None:
        _tz = resolve(os.environ.get("STEWARD_TIMEZONE"), os.environ.get("TZ"))
    return _tz


def now() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    """The household's date: now() in its time zone."""
    return now().astimezone(household_tz()).date()
