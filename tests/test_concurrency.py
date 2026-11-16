"""Requests that wait (for a body, for the categorizer, for a book's write lock) must not hold up other requests.
Each test decides on the real event: the stalled request asking for its body, the model blocked until this test
releases it, a writer reaching BEGIN IMMEDIATE. It never decides on time.sleep or on how long something took
(flaky-test audit P2-P5). UNDER_BUSY is the ceiling for "answered meanwhile": under the books' 30 s busy timeout, so
a request that really waited for the lock is still waiting when it runs out."""
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.factories import make_user
from tests.waiting import CEILING

UNDER_BUSY = 20


@contextmanager
def writer_reaches_begin(engine):
    """Set once a connection on `engine` is about to send BEGIN IMMEDIATE, just before it asks SQLite for the write
    lock: the event a half-second nap used to stand in for. It listens for the statement itself
    (before_cursor_execute), because a begin listener runs after the engine's own begin hook, which is the one that
    blocks on the lock. The base engine's listeners reach the option engines a request's session uses."""
    reached = threading.Event()

    def on_statement(conn, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE":
            reached.set()
    event.listen(engine, "before_cursor_execute", on_statement)
    try:
        yield reached
    finally:
        event.remove(engine, "before_cursor_execute", on_statement)


def test_parallel_requests_do_not_hit_database_locked(app, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    db.commit()
    with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
        assert c.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"}).status_code == 200

        def worker(_):
            return [c.get("/api/auth/me").status_code for _ in range(20)]

        with ThreadPoolExecutor(8) as ex:
            codes = [code for batch in ex.map(worker, range(8)) for code in batch]
    assert codes == [200] * 160


def test_a_request_waiting_for_its_body_does_not_hold_the_write_lock(tmp_path, monkeypatch):
    """Item 2 of the M2-B review: signing in must not leave an IMMEDIATE transaction open while the handler waits
    for the request body, or every other signed-in request queues behind a slow client."""
    import http.client
    import json
    import socket

    from sqlalchemy.orm import Session

    from steward.app import create_app
    from steward.books.registry import open_books
    from steward.db.keys import ensure_key
    from steward.settings import Settings
    from tests.factories import TEST_BOOK_KEY
    from tests.servers import serve_in_thread

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))          # bound here and handed to uvicorn: nothing can take the port in between
    port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWARD_BASE_URL", origin)
    monkeypatch.setenv("STEWARD_ENV", "test")
    monkeypatch.setenv("STEWARD_WEB_DIR", str(tmp_path / "no-web-build"))
    settings = Settings(_env_file=None)
    ensure_key(settings.key_path)
    books = open_books(settings)
    with Session(books.engine_for(books.book("ours"))) as db:
        db.info[TEST_BOOK_KEY] = (books, books.book("ours").id)
        make_user(db)
    inner = create_app(settings, books)
    body_asked = threading.Event()

    async def app(scope, receive, send):
        """The app, watched: body_asked is set when the stalled preview first asks for its body."""
        if scope["type"] == "http" and scope["path"].endswith("/plan/preview"):
            async def asked():
                body_asked.set()
                return await receive()
            return await inner(scope, asked, send)
        return await inner(scope, receive, send)

    try:
        with serve_in_thread(app, sockets=[sock]):
            h = http.client.HTTPConnection("127.0.0.1", port, timeout=UNDER_BUSY)
            h.request("POST", "/api/auth/login", body=json.dumps({"username": "jr", "password": "pw-one-two-3"}),
                      headers={"Content-Type": "application/json", "Origin": origin})
            r = h.getresponse()
            r.read()
            assert r.status == 200
            cookie = "; ".join(v.split(";")[0] for k, v in r.getheaders() if k.lower() == "set-cookie")
            with socket.create_connection(("127.0.0.1", port), timeout=UNDER_BUSY) as stalled:
                stalled.sendall((f"POST /api/b/ours/plan/preview HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                                 f"Origin: {origin}\r\nCookie: {cookie}\r\nContent-Type: application/json\r\n"
                                 f"Content-Length: 50\r\n\r\n").encode())
                assert body_asked.wait(CEILING), "the preview never asked for its body"
                h2 = http.client.HTTPConnection("127.0.0.1", port, timeout=UNDER_BUSY)
                h2.request("GET", "/api/b/ours/plan/setup", headers={"Cookie": cookie})
                r2 = h2.getresponse()
                r2.read()
                assert r2.status == 200              # answered while the preview still waits for its body
                stalled.sendall(b"{}".ljust(50))     # the body at last: the preview answers, nothing disconnects
                assert stalled.recv(64).startswith(b"HTTP/1.1 ")
    finally:
        books.dispose()


