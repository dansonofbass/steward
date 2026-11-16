"""Each question leaves a chat_turn row the Ask page replays (plan B ruling 1), and the turn's events carry what the
page needs: the turn id, the alias labels, step words and the time-and-cost line."""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.advisor.state import set_chat_on
from steward.advisor.turn import DONE, AskEnv, done_words, meta_line, run_turn, start_turn
from steward.db.models import ChatTurn
from steward.demo import seed, seed_people
from steward_boundary import tools as T
from tests.advisor.stubs import StubGateway, part

NOW = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
TODAY = date(2026, 10, 20)
Q = "Can Sam and I cover a year on one income?"
SENT = "Can Person 2 and I cover a year on one income?"
CTX = "Today is Tuesday, October 20, 2026. This is a household book. The person asking is Person 1."


@pytest.fixture
def household(books, ours, engine):
    with Session(engine) as db:
        seed(db, years=1, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    with Session(engine) as db:
        set_chat_on(db, True, None, NOW)
        db.commit()
    return next(p.id for p in books.people(ours.id) if p.username == "alex")


def env_for(books, book, user_id, gateway):
    return AskEnv(bind=books.engine_for(book).execution_options(immediate=True), directory=books.directory, book=book,
                  user_id=user_id, people=lambda: books.people(book.id), plan_cache=books.plan_cache(book.id),
                  gateway=gateway, now=lambda: NOW, today=lambda: TODAY)


def one_tool_round():
    user = {"role": "user", "content": [{"type": "text", "text": SENT}]}
    system = {"role": "system", "content": CTX}
    call = {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "accounts",
                                              "input": {"include_closed": False}}]}
    answer = {"role": "assistant", "content": [{"type": "text", "text": "Person 2's pay covers it."}]}
    return [{"type": "redacted", "text": SENT, "edits": []},
            {"type": "record", "seq": 1, "parts": [part("question", {"text": SENT}), part("system", {"text": CTX})]},
            {"type": "sent", "messages": [{"message": user, "mac": "a" * 64}, {"message": system, "mac": "b" * 64}]},
            {"type": "status", "tool": "accounts"},
            {"type": "assistant", "message": call, "mac": "c" * 64, "model": "claude-opus-5-5", "usage": {}},
            {"type": "tool_calls", "seq": 1, "calls": [{"id": "toolu_1", "name": "accounts",
                                                         "input": {"include_closed": False}}]},
            {"type": "text", "delta": "Person 2's pay covers it."},
            {"type": "assistant", "message": answer, "mac": "d" * 64, "model": "claude-opus-5-5", "usage": {}},
            {"type": "done", "stop": "end_turn", "line": None, "check": None, "path": None, "requests": 2,
             "cost_nd": 90_000_000, "last_input_tokens": 6000}]


def test_a_turn_leaves_a_record_of_what_was_typed_sent_and_spent(books, ours, household):
    env = env_for(books, ours, household, StubGateway(one_tool_round()))
    prep = start_turn(env, Q)
    events = list(run_turn(env, prep))
    assert [e["type"] for e in events] == ["conversation", "labels", "redacted", "status", "labels", "text", "done"]
    assert events[0]["turn_id"] == prep.turn_id
    assert events[1]["labels"]["Person 2"] == "Sam"
    assert events[3] == {"type": "status", "tool": "accounts", "text": "Looking at accounts", "done": "Looked at accounts"}
    done = events[-1]
    assert done["turn_id"] == prep.turn_id and done["meta"] == "1 second · $0.09"
    with Session(books.engine_for(ours)) as db:
        t = db.scalar(select(ChatTurn).where(ChatTurn.turn_id == prep.turn_id))
        assert (t.asked, t.sent, t.user_id, t.conversation_id) == (Q, SENT, household, prep.conversation_id)
        assert json.loads(t.steps) == ["accounts"] and [c["label"] for c in json.loads(t.chips)] == ["Person 2"]
        assert (t.stop, t.line, t.cost_cents) == ("end_turn", None, 9)
        assert t.ms >= 0 and t.ended_at is not None and t.approval is None and t.store_rows == 0


def test_a_turn_that_never_reaches_gateway_still_leaves_its_record(books, ours, household):
    env = env_for(books, ours, household, StubGateway(away=True))
    prep = start_turn(env, Q)
    done = list(run_turn(env, prep))[-1]
    assert done["stop"] == "away" and done["meta"] == "1 second"
    with Session(books.engine_for(ours)) as db:
        t = db.scalar(select(ChatTurn).where(ChatTurn.turn_id == prep.turn_id))
        assert t.stop == "away" and t.sent is None
        assert t.line == "Chat needs the gateway, which isn't answering. It may be asleep or turned off."


def test_every_tool_has_past_tense_words():
    assert set(DONE) == {t.name for t in T.TOOLS}
    for t in T.TOOLS:
        assert DONE[t.name] != t.status and DONE[t.name][:1].isupper(), t.name
    assert done_words("Trying the plan with changes") == "Tried the plan with changes"
    assert done_words("Asking for store names") == "Asked for store names"


@pytest.mark.parametrize("ms, cents, requests, line", [
    (11_200, 9, 2, "11 seconds · $0.09"), (400, 0, 1, "1 second · less than $0.01"),
    (2_600, 112, 3, "3 seconds · $1.12"), (300, 0, 0, "1 second")])
def test_the_time_and_cost_line(ms, cents, requests, line):
    assert meta_line(ms, cents, requests) == line


from steward.db.models import ChatConversation


def title_of(books, ours, cid):
    with Session(books.engine_for(ours)) as db:
        return db.get(ChatConversation, cid).title


@pytest.mark.parametrize("title, want", [("Covering a year on one income", "Covering a year on one income"),
                                         (None, "Can Person 2 and I cover"),
                                         ("Call 7145550102 about it", "Can Person 2 and I cover")])
def test_a_new_conversation_takes_gateways_title_when_it_is_safe(books, ours, household, title, want):
    gw = StubGateway(one_tool_round(), title=title)
    env = env_for(books, ours, household, gw)
    prep = start_turn(env, Q)
    list(run_turn(env, prep))
    assert gw.titled == SENT
    assert title_of(books, ours, prep.conversation_id) == want


def test_a_title_for_a_conversation_deleted_meanwhile_changes_nothing(books, ours, household):
    """Final review, finding 4: the title comes after done; a conversation gone by then is left alone, no error."""
    from dataclasses import replace

    from steward.advisor.turn import _retitle
    env = env_for(books, ours, household, StubGateway(title="Covering a year on one income"))
    prep = start_turn(env, Q)
    _retitle(env, replace(prep, conversation_id=prep.conversation_id + 1000, sent=SENT))
    assert title_of(books, ours, prep.conversation_id) == "Can Person 2 and I cover"
