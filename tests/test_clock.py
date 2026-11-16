"""Steward's one clock (flaky-test audit S2): every module reads it, and one patch moves all of them."""
from datetime import date, datetime, timedelta, timezone

import pytest

from steward import clock, deps
from tests.conftest import DEFAULT_NOW, FROZEN_NOW


def test_the_household_date_is_pacific(fake_clock):
    fake_clock.set(datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc))        # 11 pm on the 13th in Los Angeles
    assert clock.today() == deps.today() == date(2026, 10, 13)


def test_every_reader_sees_the_test_clock(fake_clock):
    """One patch reaches deps.now, a module that imported `now` by name from steward.deps, and the models' default."""
    from steward.api import events                   # from steward.deps import ..., now, ...
    from steward.db.models import utcnow
    at = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)
    fake_clock.set(at)
    assert clock.now() == deps.now() == events.now() == utcnow() == at
    assert clock.today() == deps.today() == date(2026, 11, 2)


def test_the_default_clock_starts_at_default_now_and_keeps_order(fake_clock):
    """Unfrozen tests still see time move forward (rows written one after another sort as written), but the date
    never turns mid-run."""
    first, second = clock.now(), clock.now()
    assert first == DEFAULT_NOW and first < second < first + timedelta(seconds=1)
    assert clock.today() == date(2026, 10, 30)


def test_frozen_pins_the_clock_without_ticking(frozen):
    assert clock.now() == clock.now() == FROZEN_NOW and deps.today() == date(2026, 10, 13)


def test_advance_moves_the_date(frozen, fake_clock):
    fake_clock.advance(timedelta(days=20))
    assert clock.today() == date(2026, 11, 2)


@pytest.mark.real_clock
def test_real_clock_opts_out(fake_clock):
    assert fake_clock is None
    before = datetime.now(timezone.utc)
    assert before <= clock.now() <= datetime.now(timezone.utc)


from pathlib import Path
from zoneinfo import ZoneInfo


def test_the_zone_is_the_setting_then_tz_then_utc():
    assert str(clock.resolve("America/Chicago", "Europe/Paris")) == "America/Chicago"
    assert clock.resolve("", "Europe/Paris").key == "Europe/Paris"
    assert clock.resolve(None, ":Europe/Paris").key == "Europe/Paris"
    assert clock.resolve("  ", "").key == "UTC" and clock.resolve(None, None).key == "UTC"


def test_a_tz_that_names_no_zone_is_utc():
    assert clock.resolve(None, "EST5EDT,M3.2.0,M11.1.0").key == "UTC"
    assert clock.resolve(None, "/etc/localtime").key == "UTC"


def test_a_setting_that_names_no_zone_is_refused_in_plain_words():
    with pytest.raises(ValueError, match="STEWARD_TIMEZONE must be a time zone name like America/Chicago or UTC"):
        clock.resolve("Pacific", None)


def test_configure_moves_the_household_date(fake_clock):
    fake_clock.set(datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc))
    clock.configure("UTC")
    assert clock.today() == deps.today() == date(2026, 10, 14)
    clock.configure("America/Los_Angeles")
    assert clock.today() == date(2026, 10, 13)


def test_unconfigured_it_reads_the_environment_once(monkeypatch):
    clock.reset()
    monkeypatch.setenv("STEWARD_TIMEZONE", "Asia/Tokyo")
    assert clock.household_tz() == ZoneInfo("Asia/Tokyo")
    monkeypatch.setenv("STEWARD_TIMEZONE", "UTC")
    assert clock.household_tz() == ZoneInfo("Asia/Tokyo")


def test_no_module_keeps_its_own_zone():
    root = Path(__file__).resolve().parents[1] / "src" / "steward"
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if "HOUSEHOLD_TZ" in p.read_text() or "America/Los_Angeles" in p.read_text()]
    assert hits == []