class _SlowModel:
    """A categorizer whose one batch call blocks until the test releases it: the gateway thinking for as long as the
    test needs. It never lets go by itself, so "meanwhile" is certain."""
    last_error = None
    missed = False

    def __init__(self):
        self.started, self.release, self.calls = threading.Event(), threading.Event(), []

    def categorize(self, d, a):
        raise AssertionError("the batch call is the one that must be used")

    def categorize_batch(self, rows, examples=()):
        self.calls.append(list(rows))
        self.started.set()
        self.release.wait()
        return [("dining", "Bean Cafe") for _ in rows]


def _write_meanwhile(engine) -> None:
    """Another request's write (BEGIN IMMEDIATE) on the same book."""
    from sqlalchemy.orm import Session

    from steward.events import log_event
    with Session(engine.execution_options(immediate=True)) as w:
        log_event(w, "info", "test", "meanwhile")
        w.commit()


def test_an_import_waiting_on_the_categorizer_does_not_hold_the_books_write_lock(app, client, db, engine):
    """Found in e2e on 2026-10-25: a commit took 22 s on the model and a concurrent preview failed with "database is
    locked". The model is a network call; it must be asked with no transaction open, and off the event loop."""
    from pathlib import Path

    from sqlalchemy import select

    from steward.db.models import Transaction
    from tests.factories import make_account

    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    a = make_account(db, "Sapphire", type="credit")
    db.commit()
    assert client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"}).status_code == 200
    model = _SlowModel()
    app.state.model = model
    from tests.import_helpers import file_choice, preview, stage
    csv = (Path(__file__).parent / "samples" / "chase_card.csv").read_bytes()
    staged = stage(client, "x.csv", csv).json()
    files = [file_choice(staged["files"][0], a.id)]
    digest = preview(client, staged["batch"], files).json()["digest"]
    body = {"batch": staged["batch"], "files": files, "digest": digest}
    with ThreadPoolExecutor(2) as ex:
        try:
            fut = ex.submit(client.post, "/api/b/ours/import/batch/commit", json=body)
            assert model.started.wait(CEILING), "the import never asked the model"
            # Both answer while the model provably still holds the import: only this test lets it go.
            r = ex.submit(client.get, "/api/b/ours/import/batches").result(timeout=UNDER_BUSY)   # a page load
            ex.submit(_write_meanwhile, engine).result(timeout=UNDER_BUSY)                      # another write
            assert not model.release.is_set() and not fut.done()
        finally:
            model.release.set()
        done = fut.result(timeout=CEILING)
    assert r.status_code == 200
    assert done.status_code == 201 and done.json()["imported"] == 3
    assert [sorted(d for d, _ in c) for c in model.calls] == [["GREENLEAF MARKET, #12", "STREAMFLIX"]]
    db.rollback()
    cats = {t.raw_description: t.category for t in db.scalars(select(Transaction))}
    assert cats == {"GREENLEAF MARKET, #12": "dining", "Payment Thank You-Mobile": "transfer", "STREAMFLIX": "dining"}


def test_a_sync_waiting_on_the_categorizer_does_not_hold_the_books_write_lock(db, engine):
    from datetime import datetime, timezone

    from sqlalchemy import select

    from steward.db.models import SimplefinLink, Transaction
    from steward.services.simplefin.client import claim
    from steward.services.simplefin.sync import sync_now
    from tests.fake_simplefin import make_fake

    now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    hosts = ("testserver",)
    fake, state = make_fake()
    at = int(datetime(2026, 10, 5, 19, tzinfo=timezone.utc).timestamp())
    state.add_account("big", "Big Bank", "bigbank", "chk", 1450_00, at, txns=[
        ("t1", at, 4120_00, "PAYROLL ACME CORP"), ("t2", at, -12_34, "BEAN & LEAF 0031")])
    state.add_account("big", "Big Bank", "bigbank", "sav", 2200_00, at, txns=[("t3", at, -9_99, "STREAMFLIX")])
    with TestClient(fake) as http:
        db.add(SimplefinLink(access_url=claim(http, "http://testserver/claim/abc", allowed_hosts=hosts), claimed_at=now))
        db.commit()
        model = _SlowModel()
        with ThreadPoolExecutor(2) as ex:
            try:
                fut = ex.submit(sync_now, engine, http, model, now, hosts)
                assert model.started.wait(CEILING), "the sync never asked the model"
                ex.submit(_write_meanwhile, engine).result(timeout=UNDER_BUSY)   # while the model holds the sync
                assert not model.release.is_set() and not fut.done()
            finally:
                model.release.set()
            res = fut.result(timeout=CEILING)
    assert (res.institutions_ok, res.transactions_new) == (1, 3)
    assert [[d for d, _ in c] for c in model.calls] == [["BEAN & LEAF 0031"], ["STREAMFLIX"]]
    db.rollback()
    cats = {t.external_id: t.category for t in db.scalars(select(Transaction))}
    assert cats == {"t1": "income", "t2": "dining", "t3": "dining"}


