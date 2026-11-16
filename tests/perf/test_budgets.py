import os
import time
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.perf

# Set STEWARD_PERF_FACTOR=2.5 when running on a dev box to approximate the DS920+
# (J4125 ≈ 2.5× slower than a 12900KF core).
FACTOR = float(os.environ.get("STEWARD_PERF_FACTOR", "1"))


def _p95_ms(fn, n=20):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code in (200, 201)
    times.sort()
    return times[int(0.95 * (n - 1))] * FACTOR


def _check(name, p95, budget):
    print(f"\nPERF {name}: p95={p95:.1f} ms (budget {budget} ms, factor {FACTOR})")
    assert p95 < budget, f"{name} p95 {p95:.1f} ms exceeds {budget} ms"


def test_search_under_200ms(big_client):
    _check("search", _p95_ms(lambda: big_client.get("/api/b/ours/transactions?q=market&limit=50")), 200)


def test_filtered_list_under_200ms(big_client):
    _check("filtered_list", _p95_ms(lambda: big_client.get("/api/b/ours/transactions?category=dining&business=false&limit=50")), 200)


def test_review_patch_under_150ms(big_client):
    ids = [t["id"] for t in big_client.get("/api/b/ours/review").json()["uncategorized"][:20]]
    assert len(ids) == 20
    it = iter(ids)  # note: this mutates the shared module-scoped dataset before the summary/history tests run
    _check("review_patch", _p95_ms(lambda: big_client.patch(f"/api/b/ours/transactions/{next(it)}", json={"category": "shopping"}), n=len(ids)), 150)


def test_review_queue_under_300ms(big_client):
    _check("review_queue", _p95_ms(lambda: big_client.get("/api/b/ours/review")), 300)


def test_summary_under_300ms(big_client):
    _check("summary", _p95_ms(lambda: big_client.get("/api/b/ours/summary")), 300)


def test_history_90d_under_300ms(big_client):
    _check("history_90d", _p95_ms(lambda: big_client.get("/api/b/ours/summary/history?days=90")), 300)


# --- Ingestion budgets (spec section 9). Local fixture only. ---

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)


def _fake_four_institutions():
    """4 connections x 2 accounts x 400 transactions: 3,200 rows, with a transfer pair every 40th row."""
    from tests.fake_simplefin import make_fake

    app, state = make_fake()
    base = int(NOW.timestamp()) - 3600
    for c in range(4):
        for a in range(2):
            acct = f"c{c}a{a}"
            txns = []
            for i in range(400):
                posted = base - i * 80 * 86400 // 400  # spread across the last 80 days (sync window is 90)
                if i % 40 == 0:  # transfer out of a0, matching transfer in to a1, same instant
                    sign = -1 if a == 0 else 1
                    txns.append((f"{acct}-{i}", posted, sign * (100_00 + i * 100), "ONLINE TRANSFER"))
                else:
                    txns.append((f"{acct}-{i}", posted, -((i % 90) + 1) * 100 - i % 100, f"SHOP {i % 40} #{c}{a}"))
            state.add_account(f"conn{c}", f"Bank {c}", f"bank{c}", acct, 1000_00, base, txns=txns)
    return app


def test_sync_four_institutions_under_60s(fresh_vault, tmp_path_factory):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from steward.db.engine import make_engine
    from steward.db.keys import ensure_key
    from steward.db.migrate import run_migrations
    from steward.db.models import SimplefinLink, Transaction
    from steward.services.simplefin.sync import run_sync

    settings, first = fresh_vault
    first.dispose()
    app = _fake_four_institutions()
    times = []
    for n in range(3):
        d = tmp_path_factory.mktemp(f"sync{n}")
        eng = make_engine(d / "vault.db", ensure_key(d / "vault.key"))  # re-create the DB each run
        run_migrations(eng)
        try:
            with Session(eng) as db, TestClient(app) as http:
                link = SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=NOW)
                db.add(link); db.commit()
                t0 = time.perf_counter()
                res = run_sync(db, http, link, NOW, model=None, allowed_hosts=("testserver",))
                db.commit()
                times.append((time.perf_counter() - t0) * 1000)
                assert (res.institutions_ok, res.institutions_failed, res.transactions_new) == (4, 0, 3200)
                assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.is_transfer.is_(True))) > 0
        finally:
            eng.dispose()
    times.sort()
    _check("sync_four_institutions", times[int(0.95 * (len(times) - 1))] * FACTOR, 60_000)


