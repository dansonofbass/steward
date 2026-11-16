"""What the gateway asks the NAS for Claude Code (spec 7, rulings 1, 7, 19): the book's tools without merchant_detail,
a result with its fingerprints held for one minute, and a log row written from the NAS's own copy only when the gateway
says the checks passed. Every route takes a grant and nothing else."""
from steward import clock
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import gateway_name
from steward.advisor import grants as G
from steward.advisor.state import set_chat_on
from steward.app import create_app
from steward.books.service import create_book, remove_member
from steward.db.models import AdvisorOutgoing, EventLog
from steward.deps import GATEWAY_ONLY, GRANT_REFUSED, NO_SUCH_BOOK
from steward.demo import seed
from steward_boundary.canonical import canonical, sha256_hex
from tests.advisor.test_grant_door import PAIRED, bearer, pair
from tests.factories import login, make_person

ADV = "/api/b/ours/advisor"


@pytest.fixture
def world(settings, books, ddb, ours):
    with Session(books.engine_for(ours)) as db:
        seed(db, years=1, seed=7)
        db.commit()
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    vee = make_person(ddb, "vee", [(ours.id, "viewer")])
    mom = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret", "Joint"])
    assert mom.slug == "margaret-ellis"
    from steward.books.service import add_membership
    add_membership(ddb, jr.id, mom.id, "manager", by=None)
    now = clock.now()
    grants = {}
    for who, book, slug in ((jr, ours, "ours"), (vee, ours, "ours"), (jr, mom, "margaret-ellis")):
        _, grants[(who.username, slug)] = G.issue(ddb, book_id=book.id, slug=slug, user_id=who.id, by=jr.id, now=now)
    ddb.commit()
    for book in (ours, mom):
        with Session(books.engine_for(book)) as db:
            set_chat_on(db, True, jr.id, now)
            db.commit()
    pair(settings)
    app = create_app(settings, books)
    with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
        yield c, grants, {"jr": jr, "vee": vee, "ours": ours, "mom": mom, "books": books}


def auth(text):
    return bearer(text)


def rows(books, book):
    with Session(books.engine_for(book)) as db:
        return db.scalars(select(AdvisorOutgoing).order_by(AdvisorOutgoing.id)).all()


def test_the_household_tools_without_merchant_detail(world):
    c, grants, w = world
    r = c.get(f"{ADV}/tools", headers=auth(grants[("jr", "ours")])).json()
    assert r["book_kind"] == "household" and r["book_id"] == w["ours"].id and r["asker"].startswith("Person ")
    assert "merchant_detail" not in r["tools"] and "plan_result" in r["tools"] and "inventory" not in r["tools"]
    assert r["until"] and "book_name" not in r and "person" not in r        # ruling I1(b): no names, even here
    p = c.get("/api/b/margaret-ellis/advisor/tools", headers=auth(grants[("jr", "margaret-ellis")])).json()
    assert "inventory" in p["tools"] and "plan_result" not in p["tools"] and "merchant_detail" not in p["tools"]


def test_a_call_returns_its_result_and_fingerprints_and_records_nothing_yet(world):
    c, grants, w = world
    r = c.post(f"{ADV}/tools/accounts", json={"input": {"include_closed": False}}, headers=auth(grants[("jr", "ours")]))
    body = r.json()
    part = body["part"]
    assert body["call_id"].startswith("mcp_") and len(body["call_id"]) == 20
    assert part["part"] == "tool_result" and part["payload"]["tool_use_id"] == body["call_id"]
    assert part["payload"]["name"] == "accounts" and part["payload"]["is_error"] is False
    assert part["payload"]["content"]["accounts"][0]["account"].startswith("Account ")
    assert part["sha256"] == sha256_hex(part["payload"]) and part["bytes"] == len(canonical(part["payload"]))
    assert len(body["fingerprints"]["salt"]) == 32 and body["fingerprints"]["hashes"]
    assert rows(w["books"], w["ours"]) == []