_TAX_CSV = ("form,tax_year,recipient,payer,last4,box_1,box_1a,box_1b,box_2a,box_3,box_4,box_5,box_7,medicare\n"
            "1099-INT,2025,Margaret,Harbor Savings Bank,2207,58.90,,,,,0,,,\n").encode()
_PDF = b"%PDF-1.4\n%made-up statement\n%%EOF\n"
# Every route that is async def because it awaits its upload, then works in a book's database: (book, path, file).
_UPLOADS = {
    "tax form csv": ("margaret-ellis", "/api/b/margaret-ellis/inventory/tax-forms/csv", "tax_forms.csv"),
    "inventory file": ("margaret-ellis", "/api/b/margaret-ellis/inventory/files", "statement.pdf"),
}


@pytest.mark.parametrize("route", list(_UPLOADS))
def test_an_upload_waiting_for_a_locked_book_does_not_stall_other_requests(route, books, ours, margaret, db, client):
    """Found in e2e on 2026-10-25: while another request held a book's write lock, an import preview waited for it at
    BEGIN IMMEDIATE on the event loop, and every other request on the server (other books, the sign-in check, page
    loads) hung with it for up to the 30 s busy timeout. The upload must wait in a worker thread instead."""
    from pathlib import Path

    from tests.factories import login, make_account

    slug, url, name = _UPLOADS[route]
    data = {}
    if slug == "ours":
        data["account_id"] = str(make_account(db, "Sapphire", type="credit").id)
        db.commit()
        body = (Path(__file__).parent / "samples" / "chase_card.csv").read_bytes()
    else:
        body = _TAX_CSV if name.endswith(".csv") else _PDF
    login(client, "jr")
    eng = books.engine_for(ours if slug == "ours" else margaret)
    holder = eng.execution_options(immediate=True).connect()
    holder.begin()                                       # another request's write, mid-transaction
    with writer_reaches_begin(eng) as reached, ThreadPoolExecutor(2) as ex:
        try:
            upload = ex.submit(client.post, url, files={"file": (name, body, "application/octet-stream")}, data=data)
            assert reached.wait(CEILING), "the upload never reached BEGIN IMMEDIATE, so this test proves nothing"
            # The upload now waits for the lock the holder keeps; another request must be answered meanwhile.
            status = ex.submit(client.get, "/api/auth/me").result(timeout=UNDER_BUSY).status_code
            waiting = not upload.done()
        finally:
            holder.rollback()
            holder.close()
        done = upload.result(timeout=CEILING)
    assert waiting, "the upload never waited for the lock, so this test proves nothing"
    assert status == 200
    assert done.status_code in (200, 201), done.text


def test_a_read_on_a_book_another_request_is_writing_answers_at_once(books, ours, db, signed_in):
    """Every book request used to open with BEGIN IMMEDIATE, so while an import, a sync or a long write held a book's
    write lock, each page load on that book waited for it, up to the 30 s busy timeout. WAL lets a reader go on beside
    the writer: a GET reads its snapshot while the lock is held, and a write still queues for the lock and then
    succeeds."""
    from sqlalchemy import text

    from tests.factories import make_account

    client = signed_in
    make_account(db, "Checking")
    db.commit()
    eng = books.engine_for(ours)
    holder = eng.execution_options(immediate=True).connect()
    holder.begin()                                       # another request's write, mid-transaction
    holder.execute(text("UPDATE account SET name = 'Renamed' WHERE name = 'Checking'"))
    with writer_reaches_begin(eng) as reached, ThreadPoolExecutor(2) as ex:
        try:
            got = ex.submit(client.get, "/api/b/ours/accounts").result(timeout=UNDER_BUSY)   # the lock is still held
            write = ex.submit(client.post, "/api/b/ours/accounts",
                              json={"name": "Savings", "type": "savings", "owner": "joint", "balance_cents": 100_00})
            assert reached.wait(CEILING), "the write never reached BEGIN IMMEDIATE"
            waiting = not write.done()
        finally:
            holder.commit()
            holder.close()
        done = write.result(timeout=CEILING)
    assert got.status_code == 200
    assert [a["name"] for a in got.json()["accounts"]] == ["Checking"]   # the snapshot before the other write
    assert waiting, "the write didn't wait for the lock"
    assert done.status_code == 201, done.text
    names = sorted(a["name"] for a in client.get("/api/b/ours/accounts").json()["accounts"])
    assert names == ["Renamed", "Savings"]


