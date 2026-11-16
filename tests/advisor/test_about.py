"""What a question is about (Ask about this, Privacy tests): the request is exactly one shape; each kind builds only
its allowed fields, in each book it applies to; the seeded free text never reaches the wire or the line; a kind the
book doesn't have, a month outside the book and a row that's gone are refused."""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.advisor.about import AboutGone, AboutIn, AboutRefused, parse_about, resolve
from steward.advisor.aliases import Aliases
from steward.advisor.state import set_chat_on
from steward.advisor.tools.parent import flag_day
from steward.db.directory_models import User
from steward.db.models import AdvisorAlias, CareScenario, Flag, TransactionNote
from steward_boundary.about import about_text
from steward_boundary.protocol import ABOUT, check_frame
from tests.factories import make_account, make_person, make_txn

TODAY = date(2026, 10, 30)
ON_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)
ALLOWED = {"account": {"kind", "account"}, "category": {"kind", "category", "month"}, "plan": {"kind"},
           "transaction": {"kind", "date", "amount_cents", "category", "account"}, "flag": {"kind", "check", "date"},
           "care": {"kind"}, "scenario": {"kind", "scenario", "level"}}
# Every word the seeded free text holds that a typed value never would.
SEEDED = ("zorblax", "Alvarez", "StreamBox", "STREAMBOX", "4417", "Margaret", "Ralphs", "CVS", "Pharmacy", "500.00",
          "Calling")


@pytest.fixture
def people(margaret, ours, ddb):
    """jr manages ours and Margaret Ellis (the margaret fixture), vee views Margaret Ellis, kai views ours."""
    make_person(ddb, "kai", [(ours.id, "viewer")])
    return {u: ddb.scalar(select(User.id).where(User.username == u)) for u in ("jr", "vee", "kai")}


@pytest.fixture
def house(books, ours, people):
    """Ours, chat on, with an account named after a person and a row holding a nickname, a store, raw bank text with
    digits and a note."""
    with Session(books.engine_for(ours)) as db:
        acct = make_account(db, name="Alvarez Checking")
        t = make_txn(db, acct, date(2026, 10, 16), -1599, "STREAMBOX 4417", merchant="StreamBox",
                     category="subscriptions")
        t.nickname = "zorblax"
        db.add(TransactionNote(transaction_id=t.id, author_id=people["jr"], author_name="Jr",
                               body="zorblax for Dr. Alvarez", created_at=datetime(2026, 10, 17, tzinfo=timezone.utc)))
        set_chat_on(db, True, people["jr"], ON_AT)
        db.commit()
        return {"account": acct.id, "transaction": t.id}


@pytest.fixture
def mom(books, margaret, people):
    """Margaret Ellis, chat on, with a flagged row whose title, summary and note all hold free text, and two care
    scenarios stored out of id order."""
    with Session(books.engine_for(margaret)) as db:
        acct = make_account(db, name="Margaret Checking")
        t = make_txn(db, acct, date(2026, 10, 14), -12_345, "CVS PHARMACY 0042", merchant="CVS Pharmacy",
                     category="health")
        f = Flag(check="large", severity="normal", status="checking", transaction_id=t.id,
                 summary="$500.00 gift card at CVS Pharmacy", title="Two trips to Ralphs",
                 note="Calling Margaret this morning", created_at=datetime(2026, 10, 15, tzinfo=timezone.utc))
        db.add(f)
        db.add_all([CareScenario(position=2, level="assisted_living"), CareScenario(position=1, level="in_home_help")])
        set_chat_on(db, True, people["jr"], ON_AT)
        db.commit()
        scenarios = list(db.scalars(select(CareScenario.id).order_by(CareScenario.position)))
        return {"flag": f.id, "transaction": t.id, "scenarios": scenarios}


def _resolve(books, book, about: AboutIn) -> dict:
    with Session(books.engine_for(book)) as db:
        out = resolve(db, book, Aliases(db, book, books.people(book.id), save=False), about, TODAY)
        db.rollback()
        return out


def test_parse_takes_each_request_shape():
    assert parse_about(None) is None
    assert parse_about({"kind": "account", "id": 12}) == AboutIn("account", 12)
    assert parse_about({"kind": "transaction", "id": 345}) == AboutIn("transaction", 345)
    assert parse_about({"kind": "flag", "id": 7}) == AboutIn("flag", 7)
    assert parse_about({"kind": "category", "category": "dining", "month": "2026-10"}) == \
        AboutIn("category", None, "dining", "2026-10")
    assert parse_about({"kind": "plan"}) == AboutIn("plan")
    assert parse_about({"kind": "care"}) == AboutIn("care")
    assert parse_about({"kind": "care", "id": 3}) == AboutIn("care", 3)