def test_sent_records_the_nas_copy_once_with_channel_mcp(world):
    c, grants, w = world
    text = grants[("vee", "ours")]
    body = c.post(f"{ADV}/tools/book_summary", json={"input": {}}, headers=auth(text)).json()
    r = c.post(f"{ADV}/calls/{body['call_id']}", json={"outcome": "sent"}, headers=auth(text))
    assert r.json() == {"recorded": True, "sha256": body["part"]["sha256"], "bytes": body["part"]["bytes"]}
    (row,) = rows(w["books"], w["ours"])
    assert (row.channel, row.part, row.seq, row.conversation_id, row.user_id) == ("mcp", "tool_result", 1, None,
                                                                                  w["vee"].id)
    assert row.sha256 == body["part"]["sha256"] and row.turn_id == "t_" + body["call_id"][4:]
    again = c.post(f"{ADV}/calls/{body['call_id']}", json={"outcome": "sent"}, headers=auth(text))
    assert (again.status_code, again.json()) == (404, {"error": "That call has expired. Call the tool again."})


def test_a_stopped_call_is_an_event_with_the_check_and_path_never_the_value(world):
    c, grants, w = world
    text = grants[("jr", "ours")]
    body = c.post(f"{ADV}/tools/holdings", json={"input": {}}, headers=auth(text)).json()
    r = c.post(f"{ADV}/calls/{body['call_id']}", json={"outcome": "stopped", "check": "fingerprint",
                                                         "path": "parts[0].content.holdings[3].symbol"}, headers=auth(text))
    assert r.json() == {"recorded": False}
    assert rows(w["books"], w["ours"]) == []
    with Session(w["books"].engine_for(w["ours"])) as db:
        msg = db.scalar(select(EventLog.message).where(EventLog.kind == "chat").order_by(EventLog.id.desc()))
    assert msg == ("Steward stopped a Claude Code lookup before anything was returned: the known-identifier check "
                   "fired at parts[0].content.holdings[3].symbol.")
    bad = c.post(f"{ADV}/calls/x", json={"outcome": "stopped", "check": "nope", "path": "p"}, headers=auth(text))
    assert bad.status_code == 422


def test_merchant_detail_and_other_books_tools_are_not_offered(world):
    c, grants, _ = world
    text = grants[("jr", "ours")]
    for name in ("merchant_detail", "inventory", "no_such_tool"):
        r = c.post(f"{ADV}/tools/{name}", json={"input": {}}, headers=auth(text))
        assert (r.status_code, r.json()) == (404, {"error": "Claude Code can't use that tool."}), name


def test_a_bad_input_is_an_error_result_not_a_failure(world):
    c, grants, _ = world
    body = c.post(f"{ADV}/tools/cash_flow", json={"input": {"months": "six"}}, headers=auth(grants[("jr", "ours")])).json()
    assert body["part"]["payload"]["is_error"] is True
    assert body["part"]["payload"]["content"] == {"error": "That input wasn't understood."}


def test_a_call_expires_after_a_minute_and_belongs_to_its_person(world, monkeypatch):
    c, grants, w = world
    body = c.post(f"{ADV}/tools/debts", json={"input": {}}, headers=auth(grants[("jr", "ours")])).json()
    assert c.post(f"{ADV}/calls/{body['call_id']}", json={"outcome": "sent"},
                  headers=auth(grants[("vee", "ours")])).status_code == 404     # not vee's call
    later = clock.now() + timedelta(seconds=61)
    monkeypatch.setattr("steward.clock.now", lambda: later)
    assert c.post(f"{ADV}/calls/{body['call_id']}", json={"outcome": "sent"},
                  headers=auth(grants[("jr", "ours")])).status_code == 404