def _chase_csv(rows=2500, start=date(2024, 10, 1)):
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    for i in range(rows):
        d = start + timedelta(days=i * 730 // rows)
        lines.append(f"{d:%m/%d/%Y},{d:%m/%d/%Y},SHOP {i % 40},Shopping,Sale,-{(i % 90) + 1}.{i % 100:02d},")
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def import_ctx(fresh_vault):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from steward.app import create_app
    from tests.factories import TEST_BOOK_KEY, make_account, make_user

    settings, books = fresh_vault
    ours = books.book("ours")
    with Session(books.engine_for(ours)) as db:
        db.info[TEST_BOOK_KEY] = (books, ours.id)
        make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
        acct_ids = [make_account(db, f"Card {i}", type="credit").id for i in range(21)]
        db.commit()
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        assert c.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"}).status_code == 200
        yield c, acct_ids


def _batch(c, files):
    """Stage (name, account id, body) files and preview them; returns (batch, choices, preview)."""
    from tests.import_helpers import file_choice, preview, stage
    batch, choices = None, []
    for name, acct, body in files:
        r = stage(c, name, body, batch=batch).json()
        batch = r["batch"]
        choices += [file_choice(e, acct) for e in r["files"] if e["token"]]
    return batch, choices, preview(c, batch, choices).json()


def test_staging_a_5_mb_csv_under_2s(import_ctx):
    from tests.import_helpers import stage
    c, ids = import_ctx
    body = _chase_csv(rows=50_000)[: 5 * 1024 * 1024 - 1024]
    body = body[: body.rfind(b"\n") + 1]
    _check("import_stage_5mb", _p95_ms(lambda: stage(c, "big.csv", body), n=3), 2_000)


def test_a_three_file_batch_preview_under_2s(import_ctx):
    c, ids = import_ctx
    # Each file needs its own body: identical bodies share a SHA and the batch refuses the repeats.
    files = [(f"{i}.csv", ids[i], _chase_csv(rows=834, start=date(2018, 1, 1) + timedelta(days=i * 800)))
             for i in range(3)]
    batch, choices, p = _batch(c, files)
    assert p["new"] == 3 * 834
    _check("import_preview", _p95_ms(lambda: c.post("/api/b/ours/import/batch/preview",
                                                    json={"batch": batch, "files": choices})), 2_000)


def test_csv_24_months_under_5s(import_ctx):
    c, ids = import_ctx
    batch, choices, p = _batch(c, [("chase.csv", ids[3], _chase_csv())])
    body = {"batch": batch, "files": choices, "digest": p["digest"]}
    p95 = _p95_ms(lambda: c.post("/api/b/ours/import/batch/commit", json=body), n=1)
    _check("csv_24_months_commit", p95, 5_000)


def test_csv_24_months_with_a_slow_categorizer_under_5s(import_ctx):
    """With a categorizer that takes a second a batch, the 2,500-row import still commits in < 5 s, because at most one
    batch is asked while the person waits (P19, ruling 21)."""
    c, ids = import_ctx

    class Slow:
        last_error, missed = None, False

        def categorize(self, d, a):
            raise AssertionError("batches only")

        def categorize_batch(self, rows, examples=()):
            time.sleep(1.0)
            return [("shopping", None)] * len(rows)
    c.app.state.model = Slow()
    batch, choices, p = _batch(c, [("chase.csv", ids[4], _chase_csv())])
    body = {"batch": batch, "files": choices, "digest": p["digest"]}
    p95 = _p95_ms(lambda: c.post("/api/b/ours/import/batch/commit", json=body), n=1)
    _check("csv_24_months_commit_slow_categorizer", p95, 5_000)
    assert c.app.state.model.missed is True


def test_applying_a_layout_to_sixty_pages_takes_under_a_second():
    """PDF statements spec, Performance: applying a layout to 60 pages, < 1 s."""
    from steward.services.statements.rules import apply
    from tests.statement_files import pages, pdf
    one = pages("capone_card")
    sixty = [dict(p, n=k + 1) for k in range(60) for p in one[:1]]
    t0 = time.perf_counter()
    apply(pdf("capone_card")[1].layout, sixty, date(2026, 10, 30))
    _check("statement_layout_60_pages", (time.perf_counter() - t0) * 1000, 1_000)


def test_extracting_a_sixty_page_statement_in_the_sandbox_under_20_seconds():
    """PDF statements spec, Performance: a 60-page text statement through the sandbox, < 20 s (p95 on the NAS; one run
    here)."""
    from dataclasses import replace

    from steward_pdf.sandbox import run_extract
    from steward_gateway.evals import statement_set as SS
    spec = SS.SPECS["capone_card"]
    part = replace(spec.parts[0], sections=(SS.Sec("Transactions", "signed", SS._spend(5, 2900, 30)),))
    data, truth = SS._draw(replace(spec, parts=(part,)), spec.end)
    assert 55 <= truth.pages <= 60
    t0 = time.perf_counter()
    assert run_extract(data).error is None
    _check("statement_extract_60_pages", (time.perf_counter() - t0) * 1000, 20_000)
