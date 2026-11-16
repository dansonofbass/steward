"""POST and GET /import/statements (spec P1-P3, P7, API, Limits): a raw application/pdf body, managers only, the 30-file
batch with CSVs, the caps before reading, the same file twice, and a listing whose queries don't grow."""
import tempfile

from sqlalchemy import event

from steward.db.models import StatementStage
from steward.services.statements import stage as S
from tests.factories import login, make_person
from tests.import_helpers import stage as stage_csv
from tests.statement_files import pdf
from tests.statement_helpers import upload


def _jr(ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])


def test_a_pdf_stages_as_a_queued_line(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    r = upload(client, "Statement 0324.pdf", pdf("chase_checking")[0])
    assert r.status_code == 201
    line = r.json()["statement"]
    assert (line["name"], line["state"], line["added_by"], line["rows"]) == ("Statement 0324.pdf", "queued", None, None)
    assert client.get("/api/b/ours/import/statements").json()["statements"][0]["id"] == line["id"]


def test_only_a_raw_pdf_body_is_taken(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    for kind in ("multipart/form-data; boundary=x", "text/plain", "application/octet-stream", ""):
        r = client.post("/api/b/ours/import/statements", content=pdf("boa_checking")[0],
                        headers={"content-type": kind, "x-filename": "a.pdf"})
        assert (r.status_code, r.json()) == (415, {"error": "That request wasn't understood."}), kind


def test_viewers_and_other_books_get_404(client, ddb, ours, margaret):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    assert upload(client, "a.pdf", pdf("boa_checking")[0]).status_code == 404
    assert client.get("/api/b/ours/import/statements").status_code == 404
    assert client.get("/api/b/ours/import/statements/1").status_code == 404
    login(client, "jr")
    sid = upload(client, "a.pdf", pdf("boa_checking")[0], slug=margaret.slug).json()["statement"]["id"]
    assert client.get(f"/api/b/ours/import/statements/{sid}").status_code == 404


def test_the_31st_file_counts_csvs_too(client, db, ddb, ours, fake_clock):
    _jr(ddb, ours)
    login(client, "jr")
    from steward.deps import now
    for k in range(29):
        S.add(db, user_id=1, filename=f"s{k}.pdf", size=1, sha=f"{k:064d}", now=now())
    db.commit()
    batch = stage_csv(client, "amex-basic.csv").json()["batch"]
    r = upload(client, "thirty-one.pdf", pdf("boa_checking")[0], batch=batch)
    assert (r.status_code, r.json()) == (422, {"error": "A batch holds up to 30 files. Import these, then add the rest."})
    assert upload(client, "thirty.pdf", pdf("boa_checking")[0]).status_code == 201
    assert stage_csv(client, "first-cu.csv", batch=batch).status_code == 422


def test_body_limit_passes_15_mb_plus_64_kb_and_refuses_one_more_before_the_handler(client, ddb, ours, app):
    from steward.api.limits import limit_for
    assert limit_for("/api/b/ours/import/statements")[0] == 15 * 1024 * 1024 + 64 * 1024
    _jr(ddb, ours)
    login(client, "jr")
    called = []
    app.state.statements.reserve = lambda *a: called.append(a) or 0
    r = client.post("/api/b/ours/import/statements", content=b"x",
                    headers={"content-type": "application/pdf", "content-length": str(15 * 1024 * 1024 + 64 * 1024 + 1)})
    assert r.status_code == 413 and called == []


def test_a_declared_15_mb_reserves_and_the_body_limit_passes_15_mb_plus_64_kb_to_the_app(client, ddb, ours, app):
    """Pre-flight F6: reserve() is called for a declared 15 MB; BodyLimit hands the app exactly 15 MB + 64 KB (the cap is
    inclusive) and refuses one byte more before the app runs."""
    import asyncio

    from steward.api.limits import BodyLimit
    _jr(ddb, ours)
    login(client, "jr")
    called = []
    app.state.statements.reserve = lambda *a: called.append(a) or 0
    client.post("/api/b/ours/import/statements", content=b"x",
                headers={"content-type": "application/pdf", "content-length": str(15 * 1024 * 1024)})
    assert len(called) == 1

    reached = []

    async def inner(scope, receive, send):
        reached.append(1)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def post(declared):
        sent = []

        async def send(event):
            sent.append(event)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        scope = {"type": "http", "path": "/api/b/ours/import/statements",
                 "headers": [(b"content-length", str(declared).encode())]}
        await BodyLimit(inner)(scope, receive, send)
        return sent[0]["status"]
    cap = 15 * 1024 * 1024 + 64 * 1024
    assert asyncio.run(post(cap)) == 204 and reached == [1]
    assert asyncio.run(post(cap + 1)) == 413 and reached == [1]


def test_the_handler_refuses_past_15_mb(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    r = upload(client, "huge.pdf", b"%PDF-" + b"0" * (15 * 1024 * 1024))
    assert (r.status_code, r.json()) == (413, {"error": "Bigger than 15 MB. Download it again or split it."})


def test_a_12_mb_upload_makes_no_temporary_file(client, ddb, ours, monkeypatch):
    """P1: the raw body, so Starlette's multipart parser (which spools a part over 1 MB to disk) never runs."""
    import inspect

    from fastapi import UploadFile

    from steward.api import statements

    def refuse(*a, **k):
        raise AssertionError("a temporary file was made")
    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, refuse)
    _jr(ddb, ours)
    login(client, "jr")
    assert upload(client, "twelve.pdf", b"%PDF-1.7\n" + b"0" * (12 * 1024 * 1024)).status_code == 201
    assert not any(p.annotation in (UploadFile, "UploadFile") for p in inspect.signature(statements.upload).parameters.values())


def test_the_same_file_twice(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    assert upload(client, "a.pdf", pdf("boa_checking")[0]).status_code == 201
    r = upload(client, "copy of a.pdf", pdf("boa_checking")[0])
    assert (r.status_code, r.json()) == (409, {"error": "This file is already in the batch."})


def test_the_listing_runs_a_fixed_number_of_statements(client, db, ddb, ours, engine):
    _jr(ddb, ours)
    login(client, "jr")
    from steward.deps import now

    def count(n):
        db.query(StatementStage).delete()
        for k in range(n):
            S.add(db, user_id=1, filename=f"s{k}.pdf", size=1, sha=f"{k:064d}", now=now())
        db.commit()
        seen = []
        listener = lambda *a: seen.append(1)                      # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert client.get("/api/b/ours/import/statements").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)
    assert count(2) == count(12)


def test_opening_import_takes_no_write_lock_when_nothing_is_due(client, db, ddb, ours, engine):
    """Phase 18: GET /import/statements swept and committed on every open and on each 3 s poll while a statement read,
    taking the book's write lock and moving Plan's inputs. With nothing due it now only reads."""
    from steward.deps import now
    from tests.test_concurrency import writer_reaches_begin
    _jr(ddb, ours)
    login(client, "jr")
    S.add(db, user_id=1, filename="s.pdf", size=1, sha="0" * 64, now=now())
    db.commit()
    with writer_reaches_begin(engine) as reached:
        assert client.get("/api/b/ours/import/statements").status_code == 200
    assert not reached.is_set()


def test_a_due_sweep_still_runs_on_open(client, db, ddb, ours, engine, fake_clock):
    from datetime import timedelta

    from steward.deps import now
    from tests.test_concurrency import writer_reaches_begin
    _jr(ddb, ours)
    login(client, "jr")
    S.add(db, user_id=1, filename="s.pdf", size=1, sha="0" * 64, now=now())
    db.commit()
    fake_clock.advance(S.TTL + timedelta(minutes=1))
    with writer_reaches_begin(engine) as reached:
        r = client.get("/api/b/ours/import/statements")
    assert reached.is_set() and r.status_code == 200
    assert [s["state"] for s in r.json()["statements"]] == ["cleared"]
