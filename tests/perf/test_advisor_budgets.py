"""Spec 12, the NAS's share: the exact pass, each tool over 5 years of synthetic data, the plan tools cached and not,
lever impacts, recording a part, the time Steward adds before the first Anthropic byte, and the preview round trip.
Run: uv run pytest -q -m perf tests/perf/test_advisor_budgets.py (STEWARD_PERF_FACTOR=2.5 approximates the NAS)."""
import os
import statistics
import time
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from steward.advisor.identifiers import Identifier
from steward.advisor.outgoing import record_parts
from steward.advisor.redact import exact_redact
from steward.advisor.state import set_chat_on
from steward.advisor.turn import AskEnv, run_turn, start_turn
from steward.app import create_app
from steward.demo import seed, seed_people
from steward.services.plan_cache import PlanCache
from steward_boundary.canonical import canonical, sha256_hex
from tests.advisor.helpers import call
from tests.advisor.rig import gateway_rig
from tests.factories import login
from tests.gateway.fake_anthropic import Reply, text

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
TODAY = date(2026, 10, 13)
NOW = datetime(2026, 10, 13, 19, tzinfo=timezone.utc)
FIRST = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hazel", "Ivy", "Juniper"]
LAST = ["Ashgrove", "Brookfield", "Copperton", "Dunmere", "Elsworth"]


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


def _p95(times):
    return sorted(times)[max(0, int(len(times) * 0.95) - 1)]


def test_exact_pass_over_1000_characters_with_50_names_under_20_ms():
    names = [f"{f} {l}" for f in FIRST for l in LAST]
    idents = [Identifier(n, "name", f"Person {i + 3}", True) for i, n in enumerate(names)]
    idents += [Identifier(n.split()[1], "name", f"Person {i + 3}") for i, n in enumerate(names)]
    text = (f"Did {names[7]} pay $812.40 for groceries in 2025, and is the 401(k) up 4% from last year? " * 20)[:1000]
    exact_redact(text, idents)
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        exact_redact(text, idents)
        times.append((time.perf_counter() - t0) * 1000)
    _check("exact_pass_1000_50_names", statistics.median(times) * FACTOR, 20)


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    from steward.books.registry import open_books
    from steward.db.keys import ensure_key
    from steward.settings import Settings
    d = tmp_path_factory.mktemp("advisor-perf")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(d))
        mp.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
        mp.setenv("STEWARD_ENV", "test")
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    ours = books.book("ours")
    with Session(books.engine_for(ours)) as db:
        seed(db, years=5, seed=11)
        set_chat_on(db, True, None, NOW)
        db.commit()
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    people = books.people(ours.id)
    yield s, books, ours, people, next(p.id for p in people if p.username == "alex")
    books.dispose()


TOOLS = {"book_summary": {}, "accounts": {"include_closed": True}, "balance_history": {"months": 60, "by_account_type": True},
         "cash_flow": {"months": 60, "by": "category"}, "recurring": {}, "holdings": {}, "debts": {}, "facts": {},
         "spending_by_category": {"start": "2025-10-14", "end": "2026-10-13", "compare_previous": True},
         "savings_checklist": {}}


PARENT_TOOLS = {"inventory": {"kind": None}, "money_in_monthly": {"months": 24}, "premiums": {},
                "flags": {"include_done": True}, "care_projection": {}}


