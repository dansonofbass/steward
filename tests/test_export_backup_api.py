"""POST /export/backup and GET /export/backup/{token} (spec P29, P30): made once at a time, a one-time token for the
same person within 10 minutes, the folder 0700 while it waits and gone after, recorded, and the passphrase never in a
log, a response, the event log or the change record."""
import json
import logging
import stat
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from steward.db.models import ChangeRecord, EventLog
from steward.services import book_export as X
from tests.factories import login, make_person

URL = "/api/b/ours/export/backup"
PASS = "zorblax-quillfeather-77"


def _jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")


def _make(client, slug="ours"):
    return client.post(f"/api/b/{slug}/export/backup", json={"passphrase": PASS, "again": PASS})


def test_make_then_download_once(client, ddb, ours, settings):
    _jr(client, ddb, ours)
    r = _make(client)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"token", "filename", "bytes"} and body["filename"] == "steward-ours-2026-10-30.steward-backup"
    [folder] = Path(settings.export_tmp_dir).glob("steward-export-*")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    got = client.get(f"{URL}/{body['token']}")
    assert got.status_code == 200 and got.content[:2] == b"PK" and len(got.content) == body["bytes"]
    assert got.headers["content-disposition"] == 'attachment; filename="steward-ours-2026-10-30.steward-backup"'
    assert got.headers["cache-control"] == "no-store"
    assert not folder.exists()
    again = client.get(f"{URL}/{body['token']}")
    assert (again.status_code, again.json()) == (404, {"error": "That download has expired. Make the backup again."})


def test_the_link_lasts_ten_minutes(client, ddb, ours, fake_clock):
    _jr(client, ddb, ours)
    keep = _make(client).json()["token"]
    fake_clock.advance(timedelta(minutes=9, seconds=59))
    assert client.get(f"{URL}/{keep}").status_code == 200
    gone = _make(client).json()["token"]
    fake_clock.advance(timedelta(minutes=10))
    assert client.get(f"{URL}/{gone}").status_code == 404


def test_another_persons_link_is_404(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "sam", [(ours.id, "manager")])
    login(client, "jr")
    token = _make(client).json()["token"]
    login(client, "sam")
    assert client.get(f"{URL}/{token}").status_code == 404


def test_the_passphrase_rules_and_no_echo(client, ddb, ours):
    _jr(client, ddb, ours)
    for body, error in (({"passphrase": "short", "again": "short"}, "Use at least 12 characters."),
                        ({"passphrase": PASS, "again": PASS + "x"}, "The two don't match."),
                        ({"passphrase": 12, "again": 12}, "Use at least 12 characters."), ({}, "Use at least 12 characters.")):
        r = client.post(URL, json=body)
        assert (r.status_code, r.json()) == (422, {"error": error})
        assert PASS.encode() not in r.content and b"short" not in r.content


def test_a_second_backup_while_one_is_made_is_429(client, ddb, ours):
    """Review focus 3."""
    _jr(client, ddb, ours)
    X.LOCK.acquire()
    try:
        r = _make(client)
    finally:
        X.LOCK.release()
    assert (r.status_code, r.json()) == (429, {"error": "Another backup is being made. Try again in a minute."})


def test_the_passphrase_is_never_logged_returned_or_recorded(client, margaret, mdb, caplog):
    login(client, "jr")
    caplog.set_level(logging.DEBUG)
    responses = [_make(client, "margaret-ellis")]
    responses.append(client.get(f"/api/b/margaret-ellis/export/backup/{responses[0].json()['token']}"))
    assert all(PASS.encode() not in r.content for r in responses)
    assert PASS not in caplog.text
    mdb.rollback()
    events = mdb.scalars(select(EventLog.message).where(EventLog.kind == "export")).all()
    assert events == ["Jr made an encrypted backup of this book"]
    [rec] = mdb.scalars(select(ChangeRecord).where(ChangeRecord.action == "export.backup")).all()
    assert PASS not in (rec.after or "") and json.loads(rec.after)["bytes"] > 0
    changes = client.get("/api/b/margaret-ellis/changes", params={"kind": "imports"}).json()
    assert PASS not in json.dumps(changes)
    assert "made an encrypted backup of the book" in json.dumps(changes)


def test_viewers_get_404_and_there_is_no_web_restore(client, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    assert _make(client).status_code == 404
    assert client.get(f"{URL}/anything").status_code == 404
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    assert client.post("/api/b/ours/export/restore", json={}).status_code in (404, 405)


def test_startup_sweeps_every_leftover_folder(settings, books):
    from fastapi.testclient import TestClient

    from steward.app import create_app
    root = Path(settings.export_tmp_dir)
    (root / "steward-export-left-over").mkdir(parents=True)
    (root / "not-ours").mkdir()
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net"):
        assert sorted(p.name for p in root.iterdir()) == ["not-ours"]
