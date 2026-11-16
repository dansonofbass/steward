"""Spec 12: "Inventory page API with 200 items < 500 ms". Run with:
uv run pytest -q -m perf tests/perf/test_inventory_budgets.py (STEWARD_PERF_FACTOR=2.5 approximates the NAS)."""
import json
import os
import statistics
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
BASE = "https://nas.tail1234.ts.net"


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


def fill_items(db: Session, n_accounts=120, per_kind=20) -> None:
    """200 items: 120 accounts with a year of month-end balances, 20 each of income, insurance, documents, contacts."""
    from steward.db.models import Account, AccountType, BalanceSnapshot, Institution, InventoryItem, Source
    inst = Institution(name="Manual", source=Source.manual)
    db.add(inst)
    db.flush()
    accounts = []
    for n in range(n_accounts):
        a = Account(institution_id=inst.id, name=f"Account {n}", type=AccountType.savings, owner="margaret",
                    source=Source.manual)
        db.add(a)
        db.flush()
        for m in range(12):
            db.add(BalanceSnapshot(account_id=a.id, as_of=date(2026, 1, 1) + timedelta(days=30 * m), balance_cents=n * 1000 + m))
        item = InventoryItem(kind="account", name=a.name, owner="margaret", institution=f"Bank {n % 9}",
                             last4=f"{n:04d}", status="confirmed", data_source="statement", account_id=a.id,
                             details=json.dumps({"type": "savings"}))
        db.add(item)
        accounts.append(item)
    db.flush()
    for n in range(per_kind):
        db.add(InventoryItem(kind="income", name=f"Pension {n}", owner="margaret", status="confirmed", data_source="manual",
                             details=json.dumps({"source": "pension", "amount_cents": 10000, "frequency": "monthly",
                                                 "usual_day": 1, "lands_in_id": accounts[n].id})))
        db.add(InventoryItem(kind="insurance", name=f"Policy {n}", owner="margaret", status="needs_checking",
                             data_source="manual", institution="Insurer", last4="1234",
                             details=json.dumps({"type": "life", "amount_cents": 5000, "frequency": "yearly",
                                                 "paid_from_id": accounts[n].id})))
        db.add(InventoryItem(kind="document", name=f"Document {n}", owner="margaret", status="confirmed",
                             details=json.dumps({"type": "will", "original_kept_in": "Safe", "signed_on": "2019-06-12"})))
        db.add(InventoryItem(kind="contact", name=f"Contact {n}", owner="margaret", status="confirmed",
                             institution="Firm", details=json.dumps({"role": "attorney"})))
    db.commit()


@pytest.fixture
def parent_client(tmp_path):
    from steward.app import create_app
    from steward.books.registry import open_books
    from steward.books.service import create_book
    from steward.db.keys import ensure_key
    from steward.settings import Settings
    from tests.factories import login, make_person

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(tmp_path))
        mp.setenv("STEWARD_BASE_URL", BASE)
        mp.setenv("STEWARD_ENV", "test")
        mp.setenv("STEWARD_WEB_DIR", str(tmp_path / "no-web-build"))
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    with Session(books.directory) as ddb:
        book = create_book(books, ddb, name="Margaret Ellis", kind="parent",
                           owner_labels=["Margaret", "Robert (husband)", "Joint"])
        make_person(ddb, "jr", [(books.book("ours").id, "manager"), (book.id, "manager")])
    with Session(books.engine_for(book)) as db:
        fill_items(db)
    with TestClient(create_app(s, books), base_url=BASE) as c:
        login(c, "jr")
        yield c
    books.dispose()


def _median_ms(fn, n=30):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    return statistics.median(times)


def test_inventory_page_api_with_200_items_under_500ms(parent_client):
    assert len(parent_client.get("/api/b/margaret-ellis/inventory").json()["items"]) == 200
    _check("inventory_list_200", _median_ms(lambda: parent_client.get("/api/b/margaret-ellis/inventory")) * FACTOR, 500)


def test_parent_home_api_with_200_items_under_500ms(parent_client):
    _check("inventory_overview_200",
           _median_ms(lambda: parent_client.get("/api/b/margaret-ellis/inventory/overview")) * FACTOR, 500)


def test_suggester_over_10000_transactions_under_2s(tmp_path):
    """Spec 12: "Suggester over 10,000 transactions < 2 s", timed as refresh(): reading the book, the suggester and
    writing the suggestions."""
    from steward.books.registry import open_books
    from steward.books.service import create_book
    from steward.db.keys import ensure_key
    from steward.db.models import Transaction
    from steward.demo_parent import seed_parent
    from steward.inventory.suggestions import refresh
    from steward.settings import Settings

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(tmp_path))
        mp.setenv("STEWARD_BASE_URL", BASE)
        mp.setenv("STEWARD_ENV", "test")
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    with Session(books.directory) as ddb:
        book = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret", "Joint"])
    with Session(books.engine_for(book)) as db:
        today = date(2026, 10, 18)
        seed_parent(db, today)
        base = db.scalar(select(Transaction.account_id))
        for i in range(10_000):
            db.add(Transaction(account_id=base, posted_at=today - timedelta(days=i % 1800), amount_cents=-(100 + i % 900),
                               raw_description=f"SHOP NUMBER {i % 500} STORE {i}"))
        db.commit()
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            refresh(db, today)
            db.commit()
            times.append((time.perf_counter() - t0) * 1000)
    books.dispose()
    _check("suggester_refresh_10000", statistics.median(times) * FACTOR, 2000)


def test_the_suggester_alone_over_10000_transactions_under_2s():
    """The pure part of spec 12's suggester budget, without the book reads and writes refresh() times above. It
    moved here from tests/test_suggester.py: a wall-clock budget has no place in a unit test (flaky-test audit P9)."""
    from steward.inventory.suggester import Txn, candidates
    txns, start = [], date(2016, 1, 1)
    for i in range(10_000):
        txns.append(Txn(i, 1 + i % 3, start + timedelta(days=i // 3), -(100 + i % 500), f"SHOP NUMBER {i % 400} 77{i}"))
    t0 = time.perf_counter()
    candidates(txns, [], [])
    _check("suggester_pure_10000", (time.perf_counter() - t0) * 1000 * FACTOR, 2000)
