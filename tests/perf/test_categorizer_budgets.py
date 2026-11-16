"""Ruling 16: the catch-up's NAS share for one batch of 50 rows, with an instant categorizer, < 250 ms."""
import os
import statistics
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from steward.db.models import CategorySource, Transaction
from steward.services.catchup import catch_up_book
from tests.factories import make_account, make_txn

pytestmark = pytest.mark.perf
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))
TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)


def _check(name, value_ms, budget_ms):
    print(f"\nPERF {name}: {value_ms:.2f} ms (budget {budget_ms} ms, factor {FACTOR})")
    assert value_ms < budget_ms, f"{name} {value_ms:.2f} ms exceeds {budget_ms} ms"


class Instant:
    missed = False

    def categorize_batch(self, rows, examples=()):
        return [("dining", None)] * len(rows)


def test_one_catch_up_batch_of_50_under_250_ms(db, engine):
    a = make_account(db)
    db.add_all([Transaction(account_id=a.id, posted_at=TODAY - timedelta(days=i % 700), amount_cents=-500,
                            raw_description=f"SHOP {i}", category="shopping", category_source=CategorySource.rule)
                for i in range(5000)])                 # a busy book: none of these are candidates
    db.commit()
    for i in range(50):
        make_txn(db, a, TODAY - timedelta(days=1), -500, f"BEAN CAFE {i}")
    times = []
    for _ in range(5):
        with Session(engine) as s:
            s.execute(update(Transaction).where(Transaction.raw_description.like("BEAN CAFE%"))
                      .values(category="uncategorized", category_source=CategorySource.none, merchant=None,
                              model_asked_at=None))         # never asked: each run asks the 50 again
            s.commit()
        t0 = time.perf_counter()
        result = catch_up_book(engine, Instant(), now=NOW)
        times.append((time.perf_counter() - t0) * 1000)
        assert result.categorized == 50
    _check("catch_up_batch_of_50", statistics.median(times) * FACTOR, 250)
