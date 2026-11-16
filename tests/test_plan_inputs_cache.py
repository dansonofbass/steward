"""The built engine inputs are cached on (vault write generation, today) (controller ruling, final fix wave).
These tests pin invalidation: every write path below must force a fresh build."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from steward.db import generation
from steward.db.models import BalanceSnapshot, Child, Fact, SsEarnings, Transaction
from steward.db.directory_models import Session as AuthSession
from steward.services.plan_cache import InputsCache
from tests.factories import make_ready_household, make_user
from tests.test_ss_import import row, statement

SAMPLES = Path(__file__).parent / "samples"


def _builds(client) -> int:
    return client.app.state.books.plan_cache(client.app.state.books.book("ours").id).inputs.builds


def _preview(client) -> dict:
    r = client.post("/api/b/ours/plan/preview", json={})
    assert r.status_code == 200
    return r.json()


def _fact(c, db, accts):
    assert c.post("/api/b/ours/facts", json={"key": "health.premium_cents", "value": "1200000", "as_of": "2026-10-12"}).status_code == 201


def _child_post(c, db, accts):
    assert c.post("/api/b/ours/children", json={"label": "Youngest", "birth_year": 2020, "cost_level": "private"}).status_code == 201


def _child_patch(c, db, accts):
    kid = c.get("/api/b/ours/children").json()["children"][0]
    assert c.patch(f"/api/b/ours/children/{kid['id']}", json={"cost_level": "private"}).status_code == 200


def _child_delete(c, db, accts):
    kid = next(k for k in c.get("/api/b/ours/children").json()["children"] if k["label"] == "Middle")
    assert c.delete(f"/api/b/ours/children/{kid['id']}").status_code in (200, 204)


def _ss_import(c, db, accts):
    r = c.post("/api/b/ours/ss/import?person=spouse", content=statement(row(2010, 40000) + row(2011, 41000)),
               headers={"content-type": "application/xml"})
    assert r.status_code == 201


def _asset_class(c, db, accts):
    assert c.put("/api/b/ours/asset-classes", json={"symbol": "ZZFUNDX", "class": "bond"}).status_code == 200


def _txn_import(c, db, accts):
    from tests.import_helpers import import_file
    r = import_file(c, "chase_card.csv", accts["checking"].id, raw=(SAMPLES / "chase_card.csv").read_bytes())
    assert r.status_code == 201 and r.json()["imported"] > 0


def _txn_edit(c, db, accts):
    tid = db.scalar(select(Transaction.id).where(Transaction.raw_description == "GROCER").limit(1))
    assert c.patch(f"/api/b/ours/transactions/{tid}", json={"is_business": True}).status_code == 200


def _snapshot_in_db(c, db, accts):
    db.add(BalanceSnapshot(account_id=accts["taxable"].id, as_of=date(2026, 10, 12), balance_cents=25_000_000))
    db.commit()


def _transaction_in_db(c, db, accts):
    db.add(Transaction(account_id=accts["checking"].id, posted_at=date(2026, 9, 20), amount_cents=-1_200_000,
                       raw_description="ROOF REPAIR", category="home"))
    db.commit()


def _core_delete_in_db(c, db, accts):
    db.execute(delete(SsEarnings).where(SsEarnings.year < 2010))
    db.commit()


WRITE_PATHS = [_fact, _child_post, _child_patch, _child_delete, _ss_import, _asset_class, _txn_import, _txn_edit,
               _snapshot_in_db, _transaction_in_db, _core_delete_in_db]


@pytest.mark.parametrize("write", WRITE_PATHS, ids=lambda f: f.__name__.strip("_"))
def test_each_write_path_forces_a_fresh_build(frozen, signed_in, db, write):
    make_user(db, "sam", "sam@x.com", "Sam")
    accts = make_ready_household(db)
    db.add(Child(label="Middle", birth_year=2017, cost_level="in_state_public", monthly_contribution_cents=0))
    db.commit()
    _preview(signed_in)
    built = _builds(signed_in)
    _preview(signed_in)
    assert _builds(signed_in) == built                   # unchanged vault, same day: no rebuild
    write(signed_in, db, accts)
    _preview(signed_in)
    assert _builds(signed_in) == built + 1, write.__name__


def test_a_fresh_build_reflects_the_change(frozen, signed_in, db):
    make_user(db, "sam", "sam@x.com", "Sam")
    accts = make_ready_household(db)
    before = signed_in.get("/api/b/ours/plan").json()["inputs"]
    _transaction_in_db(signed_in, db, accts)
    _fact(signed_in, db, accts)
    after = signed_in.get("/api/b/ours/plan").json()["inputs"]
    assert after["spending_basis_cents"] == before["spending_basis_cents"] + 1_200_000
    assert after["facts_as_of"]["health.premium_cents"] == "2026-10-12"


def test_the_day_turning_forces_a_fresh_build(frozen, signed_in, db, monkeypatch):
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    _preview(signed_in)
    built = _builds(signed_in)
    monkeypatch.setattr("steward.clock.today", lambda: date(2026, 10, 14))
    _preview(signed_in)
    assert _builds(signed_in) == built + 1


def test_signing_in_and_previewing_do_not_bump_the_generation(frozen, signed_in, db):
    """Every signed-in request writes the auth session's last_seen_at; that must not invalidate the cache."""
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    _preview(signed_in)
    g = generation.current()
    for _ in range(3):
        _preview(signed_in)
        signed_in.get("/api/b/ours/plan")
    assert generation.current() == g


