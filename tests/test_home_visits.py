"""Visits (Home spec P27-P29, P33): a full look and a glance are kept per person and only move later; a glance today
never moves `from`, the same glance does on the next household day; a last look over 35 days ago reads as the last
35 days; a refetch's ?from= is used only within the last 35 days; POST /home/seen refuses an old or future mark, is a
viewer's own, and two people never see each other's marks."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from steward.db.directory_models import User
from steward.db.models import HomeVisit
from steward.services import home_since as hs
from tests.factories import login, make_person

NOW = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)          # noon on Friday 2026-10-30 in the household's zone
HOUR = timedelta(hours=1)


def _visit(db, user_id: int, seen=None, glanced=None) -> None:
    db.add(HomeVisit(user_id=user_id, seen_at=seen, glanced_at=glanced))
    db.commit()


def test_no_row_is_a_first_visit(db):
    assert hs.last_look(db, 1, NOW) is None


def test_a_glance_today_alone_reads_as_a_first_visit(db):
    hs.save_look(db, 1, NOW - HOUR, glance=True, now=NOW)
    db.commit()
    assert hs.last_look(db, 1, NOW) is None


def test_the_same_glance_moves_from_the_next_household_day(db):
    hs.save_look(db, 1, NOW - HOUR, glance=True, now=NOW)
    db.commit()
    assert hs.last_look(db, 1, NOW + timedelta(days=1)) == hs.Look(NOW - HOUR, False)


def test_a_late_night_glance_is_yesterday_by_the_households_day(db):
    late = datetime(2026, 10, 30, 6, 30, tzinfo=timezone.utc)      # 11:30 pm on Oct 29 in California; Oct 30 in UTC
    morning = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)   # 8 am on Oct 30 in California
    _visit(db, 1, glanced=late)
    assert hs.last_look(db, 1, morning) == hs.Look(late, False)
    assert hs.household_day(late).isoformat() == "2026-10-29"


def test_a_full_look_counts_the_same_day(db):
    hs.save_look(db, 1, NOW - HOUR, glance=False, now=NOW)
    db.commit()
    assert hs.last_look(db, 1, NOW) == hs.Look(NOW - HOUR, False)


def test_from_is_the_later_of_the_full_look_and_an_earlier_days_glance(db):
    _visit(db, 1, seen=NOW - timedelta(days=3), glanced=NOW - timedelta(days=1))
    assert hs.last_look(db, 1, NOW) == hs.Look(NOW - timedelta(days=1), False)


def test_marks_only_move_later(db):
    hs.save_look(db, 1, NOW - HOUR, glance=False, now=NOW)
    hs.save_look(db, 1, NOW - 2 * HOUR, glance=False, now=NOW)
    hs.save_look(db, 1, NOW - 3 * HOUR, glance=True, now=NOW)
    hs.save_look(db, 1, NOW - 4 * HOUR, glance=True, now=NOW)
    db.commit()
    v = db.get(HomeVisit, 1)
    assert (v.seen_at, v.glanced_at) == (NOW - HOUR, NOW - 3 * HOUR)


def test_a_look_over_35_days_ago_covers_the_last_35_days(db):
    _visit(db, 1, seen=NOW - timedelta(days=36))
    assert hs.last_look(db, 1, NOW) == hs.Look(NOW - timedelta(days=35), True)


def test_a_refetch_from_is_used_within_35_days_and_ignored_otherwise(db):
    _visit(db, 1, seen=NOW - timedelta(days=3))
    own = hs.Look(NOW - timedelta(days=3), False)
    assert hs.last_look(db, 1, NOW, NOW - timedelta(days=5)) == hs.Look(NOW - timedelta(days=5), False)
    assert hs.last_look(db, 1, NOW, NOW - timedelta(days=40)) == own
    assert hs.last_look(db, 1, NOW, NOW + HOUR) == own


def test_a_refetch_from_on_a_first_visit_is_ignored(db):
    assert hs.last_look(db, 1, NOW, NOW - timedelta(days=2)) is None


def test_save_refuses_a_mark_older_than_a_day_or_in_the_future(db):
    for mark in (NOW - timedelta(days=1, seconds=1), NOW + timedelta(seconds=1)):
        with pytest.raises(hs.LookRefused) as e:
            hs.save_look(db, 1, mark, glance=False, now=NOW)
        assert e.value.message == "That visit is too old."
    hs.save_look(db, 1, NOW - timedelta(days=1), glance=False, now=NOW)         # exactly a day: kept


def _id(ddb, username: str) -> int:
    return ddb.scalar(select(User.id).where(User.username == username))


def test_post_seen_saves_my_look_and_never_anyone_elses(client, db, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "sam", [(ours.id, "manager")])
    mark = datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)
    login(client, "jr")
    r = client.post("/api/b/ours/home/seen", json={"mark": mark.isoformat(), "glance": False})
    assert r.status_code == 204 and r.content == b""
    login(client, "sam")
    assert client.post("/api/b/ours/home/seen", json={"mark": mark.isoformat(), "glance": True}).status_code == 204
    db.expire_all()
    jr, sam = db.get(HomeVisit, _id(ddb, "jr")), db.get(HomeVisit, _id(ddb, "sam"))
    assert (jr.seen_at, jr.glanced_at) == (mark, None)
    assert (sam.seen_at, sam.glanced_at) == (None, mark)


def test_post_seen_refuses_old_future_and_odd_bodies(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    post = lambda body: client.post("/api/b/ours/home/seen", json=body)   # noqa: E731
    for mark in ("2026-10-28T19:00:00+00:00", "2026-10-31T19:00:00+00:00"):
        r = post({"mark": mark, "glance": False})
        assert (r.status_code, r.json()) == (422, {"error": "That visit is too old."})
    for body in ({"mark": "2026-10-30T18:00:00+00:00"}, {"mark": 12, "glance": False}, {"mark": "last tuesday", "glance": True},
                 {"mark": "2026-10-30T18:00:00", "glance": True}, {"mark": "2026-10-30T18:00:00+00:00", "glance": "yes"}):
        r = post(body)
        assert (r.status_code, r.json()) == (422, {"error": "That request wasn't understood."}), body


def test_a_viewer_saves_their_own_look(client, db, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    r = client.post("/api/b/ours/home/seen", json={"mark": "2026-10-30T18:00:00+00:00", "glance": True})
    assert r.status_code == 204
    db.expire_all()
    assert db.get(HomeVisit, _id(ddb, "val")).glanced_at == datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)