@pytest.mark.parametrize("raw", [
    {"kind": "account", "id": 1, "label": "Alvarez Checking"}, {"kind": "plan", "note": "zorblax"},
    {"kind": "category", "category": "dining", "month": "2026-10", "name": "Sam"},
    {"kind": "category", "category": "Eating out", "month": "2026-10"},
    {"kind": "category", "category": "dining", "month": "October"}, {"kind": "category", "category": "dining"},
    {"kind": "account", "id": "12"}, {"kind": "account", "id": True}, {"kind": "account", "id": 0},
    {"kind": "account"}, {"kind": "transaction", "id": 2**40}, {"kind": "plan", "id": 1}, {"kind": "nickname"},
    {"kind": []}, {"kind": {"a": 1}},
    {"id": 1}, "account:12", [], 7,
], ids=str)
def test_parse_refuses_anything_but_one_request_shape(raw):
    with pytest.raises(AboutRefused) as e:
        parse_about(raw)
    assert e.value.message == "That request wasn't understood."


def test_each_household_kind_builds_only_its_fields(books, ours, house):
    cases = {"account": AboutIn("account", house["account"]), "transaction": AboutIn("transaction", house["transaction"]),
             "category": AboutIn("category", category="dining", month="2026-10"), "plan": AboutIn("plan")}
    for kind, about in cases.items():
        wire = _resolve(books, ours, about)
        assert set(wire) == ALLOWED[kind] and check_frame(ABOUT, wire) == [], kind
    tx = _resolve(books, ours, cases["transaction"])
    assert tx == {"kind": "transaction", "date": "2026-10-16", "amount_cents": -1599, "category": "subscriptions",
                  "account": tx["account"]}
    assert tx["account"].startswith("Account ")
    assert _resolve(books, ours, cases["account"]) == {"kind": "account", "account": tx["account"]}


def test_each_parent_kind_builds_only_its_fields(books, margaret, mom):
    assert _resolve(books, margaret, AboutIn("flag", mom["flag"])) == {"kind": "flag", "check": "large",
                                                                       "date": "2026-10-14"}   # the row's day (P16)
    assert _resolve(books, margaret, AboutIn("care")) == {"kind": "care"}
    first, second = mom["scenarios"]
    assert _resolve(books, margaret, AboutIn("care", first)) == {"kind": "care", "scenario": 1, "level": "in_home_help"}
    assert _resolve(books, margaret, AboutIn("care", second)) == {"kind": "care", "scenario": 2,
                                                                  "level": "assisted_living"}
    assert set(_resolve(books, margaret, AboutIn("transaction", mom["transaction"]))) == ALLOWED["transaction"]


def test_the_flag_day_is_the_rows_day_then_the_due_day_then_the_household_day_it_was_made():
    made = datetime(2026, 10, 20, 6, tzinfo=timezone.utc)          # 11 pm on Oct 19 in California
    assert flag_day(date(2026, 10, 14), date(2026, 10, 9), made) == date(2026, 10, 14)
    assert flag_day(None, date(2026, 10, 9), made) == date(2026, 10, 9)
    assert flag_day(None, None, made) == date(2026, 10, 19)


def test_the_seeded_free_text_never_reaches_the_wire_or_the_line(books, ours, house, margaret, mom):
    for book, about in ((ours, AboutIn("account", house["account"])), (ours, AboutIn("transaction", house["transaction"])),
                        (ours, AboutIn("category", category="subscriptions", month="2026-10")), (ours, AboutIn("plan")),
                        (margaret, AboutIn("flag", mom["flag"])), (margaret, AboutIn("transaction", mom["transaction"])),
                        (margaret, AboutIn("care")), (margaret, AboutIn("care", mom["scenarios"][0]))):
        wire = _resolve(books, book, about)
        text = (json.dumps(wire) + " " + about_text(wire)).casefold()
        assert [w for w in SEEDED if w.casefold() in text] == [], about


@pytest.mark.parametrize("about", [AboutIn("flag", 1), AboutIn("care"), AboutIn("care", 1)], ids=str)
def test_a_household_book_refuses_parent_kinds(books, ours, house, about):
    with pytest.raises(AboutRefused):
        _resolve(books, ours, about)


@pytest.mark.parametrize("about", [AboutIn("account", 1), AboutIn("plan"),
                                   AboutIn("category", category="dining", month="2026-10")], ids=str)