def _while_another_write_commits(books, book, call):
    """Runs call() while another connection holds the book's write lock, and commits that other write once call()
    has reached its own BEGIN IMMEDIATE. A GET that read on a deferred snapshot and then wrote would fail at once
    with "database is locked"."""
    from sqlalchemy import text

    eng = books.engine_for(book)
    holder = eng.execution_options(immediate=True).connect()
    holder.begin()
    holder.execute(text("INSERT INTO event_log (at, level, kind, message, actionable) "
                        "VALUES (CURRENT_TIMESTAMP, 'info', 'test', 'meanwhile', 0)"))
    with writer_reaches_begin(eng) as reached, ThreadPoolExecutor(1) as ex:
        try:
            fut = ex.submit(call)
            assert reached.wait(CEILING), "the request never began its write"
        finally:
            holder.commit()
            holder.close()
        return fut.result(timeout=CEILING)


def test_get_plan_logs_an_engine_failure_while_another_write_commits(frozen, signed_in, books, ours, db, monkeypatch):
    """GET /plan is the one plain read that can write: an engine failure leaves one event (spec 8). That write takes
    the lock in its own short IMMEDIATE transaction, so it waits for the other writer instead of failing."""
    from sqlalchemy import select

    from steward.db.models import EventLog
    from tests.factories import make_ready_household, make_user

    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)

    def boom(*args, **kwargs):
        raise RuntimeError("the engine fell over")
    monkeypatch.setattr("steward.services.plan.solve", boom)
    r = _while_another_write_commits(books, ours, lambda: signed_in.get("/api/b/ours/plan"))
    assert r.status_code == 503, r.text
    assert r.json() == {"error": "The plan couldn't be worked out right now.", "last_saved": None}
    db.rollback()
    assert db.scalars(select(EventLog.message).where(EventLog.kind == "system")).all() == \
        ["The retirement plan couldn't be worked out: RuntimeError."]
    assert signed_in.get("/api/b/ours/plan").status_code == 503         # logged once while it stays unresolved
    db.rollback()
    assert len(db.scalars(select(EventLog.id).where(EventLog.kind == "system")).all()) == 1


def test_staging_answers_while_another_request_holds_the_write_lock(books, ours, ddb, client):
    """Plan Engineering choice 7: POST /import/files only reads, under a plain BEGIN, so a writer mid-transaction
    never makes it wait."""
    from tests.factories import login, make_person
    from tests.import_helpers import stage
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    holder = books.engine_for(ours).execution_options(immediate=True).connect()
    holder.begin()
    try:
        with ThreadPoolExecutor(1) as ex:
            r = ex.submit(stage, client, "amex-basic.csv").result(timeout=UNDER_BUSY)
    finally:
        holder.rollback()
        holder.close()
    assert r.status_code == 201


def _hold_directory_lock(books):
    """Another writer holding the directory's write lock (a sign-in, a password change) until the test lets go."""
    from steward.db.engine import allow_writes
    raw = books.directory.raw_connection()
    allow_writes(raw)                       # a test GET may have left query_only on this pooled connection
    raw.driver_connection.execute("BEGIN IMMEDIATE")
    return raw


def test_signed_in_reads_answer_while_another_writer_holds_the_directory(signed_in, books):
    """Phase 18: every signed-in request took the directory's write lock three times (last_seen_at, the user, the
    book), so six GETs ran one at a time, ~90 ms apart. Reads now read. While a writer holds the lock they answer;
    one that still asked for the lock would wait out the 30 s busy timeout, past UNDER_BUSY."""
    with ThreadPoolExecutor(3) as ex:
        raw = _hold_directory_lock(books)
        try:
            futs = [ex.submit(signed_in.get, p) for p in ("/api/auth/me", "/api/b/ours/accounts", "/api/books")]
            codes = [f.result(timeout=UNDER_BUSY).status_code for f in futs]
        finally:
            raw.driver_connection.execute("ROLLBACK")
            raw.close()
    assert codes == [200, 200, 200]
