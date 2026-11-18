"""Time zone and gateway name at runtime (guided setup spec 4.3)."""
import logging

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from steward import clock, gateway_name
from steward.app import create_app
from steward.db.directory_models import AppSetting
from tests.factories import login, make_person


def no_tz_env(settings, monkeypatch):
    monkeypatch.delenv("STEWARD_TIMEZONE")
    monkeypatch.delenv("TZ", raising=False)        # the default is then UTC on every machine
    from steward.settings import Settings
    return Settings(_env_file=None)


def test_a_time_zone_save_moves_the_clock_and_clears_plan_caches(settings, books, ddb, ours, monkeypatch):
    s = no_tz_env(settings, monkeypatch)
    make_person(ddb, "pat", [(ours.id, "manager")])
    cache = books.plan_cache(ours.id)
    cache.results.put("k", "v")
    with TestClient(create_app(s, books), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "pat")
        r = c.put("/api/install/settings/general", json={"timezone": "America/Chicago"})
        assert r.json()["general"]["timezone"]["running"] == "America/Chicago"
        assert str(clock.household_tz()) == "America/Chicago" and cache.results.get("k") is None
        assert c.get("/api/auth/me").json()["timezone"] == "America/Chicago"     # issue #26: the web's today follows


def test_the_saved_zone_and_name_apply_at_the_next_start_and_reach_me(settings, books, ddb, ours, monkeypatch):
    s = no_tz_env(settings, monkeypatch)
    make_person(ddb, "pat", [(ours.id, "manager")])
    with TestClient(create_app(s, books), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "pat")
        c.put("/api/install/settings/general", json={"timezone": "America/Chicago", "gateway_name": "Den PC"})
    clock.reset(); gateway_name.reset()
    with TestClient(create_app(s, books), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "pat")
        assert str(clock.household_tz()) == "America/Chicago"
        assert c.get("/api/auth/me").json()["gateway_name"] == "Den PC"


def test_a_stored_zone_that_is_no_zone_falls_back(settings, books, monkeypatch, caplog):
    s = no_tz_env(settings, monkeypatch)
    with Session(books.directory) as d:
        d.add(AppSetting(key="general.timezone", value="Gone/Zone")); d.commit()
    caplog.set_level(logging.WARNING)
    with TestClient(create_app(s, books), base_url="https://nas.tail1234.ts.net"):
        assert clock.household_tz().key == "UTC"
    assert "The saved time zone isn't one Steward knows" in caplog.text
