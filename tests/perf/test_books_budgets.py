"""Spec 12, the plan-1 budgets. Run with: uv run pytest -q -m perf tests/perf/test_books_budgets.py
(STEWARD_PERF_FACTOR=2.5 on a dev box approximates the NAS)."""
import os
import statistics
import time

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
BASE = "https://nas.tail1234.ts.net"


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


@pytest.fixture
def four_books(tmp_path):
    from steward.books.registry import open_books
    from steward.books.service import create_book
    from steward.db.keys import ensure_key
    from steward.settings import Settings
    from tests.factories import make_person

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(tmp_path))
        mp.setenv("STEWARD_BASE_URL", BASE)
        mp.setenv("STEWARD_ENV", "test")
        mp.setenv("STEWARD_WEB_DIR", str(tmp_path / "no-web-build"))
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    with Session(books.directory) as ddb:
        jr = make_person(ddb, "jr", [(books.book("ours").id, "manager")])
        for name in ("Mom", "Dad", "Aunt"):
            create_book(books, ddb, name=name, kind="parent", owner_labels=["Margaret", "Joint"], managers=[jr.id])
    yield s, books
    books.dispose()


def _median_ms(fn, n=200):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    return statistics.median(times)


def test_book_dependency_overhead_under_5ms(four_books):
    from steward.app import create_app
    from steward.deps import book_db, current_user, open_book
    from tests.factories import login
    s, books = four_books
    app = create_app(s, books)

    @app.get("/api/perf/plain")
    def plain(me=Depends(current_user)):
        return {}

    r = APIRouter(dependencies=[Depends(open_book)])

    @r.get("/perf/book")
    def book(db=Depends(book_db)):
        return {}
    app.include_router(r, prefix="/api/b/{slug}")
    with TestClient(app, base_url=BASE) as c:
        login(c, "jr")
        for _ in range(30):
            c.get("/api/perf/plain"), c.get("/api/b/ours/perf/book")
        plain_ms = _median_ms(lambda: c.get("/api/perf/plain"))
        book_ms = _median_ms(lambda: c.get("/api/b/ours/perf/book"))
    _check("book_dependency_overhead", (book_ms - plain_ms) * FACTOR, 5)


def test_switching_to_a_book_whose_engine_is_closed_under_300ms(four_books):
    from steward.app import create_app
    from tests.factories import login
    s, books = four_books
    with TestClient(create_app(s, books), base_url=BASE) as c:
        login(c, "jr")
        times = []
        for _ in range(5):
            for slug in ("mom", "dad", "aunt"):
                books.close(books.book(slug).id)
                t0 = time.perf_counter()
                assert c.get(f"/api/b/{slug}/accounts").status_code == 200
                times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    _check("cold_switch_p95", times[int(0.95 * (len(times) - 1))] * FACTOR, 300)


def test_start_up_with_four_books_under_3s(four_books):
    from steward.books.registry import BookRegistry
    s, books = four_books
    books.dispose()
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        fresh = BookRegistry(s)
        fresh.prepare()
        for b in fresh.books():
            fresh.engine_for(b)
        times.append((time.perf_counter() - t0) * 1000)
        assert not fresh.unavailable
        fresh.dispose()
    _check("startup_four_books", max(times) * FACTOR, 3000)


def test_auth_me_with_four_books_warm_under_50ms(four_books):
    """GET /api/auth/me lists every book the person belongs to; with the engines cached it stays quick."""
    from steward.app import create_app
    from tests.factories import login
    s, books = four_books
    with TestClient(create_app(s, books), base_url=BASE) as c:
        login(c, "jr")
        assert len(c.get("/api/auth/me").json()["books"]) == 4
        for _ in range(10):
            c.get("/api/auth/me")
        ms = _median_ms(lambda: c.get("/api/auth/me"), n=100)
    _check("auth_me_four_books_warm", ms * FACTOR, 50)