def test_generation_marks_commits_and_ignores_rollbacks(engine, ddb):
    with Session(engine) as s:
        g = generation.current()
        s.add(Fact(key="state", value="CA", as_of=date(2026, 1, 1)))
        s.flush()
        s.rollback()
        assert generation.current() == g                 # nothing reached the vault
        s.add(Fact(key="state", value="CA", as_of=date(2026, 1, 1)))
        s.flush()
        try:
            with s.begin_nested():
                s.add(Fact(key="state", value="OR", as_of=date(2026, 1, 2)))
                raise ValueError
        except ValueError:
            pass
        s.commit()                                       # a savepoint rollback must not drop the earlier change
        assert generation.current() == g + 1
        s.commit()
        assert generation.current() == g + 1             # a commit with nothing flushed does not bump
        ddb.execute(delete(AuthSession))
        ddb.commit()
        assert generation.current() == g + 1             # the auth sessions table is ignored


def test_inputs_cache_is_thread_safe_and_never_keeps_a_build_that_raced_a_write():
    cache: InputsCache = InputsCache()
    day = date(2026, 10, 13)

    def racing_build():
        generation.bump()                                # a write commits while this build runs
        return "old"
    assert cache.get_or_build(day, racing_build) == "old"
    assert cache.get_or_build(day, lambda: "new") == "new"   # the racing build was keyed on the old generation
    with ThreadPoolExecutor(8) as ex:
        values = list(ex.map(lambda _: cache.get_or_build(day, lambda: "unused"), range(200)))
    assert values == ["new"] * 200 and cache.builds == 2


def test_the_home_visit_stamp_keeps_plans_inputs(frozen, signed_in, db):
    """Phase 18: Home's visit stamp (POST /home/seen) is no input of the plan, yet it rebuilt Plan's inputs on every
    Home → Plan."""
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    _preview(signed_in)
    builds = _builds(signed_in)
    mark = signed_in.get("/api/b/ours/home").json()["mark"]
    assert signed_in.post("/api/b/ours/home/seen", json={"mark": mark, "glance": False}).status_code == 204
    _preview(signed_in)
    assert _builds(signed_in) == builds


def test_another_books_writes_keep_this_books_inputs(engine, books, ours, margaret):
    """Phase 18: a write in another book (Margaret's, Diane's) rebuilt this book's inputs. A session that names no book
    (a script, the scheduler's sync, the directory) still rebuilds every book's."""
    from steward.events import log_event
    cache = books.plan_cache(ours.id)
    day = date(2026, 10, 13)
    assert cache.inputs.get_or_build(day, lambda: "built") == "built"
    with Session(books.engine_for(margaret)) as s:          # a request session in Margaret's book
        s.info[generation.BOOK] = margaret.id
        log_event(s, "info", "test", "her book changed")
        s.commit()
    assert cache.inputs.get_or_build(day, lambda: "again") == "built"
    with Session(engine) as s:                               # names no book
        log_event(s, "info", "test", "anything")
        s.commit()
    assert cache.inputs.get_or_build(day, lambda: "again") == "again"


def test_a_books_request_sessions_name_their_book(frozen, signed_in, db, books, ours):
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    unscoped, mine = generation.current(ours.id)
    assert signed_in.post("/api/b/ours/facts", json={"key": "health.premium_cents", "value": "1200000",
                                                     "as_of": "2026-10-12"}).status_code == 201
    after_unscoped, after_mine = generation.current(ours.id)
    assert after_unscoped == unscoped and after_mine > mine     # ours moved; nothing that names no book did
