import asyncio

from sqlalchemy import func, select

from steward.api.limits import BodyLimit, limit_for
from steward.db.models import StoredFile
from tests.factories import login, make_person

BOOK = "/api/b/margaret-ellis/inventory"
PDF = b"%PDF-1.4\n%made-up statement\n%%EOF\n"
MB = 1024 * 1024
TOO_BIG = "Not attached: it's over 25 MB. Steward takes files up to 25 MB."


def _chunks(total, size=64 * 1024):
    sent = 0
    while sent < total:
        n = min(size, total - sent)
        sent += n
        yield b"x" * n


def test_a_chunked_upload_over_the_cap_is_refused_and_leaves_nothing(margaret, client, books, mdb):
    login(client, "jr")
    folder = books.files_dir(margaret)
    r = client.post(f"{BOOK}/files", content=_chunks(27 * MB),
                    headers={"content-type": "multipart/form-data; boundary=zz"})
    assert (r.status_code, r.json()) == (413, {"error": TOO_BIG})
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(StoredFile)) == 0
    assert not folder.exists() or list(folder.iterdir()) == []


def test_normal_uploads_under_the_cap_still_work(margaret, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/files", files={"file": ("Statement.pdf", PDF, "application/pdf")})
    assert r.status_code == 201
    r = client.post(f"{BOOK}/files", files={"file": ("big.pdf", b"%PDF-" + b"0" * (24 * MB), "application/pdf")})
    assert r.status_code == 201


def test_an_ordinary_json_route_refuses_a_2_mb_body(margaret, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/items", content=b"{" + b" " * (2 * MB) + b"}", headers={"content-type": "application/json"})
    assert (r.status_code, r.json()) == (413, {"error": "That request is too large."})
    r = client.post(f"{BOOK}/items", content=_chunks(2 * MB), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_each_upload_route_has_its_own_cap_and_message():
    assert limit_for("/api/b/ours/import/files") == (6 * MB, "That file is bigger than 5 MB.")
    assert limit_for("/api/b/ours/import/preview") == (MB, "That request is too large.")
    assert limit_for("/api/b/ours/import/batch/commit") == (MB, "That request is too large.")
    assert limit_for("/api/b/ours/ss/import") == (2 * MB, "That file is bigger than 1 MB.")
    assert limit_for("/api/b/m/inventory/files") == (26 * MB, TOO_BIG)
    assert limit_for("/api/b/m/inventory/tax-forms/csv")[0] == 2 * MB
    assert limit_for("/api/b/ours/import/statements") == (15 * MB + 64 * 1024, "Bigger than 15 MB. Download it again or split it.")
    assert limit_for("/api/b/m/inventory/items") == (MB, "That request is too large.")
    assert limit_for("/api/auth/login")[0] == MB


def _run(app, path, parts, declared):
    """Drives the middleware over raw ASGI with a body that may be longer than it declared."""
    out, queue = [], list(parts)

    async def receive():
        return ({"type": "http.request", "body": queue.pop(0), "more_body": bool(queue)} if queue
                else {"type": "http.disconnect"})

    async def send(event):
        out.append(event)

    headers = [(b"content-length", str(declared).encode())] if declared is not None else []
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    asyncio.run(BodyLimit(app)(scope, receive, send))
    return out


async def _reader(scope, receive, send):
    got = 0
    while True:
        event = await receive()
        if event["type"] != "http.request":
            break
        got += len(event["body"])
        if not event.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": str(got).encode()})


def test_a_content_length_under_the_cap_followed_by_more_bytes_gets_413():
    out = _run(_reader, "/api/b/ours/inventory/items", [b"x" * 600_000, b"x" * 600_000], declared=100)
    assert out[0]["status"] == 413 and b"too large" in out[1]["body"]
    assert len(out) == 2   # the app's own answer was dropped


def test_a_declared_length_over_the_cap_is_refused_without_reading():
    out = _run(_reader, "/api/b/ours/ss/import", [], declared=3 * MB)
    assert out[0]["status"] == 413 and b"1 MB" in out[1]["body"]


def test_a_body_at_the_cap_passes_through():
    out = _run(_reader, "/api/b/ours/inventory/items", [b"x" * MB], declared=MB)
    assert out[0]["status"] == 200 and out[1]["body"] == str(MB).encode()


def test_a_staged_file_over_the_cap_is_refused_before_the_handler(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    r = client.post("/api/b/ours/import/files", content=_chunks(6 * MB + 1),
                    headers={"content-type": "application/octet-stream", "x-filename": "big.csv"})
    assert (r.status_code, r.json()) == (413, {"error": "That file is bigger than 5 MB."})
