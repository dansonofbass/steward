"""POST /import/files (spec P2, P3, P5, P21, P36, P38): one request per file, each identified on its own, an account
suggested, staged in memory only."""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from steward.db.directory_models import User
from steward.db.models import ImportBatch, ImportHint, ImportLayout
from tests.factories import login, make_account, make_person
from tests.import_helpers import stage

HEADER = {"content-type": "application/octet-stream", "x-filename": "a.csv"}


def _jr(ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])


def test_a_known_file_is_identified_with_its_rows(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    r = stage(client, "chase-checking.csv")
    assert r.status_code == 201
    [f] = r.json()["files"]
    assert r.json()["batch"].startswith("b_") and f["token"].startswith("f_")
    assert (f["kind"], f["state"], f["label"], f["rows"], f["from"], f["to"], f["error"]) == \
        ("csv", "known", "Chase checking", 4, "2024-10-14", "2024-10-21", None)


def test_a_new_layout_carries_its_columns_sign_dates_and_a_masked_sample(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    [f] = stage(client, "amex-basic.csv").json()["files"]
    lay = f["layout"]
    assert (f["state"], f["label"], lay["header"], lay["mapping"], lay["negate"], lay["date_format"], lay["reading"]) == \
        ("new", None, ["Date", "Description", "Amount"], {"date": 0, "description": 1, "amount": 2}, None, "%m/%d/%Y",
         "month/day/year")
    assert lay["sign"] == {"credit": {"verdict": "negate", "lean": "positive"}, "bank": {"verdict": None, "lean": "positive"}}
    assert lay["sample"][0] == ["10/02/2024", "BLUE BOTTLE COFFEE", "6.50"] and len(lay["sample"]) == 5
    [amex] = stage(client, "amex-extended.csv", batch=None).json()["files"]
    assert {row[3] for row in amex["layout"]["sample"]} == {"••••0001"}


def test_a_header_whose_names_guess_too_little_stages_for_the_confirm(client, ddb, ours):
    """P1, P12: odd header names reach the column confirm once, never "couldn't be read as a CSV"."""
    _jr(ddb, ours)
    login(client, "jr")
    raw = b"Run Date,Payee Name,Amount\n10/14/2024,BLUE BOTTLE,6.50\n10/15/2024,PAYROLL,-2100.00\n"
    [f] = stage(client, "odd.csv", raw).json()["files"]
    lay = f["layout"]
    assert (f["state"], f["error"], lay["header"], lay["mapping"], lay["date_format"]) == \
        ("new", None, ["Run Date", "Payee Name", "Amount"], {"amount": 2}, None)
    assert f["held"] == "2 rows can't be read. Check the columns."
    assert lay["sample"] == [["10/14/2024", "BLUE BOTTLE", "6.50"], ["10/15/2024", "PAYROLL", "-2100.00"]]


def test_the_date_question_carries_its_example_and_options(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    [f] = stage(client, "wise-dmy-ambiguous.csv").json()["files"]
    assert f["layout"]["date_question"] == {"example": "03-04-2024", "options": [
        {"format": "%m-%d-%Y", "label": "March 4", "reading": "month/day/year"},
        {"format": "%d-%m-%Y", "label": "April 3", "reading": "day/month/year"}]}


def test_rows_left_out_and_unreadable_rows_are_counted(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    [f] = stage(client, "paypal.csv").json()["files"]
    assert f["left_out"] == {"pending": 1, "balance": 0, "totals": 0, "currency": 1}
    [bad] = stage(client, "mostly-bad.csv").json()["files"]
    assert (bad["unreadable"], bad["held"], len(bad["errors"])) == (30, "30 rows can't be read. Check the columns.", 3)


def test_a_multi_account_ofx_is_a_line_per_account(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    files = stage(client, "two-accounts.ofx").json()["files"]
    assert [(f["name"], f["kind"], f["state"], f["label"], f["rows"]) for f in files] == [
        ("two-accounts.ofx · ••1111", "ofx", "known", "OFX", 2), ("two-accounts.ofx · ••2222", "ofx", "known", "OFX", 2)]
    assert all(f["layout"] is None for f in files)


def test_refused_files_and_a_second_copy_are_entries_with_no_token(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    batch = stage(client, "amex-basic.csv").json()["batch"]
    again = stage(client, "amex-basic.csv", batch=batch).json()
    assert again["batch"] == batch
    assert [(f["token"], f["error"]) for f in again["files"]] == [(None, "This file is already in the batch.")]
    for name, error in (("renamed.xlsx.csv", "Excel files can't be read yet. Save it as CSV and try again."),
                        ("decimal-comma.csv", "Amounts like 1.234,56 can't be read yet."),
                        ("header-only.csv", "This file has no rows.")):
        [f] = stage(client, name, batch=batch).json()["files"]
        assert (f["token"], f["state"], f["error"]) == (None, "error", error)


def test_a_file_over_5_mb_is_refused_by_the_handler(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    r = client.post("/api/b/ours/import/files", content=b"a,b\n" * (5 * 1024 * 1024 // 4 + 1), headers=HEADER)
    assert (r.status_code, r.json()) == (413, {"error": "That file is bigger than 5 MB."})


# The parse runs in a worker thread, where the default signal timeout can't reach it, so this uses the thread method.
# That doesn't bound a quadratic pattern either: one long `re` call holds the interpreter lock, and the timer thread
# needs it to dump the stacks, so should the class come back this test would hang, not fail. What fails fast then is
# the scan in tests/test_linear_parsing.py, and the 5 MB tests there that call the parser directly.
@pytest.mark.timeout(120, method="thread")
def test_a_5_mb_ofx_of_unclosed_transactions_is_refused_in_time(client, ddb, ours):
    """SEC-3: one such file used to hold the server for hours (tests/test_linear_parsing.py)."""
    _jr(ddb, ours)
    login(client, "jr")
    body = b"<OFX>" + b"<STMTTRN>" * ((5 * 1024 * 1024 - 5) // 9)
    r = client.post("/api/b/ours/import/files", content=body, headers={**HEADER, "x-filename": "x.ofx"})
    assert r.status_code == 201
    [f] = r.json()["files"]
    assert (f["token"], f["state"], f["error"]) == (None, "error", "No transactions were found in this OFX/QFX file.")


def test_the_body_must_say_its_a_file(client, ddb, ours):
    """Not a CORS-safelisted type, so a cross-site page can't post one without a preflight (as json_object's ruling 0).
    The file's own type is fine (text/csv, application/x-ofx)."""
    _jr(ddb, ours)
    login(client, "jr")
    for kind in ("text/plain", "multipart/form-data; boundary=x", "application/x-www-form-urlencoded", ""):
        r = client.post("/api/b/ours/import/files", content=b"Date,Description,Amount\n",
                        headers={"content-type": kind, "x-filename": "a.csv"})
        assert (r.status_code, r.json()) == (415, {"error": "That request wasn't understood."}), kind
    ok = client.post("/api/b/ours/import/files", content=b"Date,Description,Amount\n10/14/2024,A,-1.00\n",
                     headers={"content-type": "text/csv", "x-filename": "a.csv"})
    assert ok.status_code == 201


def test_a_declared_length_over_the_cap_is_refused_before_reading(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    r = client.post("/api/b/ours/import/files", content=b"x", headers={**HEADER, "content-length": str(5 * 1024 * 1024 + 1)})
    assert (r.status_code, r.json()) == (413, {"error": "That file is bigger than 5 MB."})


def test_a_4_mb_upload_makes_no_temporary_file(client, ddb, ours, monkeypatch):
    """The coordinator's binding fix (plan Engineering choice 22): Starlette writes a multipart part over 1 MB to a temp
    file, and the NAS has no tmpfs. The route takes the raw body, so no temporary file is ever made."""
    import inspect

    from fastapi import UploadFile

    from steward.api import imports

    def refuse(*a, **k):
        raise AssertionError("a temporary file was made")
    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, refuse)
    _jr(ddb, ours)
    login(client, "jr")
    line = b"10/14/2024,SHOP NUMBER ONE TWO THREE FOUR,-1.00\n"         # 49 bytes: 4 MB stays under 100,000 rows
    rows = line * (4 * 1024 * 1024 // len(line))
    assert stage(client, "four-mb.csv", b"Date,Description,Amount\n" + rows).status_code == 201
    params = inspect.signature(imports.stage_file).parameters.values()
    assert not any(p.annotation in (UploadFile, "UploadFile") for p in params)


def test_an_expired_or_unknown_batch_is_410(client, ddb, ours, fake_clock):
    _jr(ddb, ours)
    login(client, "jr")
    batch = stage(client, "amex-basic.csv").json()["batch"]
    fake_clock.advance(timedelta(minutes=30))
    for r in (stage(client, "first-cu.csv", batch=batch), client.get(f"/api/b/ours/import/batch/{batch}"),
              stage(client, "first-cu.csv", batch="b_nope")):
        assert (r.status_code, r.json()) == (410, {"error": "These files expired. Add them again."})


def test_a_fourth_batch_expires_the_oldest_and_its_next_call_says_so(client, ddb, ours, fake_clock):
    """At most 3 open batches per person per book: a 4th drops the least recently touched, whose next call is the
    spec's expired answer (the screen keeps the names and says "These files expired. Add them again.")."""
    _jr(ddb, ours)
    login(client, "jr")
    batches = []
    for name in ("amex-basic.csv", "first-cu.csv", "discover.csv", "citi.csv"):
        batches.append(stage(client, name).json()["batch"])
        fake_clock.advance(timedelta(minutes=1))
    for r in (client.get(f"/api/b/ours/import/batch/{batches[0]}"), stage(client, "venmo.csv", batch=batches[0])):
        assert (r.status_code, r.json()) == (410, {"error": "These files expired. Add them again."})
    assert all(client.get(f"/api/b/ours/import/batch/{b}").status_code == 200 for b in batches[1:])


def test_room_is_checked_before_the_file_is_parsed(app, client, ddb, ours, monkeypatch):
    from steward.services import import_staging as S

    _jr(ddb, ours)
    login(client, "jr")
    raw = b"Date,Description,Amount\n10/14/2024,SHOP,-1.00\n"
    monkeypatch.setattr(app.state, "import_staging", S.ImportStaging(cap=len(raw) * S.RAW_FACTOR - 1))

    def never(*_a, **_k):
        raise AssertionError("parsed a file there was no room for")
    monkeypatch.setattr(S, "build", never)
    r = stage(client, "a.csv", raw)
    assert (r.status_code, r.json()) == (503, {"error": "Steward is busy with other files. Try again in a few minutes."})


def test_a_new_app_has_no_staged_files(settings, books, ddb, ours):
    from fastapi.testclient import TestClient

    from steward.app import create_app
    _jr(ddb, ours)
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "jr")
        batch = stage(c, "amex-basic.csv").json()["batch"]
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "jr")
        assert c.get(f"/api/b/ours/import/batch/{batch}").status_code == 410


def test_the_batch_answers_again_and_a_file_can_be_dropped(client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    first = stage(client, "amex-basic.csv").json()
    batch, token = first["batch"], first["files"][0]["token"]
    stage(client, "first-cu.csv", batch=batch)
    again = client.get(f"/api/b/ours/import/batch/{batch}").json()
    assert [f["name"] for f in again["files"]] == ["amex-basic.csv", "first-cu.csv"]
    assert client.delete(f"/api/b/ours/import/files/{token}").status_code == 204
    assert [f["name"] for f in client.get(f"/api/b/ours/import/batch/{batch}").json()["files"]] == ["first-cu.csv"]
    assert client.delete(f"/api/b/ours/import/files/{token}").status_code == 404


def test_another_persons_token_and_batch_are_out_of_reach(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    make_person(ddb, "sam", [(ours.id, "manager")])
    login(client, "jr")
    first = stage(client, "amex-basic.csv").json()
    login(client, "sam")
    assert client.delete(f"/api/b/ours/import/files/{first['files'][0]['token']}").status_code == 404
    assert client.get(f"/api/b/ours/import/batch/{first['batch']}").status_code == 410


def test_viewers_cant_stage_or_read_a_batch(client, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    assert stage(client, "amex-basic.csv").status_code == 404
    assert client.get("/api/b/ours/import/batch/b_any").status_code == 404


def test_staging_writes_nothing_to_disk(client, ddb, ours, settings, tmp_path, monkeypatch):
    """P3: nothing from a file touches disk before commit, under the data dir or the temp folder. The temp folder is
    this test's own, so any temporary file (a spooled upload, say) would land where the test can see it."""
    scratch = tmp_path / "scratch-tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    _jr(ddb, ours)
    login(client, "jr")
    client.get("/api/b/ours/import/batches")                    # the book's files exist before the listing

    def listing():
        return {str(p) for root in (Path(settings.data_dir), scratch) for p in root.rglob("*")}
    before = listing()
    big = b"Date,Description,Amount\n" + b"10/14/2024,SHOP ZORBLAX,-1.00\n" * 60_000      # about 1.9 MB
    assert stage(client, "big.csv", big).status_code == 201
    assert listing() == before


def _accounts(db):
    from steward.db.models import Institution, Source
    chase = Institution(name="Chase", source=Source.simplefin)
    db.add(chase)
    db.flush()
    a = make_account(db, "Card 1234", type="credit")
    b = make_account(db, "Joint checking", type="checking", source="simplefin", institution_name="Chase")
    return a, b


def test_the_suggestion_order_hint_layout_digits_name(client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    card, chase = _accounts(db)
    db.add(ImportHint(key="ofx:121000000:6789", account_id=chase.id, updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    db.add(ImportLayout(key="h:9bcfe1f64b691063bb60a855d7736ffcdb199c0b3bd0bd6c782a805d1f4fc7d0", label="Amex",
                        header='["Date", "Description", "Amount"]', mapping='{"date": 0, "description": 1, "amount": 2}',
                        negate=True, date_format="%m/%d/%Y", account_id=card.id,
                        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    db.commit()
    pick = lambda name, raw=None: (lambda f: (f["account_id"], f["suggested_by"]))(stage(client, name, raw).json()["files"][0])  # noqa: E731
    assert pick("bank.ofx") == (chase.id, "hint")
    assert pick("amex-basic.csv") == (card.id, "layout")
    other = b"Post Date,Payee,Total\n10/14/2024,A,-1.00\n"          # not the remembered header
    assert pick("activity-1234.csv", other) == (card.id, "digits")
    assert pick("Chase-checking-2024.csv", other) == (chase.id, "name")
    assert pick("statement.csv", other) == (None, None)


def test_a_file_imported_before_says_when(client, db, ddb, ours):
    import hashlib

    from tests.bank_files import read
    _jr(ddb, ours)
    login(client, "jr")
    card = make_account(db, "Card", type="credit")
    uid = ddb.scalar(select(User.id).where(User.username == "jr"))
    db.add(ImportBatch(account_id=card.id, filename="chase.csv", format="chase_checking", row_count=4, imported_by=uid,
                       imported_at=datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc),
                       content_sha256=hashlib.sha256(read("chase-checking.csv")).hexdigest()))
    db.commit()
    assert stage(client, "chase-checking.csv").json()["files"][0]["imported_before"] == "2026-10-12"
