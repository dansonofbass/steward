"""The chat routes with a scripted gateway. The isolation sweep and the change-record sweep cover them on their own
(tests/test_isolation_sweep.py, tests/test_change_record_sweep.py)."""
import json
import threading
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from steward.app import create_app
from steward.db.models import ChatConversation, ChatMessage
from steward.books.service import add_membership, create_book
from tests.advisor.stubs import StubGateway, part
from tests.factories import login, make_person
from tests.waiting import CEILING, wait_for_card, wait_until

CHAT = "/api/b/ours/chat"
Q = "How much is in savings?"
CTX = "Today is Tuesday, October 20, 2026. This is a household book. The person asking is Person 1."


@pytest.fixture
def members(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    vee = make_person(ddb, "vee", [(ours.id, "viewer")])
    return jr, vee


def make(settings, books, gw):
    return TestClient(create_app(settings, books, gateway=gw), base_url="https://nas.tail1234.ts.net")


def answered(text="Account 1 holds $14,500.00.", question=Q):
    user = {"role": "user", "content": [{"type": "text", "text": question}]}
    system = {"role": "system", "content": CTX}
    assistant = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    return [{"type": "redacted", "text": question, "edits": []},
            {"type": "record", "seq": 1, "model": "claude-opus-5-5",
             "parts": [part("question", {"text": question}), part("system", {"text": CTX})]},
            {"type": "sent", "messages": [{"message": user, "mac": "a" * 64}, {"message": system, "mac": "b" * 64}]},
            {"type": "text", "delta": text},
            {"type": "assistant", "message": assistant, "mac": "c" * 64, "model": "claude-opus-5-5", "usage": {}},
            {"type": "done", "stop": "end_turn", "line": None, "check": None, "path": None, "requests": 1,
             "cost_nd": 90_000_000, "last_input_tokens": 5000}]


def test_chat_is_off_until_a_manager_turns_it_on(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        s = c.get(CHAT).json()
        assert s["on"] is False and s["can_change"] is True and s["can_budget"] is True
        assert {k: s["gateway"][k] for k in ("state", "line")} == {"state": "ok", "line": "The gateway is answering."}
        assert s["budget"]["line"] == "This month: $3.12 of $10 · 26 questions"
        r = c.post(f"{CHAT}/on", json={"on": True})
        assert r.status_code == 200 and r.json()["on"] is True
        assert r.json()["changed"]["line"].startswith("Turned on by Jr, ")
        assert c.post(f"{CHAT}/on", json={"on": "yes"}).json() == {"error": "Choose on or off."}
        assert (s["members"], s["others"]) == (["Jr", "Vee"], ["Vee"])     # who sees the disclosure later (INS-18)
        login(c, "vee")
        v = c.get(CHAT).json()
        assert v["on"] is True and not v["can_change"] and not v["seen"] and not v["can_budget"]
        assert c.post(f"{CHAT}/on", json={"on": False}).status_code == 403
        assert c.post(f"{CHAT}/seen", json={}).json() == {"seen": True}
        assert c.get(CHAT).json()["seen"] is True


def test_asking_when_chat_is_off_is_refused(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        r = c.post(f"{CHAT}/ask", json={"question": Q})
        assert (r.status_code, r.json()) == (409, {"error": "Chat is off for this book. A manager can turn it on in Settings → Chat."})


def test_ask_streams_events_and_the_log_reads_back(settings, books, members):
    gw = StubGateway(answered())
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        login(c, "vee")
        r = c.post(f"{CHAT}/ask", json={"question": Q, "conversation_id": None})
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in r.text.splitlines()]
        assert [e["type"] for e in events] == ["conversation", "labels", "redacted", "text", "done"]
        assert events[-1]["stop"] == "end_turn" and events[-1]["parts"] == 2 and events[-1]["cost_cents"] == 9
        page = c.get(f"{CHAT}/sent").json()
        assert [(x["what"], x["who"], x["channel"]) for x in page["requests"]] == [("Question", "Vee", "Chat")]
        detail = c.get(f"{CHAT}/sent/{page['requests'][0]['key']}").json()
        assert [p["payload"] for p in detail["parts"]] == [{"text": Q}, {"text": CTX}]
        assert c.get(f"{CHAT}/export").status_code == 404
        convs = c.get(f"{CHAT}/conversations").json()["conversations"]
        assert [x["title"] for x in convs] == ["How much is in savings?"]
        view = c.get(f"{CHAT}/conversations/{convs[0]['id']}").json()
        assert [(t["asked"], t["answer"]) for t in view["turns"]] == [(Q, "Account 1 holds $14,500.00.")]
        login(c, "jr")
        assert c.get(f"{CHAT}/conversations").json()["conversations"] == []
        assert c.get(f"{CHAT}/conversations/{convs[0]['id']}").status_code == 404
        exported = c.get(f"{CHAT}/export")
        assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
        assert [row["part"] for row in exported.json()] == ["question", "system"]


def test_every_member_reads_every_turn_in_the_log(settings, books, members, ddb, ours):
    """P17: the log is the book's, not the asker's. A manager's turn and a viewer's turn are both in every member's
    list, under the person who asked, and each opens for every member."""
    make_person(ddb, "pat", [(ours.id, "manager")])
    q2 = "What did we spend on groceries?"
    gw = StubGateway(answered() + answered("Groceries came to $612.00.", question=q2))   # one socket, both turns
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        assert c.post(f"{CHAT}/ask", json={"question": Q}).status_code == 200
        login(c, "vee")
        assert c.post(f"{CHAT}/ask", json={"question": q2}).status_code == 200
        for who in ("jr", "vee", "pat"):
            login(c, who)
            rows = c.get(f"{CHAT}/sent").json()["requests"]
            seen = set()
            for row in rows:
                r = c.get(f"{CHAT}/sent/{row['key']}")
                assert r.status_code == 200, (who, row["key"])
                seen.add((row["who"], r.json()["parts"][0]["payload"]["text"]))
            assert len(rows) == 2 and seen == {("Jr", Q), ("Vee", q2)}, who
    assert gw.connects == 2


def test_bad_questions_are_refused_before_anything_is_sent(settings, books, members):
    gw = StubGateway()
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        assert c.post(f"{CHAT}/ask", json={"question": "x" * 2001}).json() == {"error": "Questions can be up to 2,000 characters."}
        assert c.post(f"{CHAT}/ask", json={"question": 7}).status_code == 422
        assert c.post(f"{CHAT}/ask", json={"question": "Hi", "conversation_id": 999}).status_code == 404
    assert gw.connects == 0


def test_the_preview_shows_what_would_go(settings, books, members):
    gw = StubGateway(redact=lambda text: {"text": "Did [name] call?",
                                          "edits": [{"start": 4, "end": 14, "label": "[name]", "layer": "gliner"}]})
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        r = c.post(f"{CHAT}/preview", json={"text": "Did Tom Becker call?"}).json()
        assert r == {"text": "Did [name] call?", "as_written": False,
                     "chips": [{"start": 4, "end": 10, "label": "[name]", "layer": "gliner"}], "labels": {}}
    with make(settings, books, StubGateway(away=True)) as c:
        login(c, "jr")
        r = c.post(f"{CHAT}/preview", json={"text": "Hello"})
        assert (r.status_code, r.json()["error"]) == (503, "Chat needs the gateway, which isn't answering. It may be asleep or turned off.")


def test_prewarm_is_recorded_before_it_is_sent(settings, books, members):
    gw = StubGateway()
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        assert c.post(f"{CHAT}/prewarm", json={}).json() == {"sent": True}
        assert c.get(f"{CHAT}/sent").json()["requests"][0]["channel"] == "Getting ready"
        assert c.get(f"{CHAT}/export").json()[0]["model"] == "claude-opus-5-5"          # PRIV-15
    assert len(gw.prewarms) == 1


def test_usage_shows_only_the_persons_books(settings, books, members, ours, ddb):
    other = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"])
    usage = {"month": "2026-10", "cap_cents": 1000,
             "months": [{"month": "2026-09", "spent_cents": 210, "questions": 9},
                        {"month": "2026-10", "spent_cents": 312, "questions": 26}],
             "by_book": [{"book_id": ours.id, "spent_cents": 300, "questions": 25},
                         {"book_id": other.id, "spent_cents": 12, "questions": 1}],
             "by_person": [{"book_id": ours.id, "user_id": members[0].id, "spent_cents": 300, "questions": 25},
                           {"book_id": other.id, "user_id": 999, "spent_cents": 12, "questions": 1}]}
    with make(settings, books, StubGateway(usage=usage)) as c:
        login(c, "vee")
        u = c.get(f"{CHAT}/usage").json()["usage"]
        assert u["months"][0] == {"month": "Oct 2026", "spent": "$3.12", "questions": 26}
        assert u["by_book"] == [{"book": "Ours", "spent": "$3", "questions": 25}]
        assert u["by_person"] == [{"book": "Ours", "person": "Jr", "spent": "$3", "questions": 25}]


def test_the_budget_is_for_household_managers(settings, books, members, ours, ddb):
    other = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"])
    make_person(ddb, "mm", [(other.id, "manager")])
    gw = StubGateway()
    with make(settings, books, gw) as c:
        login(c, "jr")
        assert c.post(f"{CHAT}/budget", json={"cap_dollars": 25, "model": "claude-sonnet-5-5"}).json() == {"ok": True}
        assert gw.settings_calls == [{"cap_cents": 2500, "model": "claude-sonnet-5-5"}]
        assert c.post(f"{CHAT}/budget", json={"model": "claude-haiku-5-5"}).json() == {
            "error": "Choose Claude Opus 5.5 or Claude Sonnet 5.5."}
        for dollars in (0, 101, 10_000):            # $1 to $100, as the message says (final review, finding 5)
            r = c.post(f"{CHAT}/budget", json={"cap_dollars": dollars})
            assert (r.status_code, r.json()) == (422, {"error": "Choose a budget from $1 to $100."}), dollars
        assert c.post(f"{CHAT}/budget", json={"cap_dollars": 100}).json() == {"ok": True}
        assert gw.settings_calls[1:] == [{"cap_cents": 10_000}]
        login(c, "vee")
        assert c.post(f"{CHAT}/budget", json={"cap_dollars": 30}).status_code == 403
        login(c, "mm")
        assert c.post(f"/api/b/{other.slug}/chat/budget", json={"cap_dollars": 30}).status_code == 404


def test_a_second_household_book_cannot_change_the_install_wide_budget(settings, books, members, ours, ddb):
    from steward.db.directory_models import Book
    older = create_book(books, ddb, name="Older", kind="parent", owner_labels=["Margaret", "Joint"])
    ddb.get(Book, older.id).kind = "household"           # an older install: a second household-kind book
    ddb.commit()
    make_person(ddb, "mm", [(older.id, "manager")])
    gw = StubGateway()
    with make(settings, books, gw) as c:
        login(c, "mm")
        assert c.get(f"/api/b/{older.slug}/chat").json()["can_budget"] is False
        r = c.post(f"/api/b/{older.slug}/chat/budget", json={"cap_dollars": 30})
        assert r.status_code == 404
        assert gw.settings_calls == []
        login(c, "jr")
        assert c.get(f"{CHAT}").json()["can_budget"] is True
        assert c.post(f"{CHAT}/budget", json={"cap_dollars": 30}).json() == {"ok": True}
        assert gw.settings_calls == [{"cap_cents": 3000}]


def test_chat_without_a_gateway_says_it_isnt_set_up(client, books, members):
    login(client, "jr")
    s = client.get(CHAT).json()
    assert {k: s["gateway"][k] for k in ("state", "line")} == {"state": "not_set_up", "line": "Chat isn't set up on the gateway yet."} and s["budget"] is None


def test_refusals_map_to_error_bodies_with_the_right_status(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        assert c.post(f"{CHAT}/ask", json={"question": Q}).status_code == 409           # chat is off
        c.post(f"{CHAT}/on", json={"on": True})
        r = c.post(f"{CHAT}/ask", json={"question": "  "})
        assert (r.status_code, r.json()) == (422, {"error": "Type a question first."})
        r = c.post(f"{CHAT}/ask", json={"question": Q, "conversation_id": 99})
        assert (r.status_code, r.json()) == (404, {"error": "No such conversation."})
        assert c.get(f"{CHAT}/conversations/99").status_code == 404


def test_a_long_conversation_is_refused_with_409(settings, books, members, ours, engine):
    from datetime import datetime, timezone

    from sqlalchemy.orm import Session

    from steward.advisor.turn import TOO_LONG
    from steward.db.models import ChatConversation
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        with Session(engine) as db:
            at = datetime(2026, 10, 20, tzinfo=timezone.utc)
            db.add(ChatConversation(user_id=members[0].id, title="Long", created_at=at, updated_at=at,
                                    last_input_tokens=200_000))
            db.commit()
            cid = db.query(ChatConversation).one().id
        r = c.post(f"{CHAT}/ask", json={"question": Q, "conversation_id": cid})
        assert (r.status_code, r.json()) == (409, {"error": TOO_LONG})


def test_a_pass_that_cannot_prove_the_text_clean_is_a_plain_stop_line(settings, books, members, monkeypatch):
    from steward.advisor import turn as turn_mod
    from steward.advisor.redact import Refused
    from steward.api import chat as chat_mod
    from steward_boundary.protocol import LINES

    def refuse(*a, **k):
        raise Refused
    gw = StubGateway()
    want = {"error": LINES["stopped_check"], "stop": "stopped_check"}
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        monkeypatch.setattr(chat_mod, "exact_redact", refuse)
        monkeypatch.setattr(turn_mod, "exact_redact", refuse)
        r = c.post(f"{CHAT}/preview", json={"text": "Robert,1234 5678"})
        assert (r.status_code, r.json()) == (422, want)
        r = c.post(f"{CHAT}/ask", json={"question": "Robert,1234 5678"})
        assert (r.status_code, r.json()) == (422, want)
    assert gw.connects == 0


def test_a_gateway_edit_over_an_alias_chip_is_a_plain_stop_line_on_the_preview(settings, books, members):
    from steward_boundary.protocol import LINES
    gw = StubGateway(redact=lambda text: {"text": text.replace("Person 1", "[name]"),
                                          "edits": [{"start": text.index("Person 1"), "end": text.index("Person 1") + 8,
                                                     "label": "[name]", "layer": "gliner"}]})
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        r = c.post(f"{CHAT}/preview", json={"text": "Does Vee or Jr have savings?"})
        assert (r.status_code, r.json()) == (422, {"error": LINES["stopped_check"], "stop": "stopped_check"})
    assert gw.redact_issued and all(t.startswith("Person ") for t in gw.redact_issued)


def test_only_managers_export_the_log_but_every_member_reads_it(settings, books, members):
    gw = StubGateway(answered())
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        login(c, "vee")
        c.post(f"{CHAT}/ask", json={"question": Q})
        page = c.get(f"{CHAT}/sent")
        assert page.status_code == 200 and len(page.json()["requests"]) == 1
        assert c.get(f"{CHAT}/sent/{page.json()['requests'][0]['key']}").status_code == 200
        assert c.get(f"{CHAT}/export").status_code == 404
        login(c, "jr")
        assert c.get(f"{CHAT}/sent").status_code == 200 and c.get(f"{CHAT}/export").status_code == 200
        # Gate finding PRIV-15: each entry names the model the gateway sent it to.
        assert [(e["part"], e["model"]) for e in c.get(f"{CHAT}/export").json()] == [
            ("question", "claude-opus-5-5"), ("system", "claude-opus-5-5")]


def test_the_export_keeps_a_model_only_when_it_looks_like_one(db):
    from datetime import datetime, timezone
    from steward.advisor.outgoing import export, model_name, record_payload
    assert [model_name(m) for m in ("claude-opus-5-5", None, "", "x" * 41, "a b", 5)] == [
        "claude-opus-5-5", None, None, None, None, None]
    at = datetime(2026, 10, 20, tzinfo=timezone.utc)
    record_payload(db, user_id=1, conversation_id=None, turn_id="p_1", seq=1, channel="prewarm", part="system",
                   payload={"message": "warmup"}, now=at, model="claude opus\nlog")
    assert export(db)[0]["model"] is None


def test_dates_and_the_budget_line_use_today_in_the_households_zone(settings, books, members, monkeypatch):
    from datetime import datetime, timezone

    # 05:00 UTC on Nov 1 is 10:00 PM on Oct 31 in Los Angeles.
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2026, 11, 1, 5, tzinfo=timezone.utc))
    health = {"key_set": True, "redaction_ready": True, "chat_stopped": False, "ollama": False, "categorizer": False,
              "budget": {"month": "2026-10", "cap_cents": 1000, "max_cap_cents": 10_000, "spent_cents": 1000,
                         "reserved_cents": 0, "questions": 40, "warn": False, "can_ask": False,
                         "model": "claude-opus-5-5"}}
    gw = StubGateway(answered(), health=health)
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        s = c.get(CHAT).json()
        assert s["changed"]["line"].endswith("Oct 31")        # not Nov 1, the UTC date
        assert "Chat starts again on Nov 1" in s["budget"]["cap_line"]
        c.post(f"{CHAT}/ask", json={"question": Q})
        assert c.get(f"{CHAT}/sent").json()["requests"][0]["when"] == "today at 10:00 PM"


def test_approving_needs_a_manager_and_a_waiting_card(settings, books, members):
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        r = c.post(f"{CHAT}/approvals", json={"turn_id": "t_0000000000000001", "call_id": "toolu_1", "send": True})
        assert (r.status_code, r.json()) == (404, {"error": "That question isn't waiting for an OK."})
        assert c.post(f"{CHAT}/approvals", json={"turn_id": 1, "call_id": "x", "send": True}).status_code == 422
        r = c.post(f"{CHAT}/turns/t_0000000000000001/stop", json={})
        assert (r.status_code, r.json()) == (404, {"error": "That answer has already finished."})
        login(c, "vee")
        assert c.post(f"{CHAT}/approvals", json={"turn_id": "t_1", "call_id": "x", "send": True}).status_code == 403
        assert c.post(f"{CHAT}/turns/t_0000000000000001/stop", json={}).status_code == 404     # viewers may stop


def test_an_approval_over_http_counts_only_for_the_asker_in_the_turns_book_with_the_cards_hash(settings, books, members,
                                                                                              ours, ddb):
    """Task 6.5: the route passes the signed-in person, the book in the URL and the card's hash to the live turn; the
    turn's own person in its own book, with the hash of the card shown, is the only answer that counts."""
    jr, vee = members
    make_person(ddb, "sam", [(ours.id, "manager")])
    other = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"])
    add_membership(ddb, jr.id, other.id, "manager", by=None)
    ddb.commit()
    turn_id = "t_00000000000000a1"
    with make(settings, books, StubGateway()) as c:
        control = c.app.state.advisor.control
        control.begin(turn_id, jr.id, ours.id)
        got = []
        waiter = threading.Thread(target=lambda: got.append(control.wait_for_ok(turn_id, "toolu_1", 10, digest="a" * 64)))
        waiter.start()
        wait_for_card(control, turn_id, "toolu_1")
        body = {"turn_id": turn_id, "call_id": "toolu_1", "send": True, "hash": "a" * 64}
        login(c, "sam")
        assert c.post(f"{CHAT}/approvals", json=body).status_code == 404                       # another manager
        login(c, "vee")
        assert c.post(f"{CHAT}/approvals", json=body).status_code == 403                       # a viewer
        login(c, "jr")
        assert c.post(f"/api/b/{other.slug}/chat/approvals", json=body).status_code == 404     # another book
        assert c.post(f"{CHAT}/approvals", json={**body, "hash": "b" * 64}).status_code == 404  # an altered list
        assert c.post(f"{CHAT}/approvals", json={k: v for k, v in body.items() if k != "hash"}).status_code == 404
        assert c.post(f"{CHAT}/approvals", json={**body, "hash": 7}).status_code == 422
        assert got == []
        r = c.post(f"{CHAT}/approvals", json=body)
        assert (r.status_code, r.json()) == (200, {"ok": True})
        waiter.join(5)
        assert got == ["send"]
        assert c.post(f"{CHAT}/approvals", json=body).status_code == 404                       # a replay
        control.end(turn_id)


def test_an_approval_over_http_releases_the_waiting_turn(settings, books, members, ours, monkeypatch):
    """Final review, Task 6.5: a live turn waits on its store-names card in the app's own Control; POST /chat/approvals
    with the card's hash lets it go on, the approved rows are sent and the answer comes back."""
    import steward.advisor.turn as turn_mod
    from steward.advisor.turn import AskEnv, run_turn, start_turn
    from steward_boundary import tools as T

    jr, _ = members
    now = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
    call = {"id": "toolu_m1", "name": T.MERCHANT, "input": {"reason": "Totals can't.", "start": "2026-10-01",
                                                           "end": "2026-10-20", "category": None, "payees": None}}
    rows = {"rows": [{"date": "2026-10-18", "amount_cents": -1599, "category": "subscriptions", "merchant": "StreamBox",
                      "account": "Account 1"}], "payees": [], "more": False}
    monkeypatch.setattr(turn_mod, "run_call", lambda c, **kw: {"id": c["id"], "name": c["name"], "content": rows,
                                                               "error": None})

    def echoed(sent):
        r = next(f for f in sent if f["type"] == "tool_results")["results"][0]
        return {"type": "record", "seq": 2, "parts": [part("merchant_rows", {
            "tool_use_id": r["id"], "name": r["name"], "is_error": False, "content": r["content"]})]}
    gw = StubGateway(answered()[:3] + [{"type": "tool_calls", "seq": 1, "calls": [call]}, echoed] + answered()[3:])
    with make(settings, books, gw) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        env = AskEnv(bind=books.engine_for(ours).execution_options(immediate=True), directory=books.directory,
                     book=ours, user_id=jr.id, people=lambda: books.people(ours.id), plan_cache=books.plan_cache(ours.id),
                     gateway=gw, now=lambda: now, today=lambda: date(2026, 10, 20),
                     control=c.app.state.advisor.control, approval_wait=10)
        prep = start_turn(env, Q)
        turn = run_turn(env, prep)
        card = next(e for e in turn if e["type"] == "approval")["card"]
        rest: list[dict] = []
        t = threading.Thread(target=lambda: rest.extend(turn))      # the turn waits on the card in its worker
        t.start()
        wait_for_card(c.app.state.advisor.control, prep.turn_id, "toolu_m1")   # the worker waits on the card now
        assert t.is_alive() and rest == []
        r = c.post(f"{CHAT}/approvals", json={"turn_id": prep.turn_id, "call_id": "toolu_m1", "send": True,
                                              "hash": card["hash"]})
        assert (r.status_code, r.json()) == (200, {"ok": True})
        t.join(CEILING)
        assert not t.is_alive()
    assert rest[0]["type"] == "approval" and rest[0]["state"] == "approved"
    assert rest[-1]["type"] == "done" and rest[-1]["stop"] == "end_turn"
    sent = next(f for f in gw.ws.sent if f["type"] == "tool_results")["results"][0]
    assert sent["error"] is None and sent["content"] == rows


def test_the_stream_releases_a_waiting_card_when_the_browser_goes_away(books, ours, ddb, monkeypatch):
    """Task 6.5: Starlette cancels the response when the browser disconnects. The stream must not wait on the worker
    thread (up to 10 minutes in a card's wait); it releases the live turn, so the worker cancels at the gateway,
    closes the socket and finishes long before the card's 30 s wait."""
    import anyio
    from sqlalchemy.orm import Session

    import steward.advisor.turn as turn_mod
    from steward.advisor.control import Control
    from steward.advisor.state import set_chat_on
    from steward.advisor.turn import AskEnv, run_turn, start_turn
    from steward.api.chat import stream_turn
    from steward.demo import seed_people
    from steward_boundary import tools as T

    now = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
    seed_people(ddb, ours.id)
    jr = next(p.id for p in books.people(ours.id) if p.username == "alex")
    with Session(books.engine_for(ours)) as db:
        set_chat_on(db, True, None, now)
        db.commit()
    call = {"id": "toolu_m1", "name": T.MERCHANT, "input": {"reason": "Totals can't.", "start": "2026-10-01",
                                                           "end": "2026-10-20", "category": None, "payees": None}}
    rows = {"rows": [{"date": "2026-10-18", "amount_cents": -1599, "category": "subscriptions", "merchant": "StreamBox",
                      "account": "Account 1"}], "payees": [], "more": False}
    monkeypatch.setattr(turn_mod, "run_call", lambda c, **kw: {"id": c["id"], "name": c["name"], "content": rows,
                                                               "error": None})
    gw = StubGateway(answered()[:3] + [{"type": "tool_calls", "seq": 1, "calls": [call]}])
    control = Control()
    env = AskEnv(bind=books.engine_for(ours).execution_options(immediate=True), directory=books.directory, book=ours,
                 user_id=jr, people=lambda: books.people(ours.id), plan_cache=books.plan_cache(ours.id), gateway=gw,
                 now=lambda: now, today=lambda: date(2026, 10, 20), control=control, approval_wait=30)
    prep = start_turn(env, Q)
    lines = stream_turn(run_turn(env, prep), lambda: control.release(prep.turn_id))
    seen = []

    async def browser():
        # The browser goes away while the card waits: the response is cancelled the moment the card is asked, as
        # Starlette cancels it when the browser disconnects.
        with anyio.fail_after(CEILING):
            with anyio.CancelScope() as gone:
                async for line in lines:
                    seen.append(json.loads(line))
                    if seen[-1]["type"] == "approval" and seen[-1]["state"] == "ask":
                        gone.cancel()
        await lines.aclose()
    anyio.run(browser)
    # approval_wait is 30 s, over CEILING: a stream that waited on the worker instead of releasing it fails here.
    wait_until(lambda: gw.ws.closed, "the worker to cancel at the gateway and close the socket")
    assert any(e["type"] == "approval" and e["state"] == "ask" for e in seen)
    assert gw.ws.sent[-1] == {"type": "cancel", "reason": "stopped"}


def test_the_list_and_one_conversation_replay_a_turn(settings, books, members):
    with make(settings, books, StubGateway(answered("Person 1 has $14,500.00."))) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        c.post(f"{CHAT}/ask", json={"question": Q})
        rows = c.get(f"{CHAT}/conversations").json()["conversations"]
        assert len(rows) == 1
        row = rows[0]
        assert (row["group"], row["questions"], row["store_names"], row["requests"]) == ("today", 1, False, 1)
        assert row["title"] == "How much is in savings?" and row["when"].endswith(("AM", "PM"))
        d = c.get(f"{CHAT}/conversations/{row['id']}").json()
        assert d["requests"] == 1 and d["long_line"] is None and d["labels"]["Person 1"]
        (t,) = d["turns"]
        assert (t["asked"], t["sent"], t["as_written"], t["answer"]) == (Q, Q, True, "Person 1 has $14,500.00.")
        assert t["who"] == "Jr" and t["when"].startswith("Today ") and t["steps"] == [] and t["saw"] == []
        assert t["meta"] == "1 second · $0.09" and t["approval"] is None and t["looked_into"] is False
        assert t["unfinished"] is False
        login(c, "vee")
        assert c.get(f"{CHAT}/conversations").json() == {"conversations": []}
        assert c.get(f"{CHAT}/conversations/{row['id']}").status_code == 404
        assert c.delete(f"{CHAT}/conversations/{row['id']}").status_code == 404


def test_deleting_a_conversation_keeps_its_log(settings, books, members):
    with make(settings, books, StubGateway(answered())) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        login(c, "vee")
        cid = json.loads(c.post(f"{CHAT}/ask", json={"question": Q}).text.splitlines()[0])["id"]
        assert c.delete(f"{CHAT}/conversations/{cid}").json() == {"deleted": True}
        assert c.get(f"{CHAT}/conversations").json() == {"conversations": []}
        assert c.get(f"{CHAT}/conversations/{cid}").status_code == 404
        assert len(c.get(f"{CHAT}/sent").json()["requests"]) == 1


def test_a_conversation_from_before_plan_b_still_replays(settings, books, members, ours):
    jr, _ = members
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    now = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
    with Session(books.engine_for(ours)) as db:
        conv = ChatConversation(user_id=jr.id, title="Savings", created_at=now, updated_at=now, last_input_tokens=0)
        db.add(conv)
        db.flush()
        for role, content in (("user", [{"type": "text", "text": "How much is in savings?"}]),
                              ("assistant", [{"type": "text", "text": "Person 1 has $9.00."}])):
            db.add(ChatMessage(conversation_id=conv.id, turn_id="t_00000000000000ab", role=role,
                               content=json.dumps({"role": role, "content": content}), mac="a" * 64, created_at=now))
        db.commit()
        cid = conv.id
    with make(settings, books, StubGateway()) as c:
        login(c, "jr")
        (t,) = c.get(f"{CHAT}/conversations/{cid}").json()["turns"]
        assert (t["asked"], t["answer"], t["meta"]) == ("How much is in savings?", "Person 1 has $9.00.", None)
        assert c.get(f"{CHAT}/conversations").json()["conversations"][0]["questions"] == 1


def test_the_log_filters_by_who_and_what(settings, books, members):
    with make(settings, books, StubGateway(answered())) as c:
        login(c, "jr")
        c.post(f"{CHAT}/on", json={"on": True})
        c.post(f"{CHAT}/ask", json={"question": Q})
        page = c.get(f"{CHAT}/sent").json()
        assert [p["name"] for p in page["people"]] == ["Jr", "Vee"]
        jr_id = page["people"][0]["id"]
        assert len(c.get(f"{CHAT}/sent?who={jr_id}&what=question").json()["requests"]) == 1
        assert c.get(f"{CHAT}/sent?what=results").json()["requests"] == []
        r = c.get(f"{CHAT}/sent?what=everything")
        assert (r.status_code, r.json()) == (422, {"error": "That filter wasn't understood."})
        key = page["requests"][0]["key"]
        d = c.get(f"{CHAT}/sent/{key}").json()
        assert d["who"] == "Jr" and d["conversation"] == "How much is in savings?" and d["checks"]