def test_chat_off_refuses_tools(world):
    c, grants, w = world
    with Session(w["books"].engine_for(w["ours"])) as db:
        set_chat_on(db, False, w["jr"].id, clock.now())
        db.commit()
    r = c.post(f"{ADV}/tools/accounts", json={"input": {"include_closed": False}}, headers=auth(grants[("jr", "ours")]))
    assert r.status_code == 409 and "Chat is off" in r.json()["error"]
    assert c.get(f"{ADV}/tools", headers=auth(grants[("jr", "ours")])).json()["chat"] is False


def test_a_removed_member_or_revoked_grant_gets_nothing_on_the_next_call(world, ddb):
    c, grants, w = world
    vee_text, jr_text = grants[("vee", "ours")], grants[("jr", "ours")]
    assert c.post(f"{ADV}/tools/book_summary", json={"input": {}}, headers=auth(vee_text)).status_code == 200
    ddb.rollback()      # end this session's old read snapshot so its write isn't refused as stale
    remove_member(ddb, w["ours"].id, w["vee"].id, by=w["jr"].id)
    ddb.commit()
    assert c.post(f"{ADV}/tools/book_summary", json={"input": {}}, headers=auth(vee_text)).status_code == 401
    ddb.rollback()
    g = G.resolve(ddb, jr_text, clock.now())
    G.revoke(g, w["jr"].id, clock.now())
    ddb.commit()
    r = c.post(f"{ADV}/tools/book_summary", json={"input": {}}, headers=auth(jr_text))
    assert (r.status_code, r.json()) == (401, {"error": GRANT_REFUSED})
    assert rows(w["books"], w["ours"]) == []


def test_sweep_grant_routes_take_grants_only(world):
    """Ruling 19: every grant route refuses a session cookie with no grant, and another book's grant; the revoked,
    ended and removed-member cases are pinned above and in tests/advisor/test_grant_door.py."""
    from tests.test_isolation_sweep import api_routes, fill, uses_grant
    c, grants, _ = world
    found = sorted((p, m) for p, m, _, calls in api_routes(c.app) if uses_grant(calls))
    assert found == [("/api/b/{slug}/advisor/calls/{call_id}", "POST"), ("/api/b/{slug}/advisor/tools", "GET"),
                     ("/api/b/{slug}/advisor/tools/{name}", "POST")]
    login(c, "jr")
    for path, method in found:
        url = fill(path, "ours")
        r = c.request(method, url, json={})
        assert (r.status_code, r.json()) == (401, {"error": gateway_name.fill(GATEWAY_ONLY)}), (method, path)
        r = c.request(method, url, json={}, headers={"X-Steward-Gateway": PAIRED})
        assert (r.status_code, r.json()) == (401, {"error": GRANT_REFUSED}), (method, path)
        r = c.request(method, url, json={}, headers=auth(grants[("jr", "margaret-ellis")]))
        assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK}), (method, path)
    c.cookies.clear()


def test_tools_gives_its_first_aliases_while_another_write_commits(world):
    """GET /advisor/tools is the one grant read that writes: the asker's alias, the first time (spec 4.2). Its session
    begins with BEGIN IMMEDIATE, so it waits for the other writer instead of failing with "database is locked"."""
    from sqlalchemy import func

    from steward.db.models import AdvisorAlias
    from tests.test_concurrency import _while_another_write_commits
    c, grants, w = world
    with Session(w["books"].engine_for(w["ours"])) as db:
        assert db.scalar(select(func.count()).select_from(AdvisorAlias).where(AdvisorAlias.kind == "user")) == 0
    r = _while_another_write_commits(w["books"], w["ours"],
                                     lambda: c.get(f"{ADV}/tools", headers=auth(grants[("jr", "ours")])))
    assert r.status_code == 200, r.text
    assert r.json()["asker"] == "Person 1"
    with Session(w["books"].engine_for(w["ours"])) as db:
        assert db.scalar(select(func.count()).select_from(AdvisorAlias).where(AdvisorAlias.kind == "user")) == 1
