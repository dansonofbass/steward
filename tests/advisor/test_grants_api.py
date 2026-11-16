"""Settings → Chat → Claude Code (spec 5.1, 7, ruling 3): every member sees the book's grants, managers issue them,
the text is shown once, a grant is only ever for the manager who issues it (final review M6), and a manager or the
person it is for revokes one."""
from steward import clock

import pytest
from fastapi.testclient import TestClient

from steward.advisor import grants as G
from steward.app import create_app
from tests.factories import login, make_person

URL = "/api/b/ours/chat/grants"


@pytest.fixture
def c(settings, books, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "vee", [(ours.id, "viewer")])
    make_person(ddb, "outsider")
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as client:
        yield client


def test_a_manager_issues_a_grant_for_themself_and_sees_it_once(c, ddb):
    login(c, "jr")
    listed = c.get(URL).json()
    assert listed == {"grants": [], "can_issue": True, "days": 30}             # no picker of people
    r = c.post(URL, json={}).json()
    assert G.GRANT_RE.match(r["grant"]) and r["command"] == "steward-gateway mcp-grant add"
    assert r["row"]["person"] == "Jr" and r["row"]["state"] == "active"
    again = c.get(URL).json()
    assert len(again["grants"]) == 1 and r["grant"] not in str(again)          # never shown again


def test_a_grant_cant_be_issued_for_anyone_else(c, ddb):
    """Final review M6: Claude Code's lookups are logged as the grant's person, so it is always the signed-in
    manager, who has seen the disclosure."""
    from steward.auth.users import find_user
    login(c, "jr")
    jr, vee, outsider = (find_user(ddb, n) for n in ("jr", "vee", "outsider"))
    for body in ({"user_id": vee.id}, {"user_id": outsider.id}, {"user_id": "1"}, {"user_id": True}):
        r = c.post(URL, json=body)
        assert (r.status_code, r.json()) == (422, {"error": "A grant is for the manager who issues it."}), body
    assert c.get(URL).json()["grants"] == []
    assert c.post(URL, json={"user_id": jr.id}).json()["row"]["person"] == "Jr"


def test_viewers_see_the_list_but_cannot_issue(c):
    login(c, "jr")
    c.post(URL, json={})
    login(c, "vee")
    listed = c.get(URL).json()
    assert len(listed["grants"]) == 1 and listed["can_issue"] is False and "people" not in listed
    assert c.post(URL, json={}).status_code == 403


def test_revoking(c, ddb, ours):
    from steward.auth.users import find_user
    jr, vee = find_user(ddb, "jr"), find_user(ddb, "vee")
    g, _ = G.issue(ddb, book_id=ours.id, slug="ours", user_id=vee.id, by=jr.id, now=clock.now())
    ddb.commit()                                                     # one issued before ruling M6
    for_vee = g.id
    login(c, "jr")
    for_jr = c.post(URL, json={}).json()["row"]["id"]
    login(c, "vee")
    r = c.post(f"{URL}/{for_jr}/revoke")
    assert (r.status_code, r.json()) == (403, {"error": "Only a manager or the person it's for can revoke a grant."})
    r = c.post(f"{URL}/{for_vee}/revoke").json()["row"]
    assert r["state"] == "revoked" and r["line"].startswith("Revoked by Vee, ")
    login(c, "jr")
    assert c.post(f"{URL}/{for_jr}/revoke").json()["row"]["state"] == "revoked"
    assert c.post(f"{URL}/999999/revoke").json() == {"error": "No such grant."}