@pytest.fixture(scope="module")
def big_parent(tmp_path_factory):
    """Margaret's book: the seed's six months plus synthetic rows back five years, income and premiums included."""
    from sqlalchemy import select

    from steward.books.registry import open_books
    from steward.books.service import create_book
    from steward.db.keys import ensure_key
    from steward.demo_parent import seed_parent
    from steward.demo_care import seed_care
    from steward.demo_watching import seed_watching
    from steward.db.models import Account, CategorySource, Transaction
    from steward.settings import Settings
    from tests.factories import make_person
    d = tmp_path_factory.mktemp("advisor-perf-parent")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(d))
        mp.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
        mp.setenv("STEWARD_ENV", "test")
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    with Session(books.directory) as ddb:
        book = create_book(books, ddb, name="Margaret Ellis", kind="parent",
                           owner_labels=["Margaret", "Robert (husband)", "Joint"])
        make_person(ddb, "jr", [(book.id, "manager")])
    people = books.people(book.id)
    jr = next(p.id for p in people if p.username == "jr")
    with Session(books.engine_for(book)) as db:
        seed_parent(db, TODAY, by=jr)
        seed_watching(db, TODAY, by=jr)
        seed_care(db, TODAY)
        chk = db.scalar(select(Account).where(Account.name == "Joint checking"))
        month_rows = (("SSA TREAS 310 XXSOC SEC", 214000), ("COUNTY SCHOOLS RET PENSION", 138500),
                      ("EVERGREEN MUTUAL LTC PREM", -21200), ("CLEARPATH RX PART D PREM", -3840),
                      ("GLOBE MUTUAL MEDSUPP PREM", -18620), ("SOUTHERN CALIFORNIA EDISON", -9000))
        for back in range(7, 60):
            y, m = divmod(TODAY.year * 12 + TODAY.month - 1 - back, 12)
            for i, (raw, cents) in enumerate(month_rows):
                db.add(Transaction(account_id=chk.id, posted_at=date(y, m + 1, 3 + i * 4), amount_cents=cents,
                                   raw_description=raw, category="synthetic", category_source=CategorySource.rule))
            for day in range(1, 29, 2):
                db.add(Transaction(account_id=chk.id, posted_at=date(y, m + 1, day), amount_cents=-(1500 + day * 37),
                                   raw_description=f"STATER BROS {day}", category="groceries",
                                   category_source=CategorySource.rule))
        db.commit()
    yield books, book, people, jr
    books.dispose()


@pytest.mark.parametrize("name", sorted(PARENT_TOOLS))
def test_each_parent_tool_over_5_years_under_200_ms_p95(big_parent, name):
    books, book, people, jr = big_parent
    engine = books.engine_for(book)
    call(engine, book, people, jr, name, PARENT_TOOLS[name], TODAY)
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        out = call(engine, book, people, jr, name, PARENT_TOOLS[name], TODAY)
        times.append((time.perf_counter() - t0) * 1000)
        assert out["error"] is None, out
    _check(f"parent_tool_{name}", _p95(times) * FACTOR, 200)


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_each_tool_over_5_years_under_200_ms_p95(big, name):
    s, books, ours, people, jr = big
    engine = books.engine_for(ours)
    call(engine, ours, people, jr, name, TOOLS[name], TODAY)
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        out = call(engine, ours, people, jr, name, TOOLS[name], TODAY)
        times.append((time.perf_counter() - t0) * 1000)
        assert out["error"] is None
    _check(f"tool_{name}", _p95(times) * FACTOR, 200)


def test_plan_tools_cached_and_uncached(big):
    s, books, ours, people, jr = big
    engine = books.engine_for(ours)
    levers = {}
    uncached = []
    for i in range(3):
        t0 = time.perf_counter()
        call(engine, ours, people, jr, "plan_what_if", {"levers": {**levers, "save_more_monthly_cents": 10_000 * (i + 1)}},
             TODAY, PlanCache())
        uncached.append((time.perf_counter() - t0) * 1000)
    _check("plan_what_if_uncached", statistics.median(uncached) * FACTOR, 600)
    fresh = []
    for _ in range(3):
        t0 = time.perf_counter()
        call(engine, ours, people, jr, "plan_result", {}, TODAY, PlanCache())
        fresh.append((time.perf_counter() - t0) * 1000)
    _check("plan_result_uncached", statistics.median(fresh) * FACTOR, 600)
    cache = PlanCache()
    what_if = {"levers": {**levers, "save_more_monthly_cents": 20_000}}
    call(engine, ours, people, jr, "plan_what_if", what_if, TODAY, cache)
    warm = []
    for _ in range(20):
        t0 = time.perf_counter()
        call(engine, ours, people, jr, "plan_what_if", what_if, TODAY, cache)
        warm.append((time.perf_counter() - t0) * 1000)
    _check("plan_what_if_cached", _p95(warm) * FACTOR, 100)
    call(engine, ours, people, jr, "plan_result", {}, TODAY, cache)
    cached = []
    for _ in range(20):
        t0 = time.perf_counter()
        call(engine, ours, people, jr, "plan_result", {}, TODAY, cache)
        cached.append((time.perf_counter() - t0) * 1000)
    _check("plan_result_cached", _p95(cached) * FACTOR, 100)
    t0 = time.perf_counter()
    call(engine, ours, people, jr, "plan_lever_impacts", {}, TODAY, cache)
    _check("plan_lever_impacts", (time.perf_counter() - t0) * 1000 * FACTOR, 3000)


