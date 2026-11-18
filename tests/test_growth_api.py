"""GET /api/b/{slug}/growth and POST .../growth/seen (phase 17 spec 3.4, 3.9): the stage and the milestones, the same
for viewers as for members; the seen mark is each person's own; parent books have no tree."""
from datetime import date

import pytest
from sqlalchemy import select

from steward.api.body import NOT_UNDERSTOOD
from steward.db.directory_models import Membership, User
from steward.db.models import Fact
from tests.factories import login, make_account, make_person, make_txn


def _book(client, ddb, ours, db):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "vee", [(ours.id, "viewer")])
    make_txn(db, make_account(db, "Checking"), date(2025, 6, 1), -100, "OLD", category="dining")   # stage 2


def test_growth_is_the_stage_the_milestones_and_the_persons_own_seen(client, ddb, ours, db):
    _book(client, ddb, ours, db)
    login(client, "jr")
    g = client.get("/api/b/ours/growth").json()
    assert set(g) == {"stage", "milestones", "seen"}                              # counts, keys and a month only
    assert g["stage"] == 2 and g["seen"] is False
    assert g["milestones"] == [{"key": "first_month", "met": True, "month": "2025-06"}, {"key": "covered", "met": False},
                               {"key": "checklist", "met": False}, {"key": "year", "met": True},
                               {"key": "five_years", "met": False}]
    assert client.post("/api/b/ours/growth/seen", json={"stage": 2}).status_code == 204
    assert client.get("/api/b/ours/growth").json()["seen"] is True
    login(client, "vee")
    v = client.get("/api/b/ours/growth").json()
    assert (v["stage"], v["milestones"], v["seen"]) == (2, g["milestones"], False)   # a viewer sees the same tree
    assert client.post("/api/b/ours/growth/seen", json={"stage": 2}).status_code == 204
    assert client.get("/api/b/ours/growth").json()["seen"] is True


def test_a_viewer_opening_it_first_still_raises_the_stage(client, ddb, ours, db):
    _book(client, ddb, ours, db)
    login(client, "vee")
    assert client.get("/api/b/ours/growth").json()["stage"] == 2
    db.rollback()
    assert db.scalars(select(Fact.value).where(Fact.key == "growth.stage")).all() == ["2"]


def test_the_seen_mark_only_rises(client, ddb, ours, db):
    _book(client, ddb, ours, db)
    login(client, "jr")
    client.post("/api/b/ours/growth/seen", json={"stage": 2})
    client.post("/api/b/ours/growth/seen", json={"stage": 0})
    jr = ddb.scalar(select(User.id).where(User.username == "jr"))
    ddb.expire_all()
    assert ddb.get(Membership, (jr, ours.id)).growth_seen == 2


@pytest.mark.parametrize("body", [{}, {"stage": "2"}, {"stage": 6}, {"stage": -1}, {"stage": True}, {"stage": 2, "x": 1}])
def test_the_seen_mark_takes_a_stage_from_0_to_5(client, ddb, ours, db, body):
    _book(client, ddb, ours, db)
    login(client, "jr")
    r = client.post("/api/b/ours/growth/seen", json=body)
    assert r.status_code == 422 and r.json() == {"error": NOT_UNDERSTOOD}


def test_a_parent_book_has_no_tree(client, margaret):
    login(client, "jr")
    assert client.get(f"/api/b/{margaret.slug}/growth").status_code == 404
    assert client.post(f"/api/b/{margaret.slug}/growth/seen", json={"stage": 1}).status_code == 404


def test_someone_outside_the_book_gets_404(client, ddb, ours, db):
    _book(client, ddb, ours, db)
    make_person(ddb, "stranger")
    login(client, "stranger")
    assert client.get("/api/b/ours/growth").status_code == 404
