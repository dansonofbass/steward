from steward.deps import VIEWER_COPY
from tests.factories import add_fact, login, make_user


def test_requires_sign_in(client):
    assert client.get("/api/b/ours/profile").status_code == 401
    for path in ("/api/b/ours/profile/sections/you", "/api/b/ours/profile/seen", "/api/b/ours/profile/confirm",
                 "/api/b/ours/profile/later"):
        assert client.post(path, json={}).status_code == 401, path
    assert client.put("/api/b/ours/profile/sections/you/resume", json={"step": None}).status_code == 401


def test_an_empty_household(frozen, signed_in):
    body = signed_in.get("/api/b/ours/profile").json()
    assert [s["key"] for s in body["sections"]] == ["you", "kids", "home", "benefits", "banks"]
    assert [s["minutes"] for s in body["sections"]] == [3, 2, 3, 5, 5]
    assert {s["status"] for s in body["sections"]} == {"todo"}
    assert (body["done"], body["total"], body["finished"], body["next"]) == (0, 5, False, "you")
    assert body["me"] == {"user_id": body["me"]["user_id"], "role": "jr", "seen": False, "confirmed": False, "later_until": None}


def test_done_needs_the_data_and_a_skip_keeps_what_is_missing(frozen, signed_in, db):
    r = signed_in.post("/api/b/ours/profile/sections/home", json={"status": "done"})
    assert r.status_code == 409 and r.json() == {"error": "Still needed: whether you own a home."}
    r = signed_in.post("/api/b/ours/profile/sections/home", json={"status": "skipped"})
    home = r.json()["sections"][2]
    assert (home["status"], home["by"], home["missing"]) == ("skipped", "JR", "whether you own a home")
    add_fact(db, "home.owns", "no")
    r = signed_in.post("/api/b/ours/profile/sections/home", json={"status": "done"})
    assert r.status_code == 200 and r.json()["sections"][2]["status"] == "done" and r.json()["done"] == 1


def test_answers_are_checked(frozen, signed_in):
    p = "/api/b/ours/profile/sections"
    assert signed_in.post(f"{p}/garage", json={"status": "done"}).json() == {"error": "No such section."}
    assert signed_in.post(f"{p}/you", json={"status": "maybe"}).json() == {"error": "Choose done, skipped or doesnt_apply."}
    r = signed_in.post(f"{p}/you", json={"status": "doesnt_apply"})
    assert r.status_code == 422 and r.json() == {"error": "Only Kids and college can be marked Doesn't apply."}
    assert signed_in.post(f"{p}/you", json={"status": "done", "x": 1}).json() == {"error": "Unknown field: x."}


def test_resume_points(frozen, signed_in):
    p = "/api/b/ours/profile/sections/home/resume"
    r = signed_in.put(p, json={"step": "mortgages"})
    assert r.status_code == 200 and (r.json()["sections"][2]["resume_step"], r.json()["sections"][2]["status"]) == ("mortgages", "todo")
    for body in ({"step": "garage"}, {"step": 3}, {}):
        r = signed_in.put(p, json=body)
        assert r.status_code == 422 and r.json() == {"error": "Name one of the section's steps, or null."}
    assert signed_in.put(p, json={"step": None}).json()["sections"][2]["resume_step"] is None


def test_later_hides_home_s_line_for_a_week_and_me_carries_it(frozen, signed_in):
    r = signed_in.post("/api/b/ours/profile/later", json={"later": True})
    assert r.status_code == 200 and r.json()["me"]["later_until"] == "2026-10-20T19:00:00+00:00"
    assert r.json()["undo"]
    assert signed_in.get("/api/auth/me").json()["books"][0]["profile"]["later_until"] == "2026-10-20T19:00:00+00:00"
    assert signed_in.post("/api/b/ours/profile/later", json={"later": False}).json()["me"]["later_until"] is None
    r = signed_in.post("/api/b/ours/profile/later", json={"later": "yes"})
    assert r.status_code == 422 and r.json() == {"error": "Say true or false for later."}


def test_seen_and_confirm_are_each_persons_own(frozen, signed_in):
    assert signed_in.post("/api/b/ours/profile/seen", json={}).json()["me"]["seen"] is True
    me = signed_in.post("/api/b/ours/profile/confirm", json={}).json()["me"]
    assert (me["seen"], me["confirmed"]) == (True, True)


def test_a_viewer_reads_but_cannot_answer(frozen, client, db):
    make_user(db, "sam", "sam@x.com", "Sam", role="viewer")
    login(client, "sam")
    assert client.get("/api/b/ours/profile").status_code == 200
    r = client.post("/api/b/ours/profile/seen", json={})
    assert r.status_code == 403 and r.json() == {"error": VIEWER_COPY}


def test_a_parent_book_has_no_profile(client, margaret):
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/profile").status_code == 404