def test_recording_a_part_under_50_ms(big):
    s, books, ours, people, jr = big
    payload = {"tool_use_id": "toolu_1", "name": "accounts", "is_error": False,
               "content": {"accounts": [{"account": f"Account {i}"} for i in range(800)]}}
    part = {"part": "tool_result", "payload": payload, "sha256": sha256_hex(payload), "bytes": len(canonical(payload))}
    times = []
    for i in range(20):
        t0 = time.perf_counter()
        with Session(books.engine_for(ours).execution_options(immediate=True)) as db:
            record_parts(db, user_id=jr, conversation_id=None, turn_id=f"t_{i:016x}", seq=1, channel="chat", model=None,
                         parts=[part], now=NOW)
            db.commit()
        times.append((time.perf_counter() - t0) * 1000)
    _check("record_part", statistics.median(times) * FACTOR, 50)


def test_time_added_before_the_first_anthropic_byte_under_400_ms(tmp_path, big):
    s, books, ours, people, jr = big
    arrived = []
    with gateway_rig(tmp_path, lambda body, n: arrived.append(time.perf_counter()) or Reply([text("ok")])) as rig:
        env = AskEnv(bind=books.engine_for(ours).execution_options(immediate=True), directory=books.directory, book=ours,
                     user_id=jr, people=lambda: books.people(ours.id), plan_cache=books.plan_cache(ours.id),
                     gateway=rig.client, now=lambda: NOW, today=lambda: TODAY)
        times = []
        for i in range(5):
            t0 = time.perf_counter()
            list(run_turn(env, start_turn(env, f"How much did we spend on dining in month {i + 1}?")))
            times.append((arrived[-1] - t0) * 1000)
    _check("before_first_anthropic_byte", statistics.median(times) * FACTOR, 400)


def test_preview_round_trip_under_250_ms_p95(tmp_path, big):
    s, books, ours, people, jr = big
    question = ("Are we spending more on dining than last year, and did the 401(k) contribution go up? " * 12)[:1000]
    with gateway_rig(tmp_path, lambda body, n: Reply([text("ok")])) as rig, \
            TestClient(create_app(s, books, gateway=rig.client), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "alex", "pw-demo-alex-2026")
        c.post("/api/b/ours/chat/preview", json={"text": question})
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = c.post("/api/b/ours/chat/preview", json={"text": question})
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
    _check("preview_round_trip", _p95(times) * FACTOR, 250)
def test_conversation_list_with_200_conversations_under_150_ms(big):
    from steward.db.models import AdvisorOutgoing, ChatConversation, ChatTurn
    from tests.advisor.stubs import StubGateway
    s, books, ours, people, jr = big
    with Session(books.engine_for(ours)) as db:
        for i in range(200):
            conv = ChatConversation(user_id=jr, title=f"Question about spending {i}", created_at=NOW, updated_at=NOW,
                                    last_input_tokens=0)
            db.add(conv)
            db.flush()
            for j in range(3):
                tid = f"t_{i:08x}{j:08x}"
                db.add(ChatTurn(conversation_id=conv.id, turn_id=tid, user_id=jr, asked="How much?", sent="How much?",
                                started_at=NOW, store_rows=1 if j == 0 and i % 10 == 0 else 0))
                db.add(AdvisorOutgoing(at=NOW, user_id=jr, conversation_id=conv.id, turn_id=tid, seq=1, channel="chat",
                                       part="question", payload='{"text":"How much?"}', sha256="0" * 64, bytes=20))
        db.commit()
    with TestClient(create_app(s, books, gateway=StubGateway()), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "alex", "pw-demo-alex-2026")
        assert len(c.get("/api/b/ours/chat/conversations").json()["conversations"]) == 200
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = c.get("/api/b/ours/chat/conversations")
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
    _check("conversation_list_200", _p95(times) * FACTOR, 150)
