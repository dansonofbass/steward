from sqlalchemy import func, select

from steward.db.models import StoredFile
from tests.factories import login

BOOK = "/api/b/margaret-ellis/inventory"
PDF = b"%PDF-1.4\n%made-up statement\n%%EOF\n"
ANNUITY = {"kind": "account", "name": "Deferred annuity", "owner": "margaret", "institution": "Westmark Life",
           "last4": "5521", "status": "needs_checking", "check_reason": "Typed in from a letter",
           "details": {"type": "annuity"}}


def _upload(client, name, data, **form):
    return client.post(f"{BOOK}/files", files={"file": (name, data, "application/octet-stream")},
                       data={k: str(v) for k, v in form.items()})


def test_attach_confirm_download_and_remove(frozen, margaret, client, books):
    login(client, "jr")
    item = client.post(f"{BOOK}/items", json=ANNUITY).json()
    r = _upload(client, "Westmark annual statement 2025.pdf", PDF, item_id=item["id"], confirm="true")
    assert r.status_code == 201
    out = r.json()
    assert out["file"]["label"] == "PDF" and out["file"]["uploaded_by"] == "Jr"
    assert out["item"]["status"] == "confirmed" and out["looks_like_tax_form"] is False
    assert [h["text"] for h in out["item"]["history"]][:2] == ["marked this item Confirmed", "attached Westmark annual statement 2025.pdf"]
    fid = out["file"]["id"]
    login(client, "vee")   # viewers can download (spec 2.5)
    d = client.get(f"{BOOK}/files/{fid}")
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["content-type"] == "application/pdf"
    assert d.headers["content-disposition"].startswith("attachment;")
    assert d.headers["x-content-type-options"] == "nosniff" and d.headers["cache-control"] == "no-store"
    assert client.delete(f"{BOOK}/files/{fid}").status_code == 403
    login(client, "jr")
    assert client.delete(f"{BOOK}/files/{fid}").status_code == 204
    assert not books.file_store(margaret).path(fid).exists()
    assert client.get(f"{BOOK}/files/{fid}").json() == {"error": "No such file."}
    assert client.get("/api/b/margaret-ellis/changes?kind=files").json()["changes"][0]["text"] == \
        "removed Westmark annual statement 2025.pdf from {item}"


def test_a_tax_form_name_gets_the_nudge(margaret, client):
    login(client, "jr")
    r = _upload(client, "1099-INT 2025 Harbor Savings.pdf", PDF)
    assert r.status_code == 201 and r.json()["looks_like_tax_form"] is True and r.json()["item"] is None


def test_a_big_or_disguised_upload_leaves_nothing_behind(margaret, client, books, mdb):
    login(client, "jr")
    folder = books.files_dir(margaret)
    r = _upload(client, "Westmark export.xlsx", b"PK\x03\x04")
    assert (r.status_code, r.json()["error"]) == (415, "Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV. "
                                                        "Save it as PDF or CSV and try again.")
    r = _upload(client, "fake.pdf", b"<html>not a pdf</html>")
    assert (r.status_code, r.json()["error"]) == (415, "Not attached: the file inside isn't a PDF. Save it again and try again.")
    r = _upload(client, "huge.pdf", b"%PDF-" + b"0" * (25 * 1024 * 1024))
    assert (r.status_code, r.json()["error"]) == (413, "Not attached: it's over 25 MB. Steward takes files up to 25 MB.")
    r = _upload(client, "empty.pdf", b"")
    assert (r.status_code, r.json()["error"]) == (422, "Not attached: the file is empty.")
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(StoredFile)) == 0
    assert not folder.exists() or list(folder.iterdir()) == []


def test_a_disk_failure_keeps_no_row(margaret, client, books, mdb, monkeypatch):
    login(client, "jr")
    def boom(self, file_id, data):
        raise OSError("disk full")
    monkeypatch.setattr("steward.inventory.files.FileStore.write", boom)
    r = _upload(client, "Statement.pdf", PDF)
    assert (r.status_code, r.json()["error"]) == (507, "Not attached: Steward couldn't save it. Try again in a minute.")
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(StoredFile)) == 0


def test_an_upload_to_another_books_item_or_no_file_is_refused(margaret, client):
    login(client, "jr")
    assert _upload(client, "Statement.pdf", PDF, item_id=999).json() == {"error": "No such item."}
    r = client.post(f"{BOOK}/files", data={"item_id": "1"})
    assert (r.status_code, r.json()) == (422, {"error": "Choose a file to attach."})


def test_a_removed_files_id_is_never_reused(margaret, client):
    login(client, "jr")
    first = _upload(client, "Wrong statement.pdf", PDF).json()["file"]["id"]
    assert client.delete(f"{BOOK}/files/{first}").status_code == 204
    second = _upload(client, "Right statement.pdf", PDF).json()["file"]["id"]
    assert second != first and second > first

import pytest


def test_a_non_numeric_content_length_on_upload_is_a_plain_refusal():
    import asyncio
    from fastapi import HTTPException
    from starlette.requests import Request
    from steward.api.inventory_files import upload

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                   "headers": [(b"content-length", b"abc"), (b"content-type", b"multipart/form-data; boundary=zz")]},
                  receive)
    with pytest.raises(HTTPException) as e:
        asyncio.run(upload.__wrapped__(req, None, None) if hasattr(upload, "__wrapped__") else upload(req, None, None))
    assert 400 <= e.value.status_code < 500 and isinstance(e.value.detail["error"], str)


def test_a_very_long_content_length_on_upload_is_a_plain_refusal():
    import asyncio
    from fastapi import HTTPException
    from starlette.requests import Request
    from steward.api.inventory_files import upload

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                   "headers": [(b"content-length", b"9" * 5000)]}, receive)
    with pytest.raises(HTTPException) as e:
        asyncio.run(upload(req, None, None))
    assert 400 <= e.value.status_code < 500 and isinstance(e.value.detail["error"], str)