def test_a_parent_book_refuses_household_kinds(books, margaret, mom, about):
    with pytest.raises(AboutRefused):
        _resolve(books, margaret, about)


def test_a_row_that_is_gone(books, ours, house, margaret, mom):
    for book, about in ((ours, AboutIn("transaction", 99_999)), (ours, AboutIn("account", 99_999)),
                        (margaret, AboutIn("flag", 99_999)), (margaret, AboutIn("care", 99_999))):
        with pytest.raises(AboutGone) as e:
            _resolve(books, book, about)
        assert e.value.message == "That isn't in this book any more."


def test_a_month_outside_the_book_is_refused(books, ours, house):
    """From the book's first month (its oldest row is in October 2026 here) to this month."""
    assert _resolve(books, ours, AboutIn("category", category="dining", month="2026-10"))["month"] == "2026-10"
    for month in ("2026-09", "2026-11", "2099-01"):
        with pytest.raises(AboutRefused):
            _resolve(books, ours, AboutIn("category", category="dining", month=month))


def test_a_book_whose_first_row_is_after_today_still_takes_this_month(books, ours, people):
    """Argon follow-up 5: a book whose only row is dated after today (a scheduled payment) had an empty range, so every
    category was refused. The first month is clamped to this one, as Spending's is."""
    with Session(books.engine_for(ours)) as db:
        make_txn(db, make_account(db), date(2026, 12, 3), -5000, "RENT", category="housing")
        db.commit()
    assert _resolve(books, ours, AboutIn("category", category="housing", month="2026-10"))["month"] == "2026-10"
    for month in ("2026-09", "2026-11", "2026-12"):
        with pytest.raises(AboutRefused):
            _resolve(books, ours, AboutIn("category", category="housing", month=month))



# The routes (Ask about this, API): POST /chat/about, /ask with an about, the turns' "About" and the sent log's label.
from fastapi.testclient import TestClient  # noqa: E402

from steward.app import create_app  # noqa: E402
from steward.db.models import ChatTurn  # noqa: E402
from steward_boundary import PROTOCOL  # noqa: E402
from tests.advisor.stubs import StubGateway, part  # noqa: E402
from tests.factories import login  # noqa: E402

CHAT = "/api/b/ours/chat"
Q = "How much is in savings?"
CTX = "Today is Friday, October 30, 2026. This is a household book. The person asking is Person 1."
OFF = "Chat is off for this book. A manager can turn it on in Settings → Chat."


def nas(settings, books, gw=None) -> TestClient:
    return TestClient(create_app(settings, books, gateway=gw or StubGateway()), base_url="https://nas.tail1234.ts.net")


def answered(text="Account 1 holds $14,500.00."):
    """One turn's frames from the gateway, as tests/advisor/test_chat_api.py scripts them."""
    user = {"role": "user", "content": [{"type": "text", "text": Q}]}
    system = {"role": "system", "content": CTX}
    assistant = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    return [{"type": "redacted", "text": Q, "edits": []},
            {"type": "record", "seq": 1, "parts": [part("question", {"text": Q}), part("system", {"text": CTX})]},
            {"type": "sent", "messages": [{"message": user, "mac": "a" * 64}, {"message": system, "mac": "b" * 64}]},
            {"type": "text", "delta": text},
            {"type": "assistant", "message": assistant, "mac": "c" * 64, "model": "claude-opus-5-5", "usage": {}},
            {"type": "done", "stop": "end_turn", "line": None, "check": None, "path": None, "requests": 1,
             "cost_nd": 90_000_000, "last_input_tokens": 5000}]


def test_about_answers_each_kind_for_managers_and_viewers(settings, books, margaret, people, house, mom):
    m = f"/api/b/{margaret.slug}/chat"
    asks = [(CHAT, {"kind": "account", "id": house["account"]}), (CHAT, {"kind": "transaction", "id": house["transaction"]}),
            (CHAT, {"kind": "category", "category": "subscriptions", "month": "2026-10"}), (CHAT, {"kind": "plan"}),
            (m, {"kind": "flag", "id": mom["flag"]}), (m, {"kind": "transaction", "id": mom["transaction"]}),
            (m, {"kind": "care"}), (m, {"kind": "care", "id": mom["scenarios"][1]})]
    with nas(settings, books) as c:
        for who, theirs in (("jr", (CHAT, m)), ("kai", (CHAT,)), ("vee", (m,))):
            login(c, who)
            for base, about in asks:
                if base not in theirs:
                    continue
                r = c.post(f"{base}/about", json={"about": about})
                assert r.status_code == 200, (who, about, r.json())
                out = r.json()
                assert set(out) == {"about", "sent", "chips", "labels"} and out["sent"] == about_text(out["about"])
                text = json.dumps({k: out[k] for k in ("about", "sent", "chips")}).casefold()
                assert [w for w in SEEDED if w.casefold() in text] == [], (who, about)


