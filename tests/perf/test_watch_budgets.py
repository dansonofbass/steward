"""Spec 12: "All checks over 10,000 transactions < 2 s", timed as run_watch(): reading the book, every check over
10,000 transactions none of which were checked before, and writing the flags. Run with:
uv run pytest -q -m perf tests/perf/test_watch_budgets.py (STEWARD_PERF_FACTOR=2.5 approximates the NAS)."""
import os
import statistics
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
BASE = "https://nas.tail1234.ts.net"
FIRST = ["ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM", "FIR", "GINKGO", "HAZEL", "IVY", "JUNIPER", "LARCH", "MAPLE",
         "NUTMEG", "OAK", "PINE", "QUINCE", "ROWAN", "SPRUCE", "TAMARACK", "WILLOW"]
SECOND = ["BAKERY", "CAFE", "DELI", "FLORIST", "GARAGE", "GROCERY", "HARDWARE", "KITCHEN", "LAUNDRY", "MARKET",
          "NURSERY", "OPTICAL", "PANTRY", "PHARMACY", "SALON", "SHOES", "STUDIO", "TAILOR", "TOYS", "VARIETY"]
CATEGORIES = ["groceries", "dining", "health", "shopping", "utilities", "personal"]


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


def test_all_checks_over_10000_transactions_under_2s(tmp_path):
    from steward.books.registry import open_books
    from steward.books.service import create_book
    from steward.db.keys import ensure_key
    from steward.db.models import Account, AccountType, Flag, FlagEvent, MailOutbox, Source, Transaction
    from steward.services.accounts import manual_institution
    from steward.settings import Settings
    from steward.watch.run import run_watch

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("STEWARD_DATA_DIR", str(tmp_path))
        mp.setenv("STEWARD_BASE_URL", BASE)
        mp.setenv("STEWARD_ENV", "test")
        s = Settings(_env_file=None)
    ensure_key(s.key_path)
    books = open_books(s)
    with Session(books.directory) as ddb:
        book = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret", "Joint"])
    today = date(2026, 10, 19)
    now = datetime(2026, 10, 19, 13, 12, tzinfo=timezone.utc)
    with Session(books.engine_for(book)) as db:
        inst = manual_institution(db)
        accts = []
        for name in ("Joint checking", "Citi card", "Way2Save savings"):
            a = Account(institution_id=inst.id, name=name, type=AccountType.checking, owner="joint", source=Source.manual)
            db.add(a)
            db.flush()
            accts.append(a.id)
        for i in range(10_000):
            raw = (f"ZELLE TO {FIRST[i % 20]} {SECOND[(i // 7) % 20]} ON 10/16" if i % 50 == 0 else
                   "ATM WITHDRAWAL 1200 MAIN ST" if i % 61 == 0 else
                   f"{FIRST[i % 20]} {SECOND[(i // 20) % 20]} #{i % 97} FULLERTON CA")
            db.add(Transaction(account_id=accts[i % 3], posted_at=today - timedelta(days=i % 540),
                               amount_cents=-(500 + (i * 37) % 20_000), raw_description=raw,
                               category=CATEGORIES[i % len(CATEGORIES)]))
        db.commit()
        times = []
        for _ in range(3):
            db.execute(delete(FlagEvent))
            db.execute(delete(MailOutbox))
            db.execute(delete(Flag))
            db.execute(update(Transaction).values(watched_at=None))
            db.commit()
            t0 = time.perf_counter()
            run_watch(db, today, now, after="import", max_age_days=10_000)   # every transaction is new
            db.commit()
            times.append((time.perf_counter() - t0) * 1000)
        assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.watched_at.is_(None))) == 0
    books.dispose()
    _check("watch_checks_10000", statistics.median(times) * FACTOR, 2000)
