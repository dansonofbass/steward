from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.books import jobs
from steward.books.service import create_book
from steward.db.models import EventLog, SimplefinLink, Transaction
from tests.fake_simplefin import make_fake

NOW = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def three(books, ddb, ours):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"])
    dad = create_book(books, ddb, name="Dad", kind="parent", owner_labels=["Joe"])
    for book in (ours, mom):
        with Session(books.engine_for(book)) as db:
            db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=NOW))
            db.commit()
    return ours, mom, dad


def test_one_books_failure_is_logged_there_and_the_others_carry_on(books, three, monkeypatch):
    ours, mom, dad = three
    fake, state = make_fake()
    base = int(NOW.timestamp()) - 3600
    state.add_account("conn1", "Big Bank", "bigbank", "a1", 1000_00, base, txns=[("t1", base, -500, "SHOP")])
    real = jobs.sync_now
    mom_engine = books.engine_for(mom)

    def flaky(engine, *a, **k):
        if engine is mom_engine:
            raise RuntimeError("bank down")
        return real(engine, *a, **k)
    monkeypatch.setattr(jobs, "sync_now", flaky)
    with TestClient(fake) as http:
        out = jobs.sync_all_books(books, http, None, NOW, ("testserver",))
        again = jobs.sync_all_books(books, http, None, NOW, ("testserver",))
    assert out[ours.slug].institutions_ok == 1 and out["mom"] == "failed" and out["dad"] == "not linked"
    with Session(books.engine_for(ours)) as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == 1
    with Session(mom_engine) as db:   # logged once in mom's own events, even after two failed runs
        assert db.scalars(select(EventLog.message).where(EventLog.kind == "sync")).all() == [jobs.SYNC_FAILED]
    assert again["mom"] == "failed"


def test_unavailable_and_busy_books_are_skipped(books, three):
    ours, mom, dad = three
    books.unavailable[dad.id] = "The book's file is missing."
    lock = books.sync_lock(mom.id)
    with lock:
        fake, _ = make_fake()
        with TestClient(fake) as http:
            out = jobs.sync_all_books(books, http, None, NOW, ("testserver",))
    assert out["dad"] == "unavailable" and out["mom"] == "busy"
    assert jobs.sync_all_books(books, None, None, NOW, ("testserver",), only="dad") == {"dad": "unavailable"}


def test_a_later_good_sync_resolves_the_failure_notice(books, three, monkeypatch):
    ours, mom, dad = three
    fake, state = make_fake()
    base = int(NOW.timestamp()) - 3600
    state.add_account("conn1", "Big Bank", "bigbank", "a1", 1000_00, base, txns=[("t1", base, -500, "SHOP")])
    real = jobs.sync_now
    broken = {"on": True}

    def flaky(engine, *a, **k):
        if broken["on"]:
            raise RuntimeError("bank down")
        return real(engine, *a, **k)
    monkeypatch.setattr(jobs, "sync_now", flaky)
    with TestClient(fake) as http:
        assert jobs.sync_all_books(books, http, None, NOW, ("testserver",), only="mom")["mom"] == "failed"
        broken["on"] = False
        assert jobs.sync_all_books(books, http, None, NOW, ("testserver",), only="mom")["mom"] != "failed"
    with Session(books.engine_for(mom)) as db:
        notice = db.scalars(select(EventLog).where(EventLog.message == jobs.SYNC_FAILED)).one()
        assert notice.resolved_at is not None