def test_the_account_chip_marks_its_alias_and_only_labels_carry_the_name(settings, books, people, house):
    with nas(settings, books) as c:
        login(c, "jr")
        out = c.post(f"{CHAT}/about", json={"about": {"kind": "account", "id": house["account"]}}).json()
    alias = out["about"]["account"]
    assert out["sent"] == f"It's about {alias}."
    assert out["chips"] == [{"start": 11, "end": 11 + len(alias), "label": alias, "layer": "alias"}]
    assert list(out["labels"]) == [alias] and "Alvarez" in out["labels"][alias]


def test_about_works_while_away_and_refuses_when_chat_is_off(settings, books, people, house):
    """P8: no gateway call, so the chip shows while the gateway is away. P31: chat turned off elsewhere is 409."""
    with nas(settings, books, StubGateway(away=True)) as c:
        login(c, "jr")
        assert c.post(f"{CHAT}/about", json={"about": {"kind": "plan"}}).status_code == 200
        c.post(f"{CHAT}/on", json={"on": False})
        r = c.post(f"{CHAT}/about", json={"about": {"kind": "plan"}})
        assert (r.status_code, r.json()) == (409, {"error": OFF})


@pytest.mark.parametrize("body, status", [
    ({"about": {"kind": "account", "id": 1, "label": "Alvarez Checking"}}, 422),
    ({"about": {"kind": "plan", "note": "zorblax"}}, 422),
    ({"about": {"kind": "category", "category": "dining", "month": "2026-10", "name": "Sam"}}, 422),
    ({"about": {"kind": "flag", "id": 1}}, 422),                       # a parent book's kind
    ({"about": {"kind": "category", "category": "dining", "month": "2099-01"}}, 422),
    ({"about": {"kind": "transaction", "id": 99_999}}, 404),
    ({"about": None}, 422), ({}, 422), ({"about": {"kind": "plan"}, "label": "x"}, 422),
], ids=str)
def test_about_refuses_what_it_doesnt_take(settings, books, people, house, body, status):
    with nas(settings, books) as c:
        login(c, "jr")
        r = c.post(f"{CHAT}/about", json=body)
    assert r.status_code == status
    assert r.json() == {"error": "That isn't in this book any more." if status == 404 else "That request wasn't understood."}


def test_a_parent_book_refuses_the_plan(settings, books, margaret, people, mom):
    with nas(settings, books) as c:
        login(c, "jr")
        assert c.post(f"/api/b/{margaret.slug}/chat/about", json={"about": {"kind": "plan"}}).status_code == 422


def test_a_question_carries_its_about_into_the_context_the_issued_tokens_and_the_turn(settings, books, ours, people,
                                                                                         house):
    gw = StubGateway(answered())
    about = {"kind": "account", "id": house["account"]}
    with nas(settings, books, gw) as c:
        login(c, "jr")
        chip = c.post(f"{CHAT}/about", json={"about": about}).json()["about"]
        r = c.post(f"{CHAT}/ask", json={"question": Q, "conversation_id": None, "about": about})
        assert r.status_code == 200 and json.loads(r.text.splitlines()[-1])["stop"] == "end_turn"
    start = next(f for f in gw.ws.sent if f["type"] == "start")
    assert start["protocol"] == PROTOCOL
    assert start["context"]["about"] == chip                    # the alias the chip showed is the one that goes
    assert chip["account"] in start["issued"]
    with Session(books.engine_for(ours)) as db:
        assert json.loads(db.scalar(select(ChatTurn.about))) == chip


def test_a_forged_or_stale_about_is_refused_before_anything_starts(settings, books, ours, people, house):
    gw = StubGateway(answered())
    with nas(settings, books, gw) as c:
        login(c, "jr")
        for about, status in (({"kind": "account", "id": house["account"], "label": "Alvarez Checking"}, 422),
                              ({"kind": "transaction", "id": 99_999}, 404),       # merged away since the chip
                              ({"kind": "care"}, 422)):
            r = c.post(f"{CHAT}/ask", json={"question": Q, "about": about})
            assert r.status_code == status, about
    assert gw.connects == 0
    with Session(books.engine_for(ours)) as db:
        assert db.scalar(select(func.count()).select_from(ChatTurn)) == 0


