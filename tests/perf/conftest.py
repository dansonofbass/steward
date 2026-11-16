import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from steward.db.models import Transaction
from steward.demo import seed


def _remote_client(base_url):
    """Run the budgets against a deployed, demo-seeded throwaway vault (never the real one)."""
    import httpx2

    with httpx2.Client(base_url=base_url, timeout=30) as c:
        r = c.post("/api/auth/login", json={"username": "alex", "password": "pw-demo-alex-2026"})
        assert r.status_code == 200, "remote vault must be demo-seeded (STEWARD_ALLOW_DEMO=1 steward seed-demo)"
        yield c


@pytest.fixture(scope="module")
def big_client(tmp_path_factory):
    if os.environ.get("STEWARD_PERF_BASE_URL"):
        yield from _remote_client(os.environ["STEWARD_PERF_BASE_URL"])
        return
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session
    from steward.app import create_app
    from steward.books.registry import open_books
    from steward.db.keys import ensure_key
    from steward.demo import seed_people
    from steward.settings import Settings

    d = tmp_path_factory.mktemp("perf")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(d))
        mp.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
        mp.setenv("STEWARD_ENV", "test")
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    ours = books.book("ours")
    with Session(books.engine_for(ours)) as db:
        for s_ in (11, 12, 13):  # three households alongside each other, ~15,000 rows (spec section 9)
            seed(db, years=5, seed=s_)
        assert db.scalar(select(func.count()).select_from(Transaction)) >= 15_000
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    with TestClient(create_app(s, books), base_url="https://nas.tail1234.ts.net") as c:
        r = c.post("/api/auth/login", json={"username": "alex", "password": "pw-demo-alex-2026"})
        assert r.status_code == 200
        yield c
    books.dispose()


@pytest.fixture
def fresh_vault(tmp_path):
    """A new encrypted, migrated vault with settings; the ingestion budgets are local-only."""
    if os.environ.get("STEWARD_PERF_BASE_URL"):
        pytest.skip("ingestion budgets run against the local fixture only")
    from steward.books.registry import open_books
    from steward.db.keys import ensure_key
    from steward.settings import Settings

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(tmp_path))
        mp.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
        mp.setenv("STEWARD_ENV", "test")
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    yield s, books
    books.dispose()


def pytest_collection_modifyitems(config, items):
    """The budgets seed and time minutes of real work, so their ceiling is 15 minutes, not the suite's two."""
    here = Path(__file__).parent
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.timeout(900))