def test_a_follow_up_carries_its_own_about_or_none_and_both_show(settings, books, ours, people, house):
    gw = StubGateway(answered() + answered())
    about = {"kind": "category", "category": "subscriptions", "month": "2026-10"}
    with nas(settings, books, gw) as c:
        login(c, "jr")
        first = [json.loads(x) for x in c.post(f"{CHAT}/ask", json={"question": Q, "about": about}).text.splitlines()]
        cid = first[0]["id"]
        c.post(f"{CHAT}/ask", json={"question": Q, "conversation_id": cid})
        view = c.get(f"{CHAT}/conversations/{cid}").json()
        details = [c.get(f"{CHAT}/sent/{r['key']}").json() for r in c.get(f"{CHAT}/sent").json()["requests"]]
    line = "It's about Subscriptions (category subscriptions) in October 2026."
    assert [t["about"] for t in view["turns"]] == [{"chip": about, "sent": line}, None]
    starts = [f for f in gw.ws.sent if f["type"] == "start"]
    assert starts[0]["context"]["about"] == about and "about" not in starts[1]["context"]
    labels = sorted(next(p["label"] for p in d["parts"] if p["part"] == "system") for d in details)
    assert labels == ["Today's date and who is asking", "Today's date, who is asking and what it's about"]


def test_the_preview_numbers_accounts_as_the_turn_does_whichever_is_asked_about(settings, books, ours, people, house):
    """Argon follow-up 2: with no saved aliases, asking about the second account first gave it Account 1 in /about and
    in the turn, while /preview (load_identifiers, in id order) gave Account 1 to the first. Accounts are numbered in id
    order whoever asks first, so the chip and the preview are what is sent and saved."""
    with Session(books.engine_for(ours)) as db:
        second = make_account(db, name="Bluebird Savings").id
        db.commit()
    question = "Should I move money from Alvarez Checking to Bluebird Savings?"
    about = {"kind": "account", "id": second}
    gw = StubGateway(answered())
    with nas(settings, books, gw) as c:
        login(c, "jr")
        chip = c.post(f"{CHAT}/about", json={"about": about}).json()
        preview = c.post(f"{CHAT}/preview", json={"text": question}).json()
        r = c.post(f"{CHAT}/ask", json={"question": question, "conversation_id": None, "about": about})
        assert r.status_code == 200
    start = next(f for f in gw.ws.sent if f["type"] == "start")
    assert chip["about"] == start["context"]["about"] == {"kind": "account", "account": "Account 2"}
    assert preview["text"] == start["question"] == "Should I move money from Account 1 to Account 2?"
    assert "Bluebird" in preview["labels"]["Account 2"] and "Alvarez" in preview["labels"]["Account 1"]
    with Session(books.engine_for(ours)) as db:
        saved = dict(db.execute(select(AdvisorAlias.target, AdvisorAlias.alias).where(AdvisorAlias.kind == "account")).all())
    assert saved == {str(house["account"]): "Account 1", str(second): "Account 2"}


def test_aliases_number_accounts_in_id_order_whichever_is_asked_for_first(books, ours, house):
    with Session(books.engine_for(ours)) as db:
        second = make_account(db, name="Bluebird Savings").id
        db.commit()
        aliases = Aliases(db, ours, books.people(ours.id), save=False)
        assert aliases.account(second) == "Account 2" and aliases.account(house["account"]) == "Account 1"
        third = make_account(db, name="Credit Union Card").id
        assert aliases.account(third) == "Account 3"        # one made after the others were numbered
        db.rollback()


def test_saved_account_aliases_keep_their_numbers_and_new_ones_continue_from_the_highest(books, ours, house):
    with Session(books.engine_for(ours)) as db:
        second = make_account(db, name="Bluebird Savings").id
        third = make_account(db, name="Credit Union Card").id
        db.add(AdvisorAlias(kind="account", target=str(second), alias="Account 4"))
        db.commit()
        aliases = Aliases(db, ours, books.people(ours.id))
        assert aliases.account(third) == "Account 6"
        assert aliases.account(second) == "Account 4" and aliases.account(house["account"]) == "Account 5"
        db.commit()
        saved = dict(db.execute(select(AdvisorAlias.target, AdvisorAlias.alias).where(AdvisorAlias.kind == "account")).all())
    assert saved == {str(house["account"]): "Account 5", str(second): "Account 4", str(third): "Account 6"}
