from sqlalchemy import inspect, select, text

from steward.db.models import EventLog, SsEarnings
from tests.test_ss_import import row, statement

XML = {"content-type": "application/xml"}
BOMB = (b'<?xml version="1.0"?><!DOCTYPE z [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        b'<osss:OnlineSocialSecurityStatementData xmlns:osss="http://ssa.gov/osss/schemas/2.0">&b;</osss:OnlineSocialSecurityStatementData>')


def _post(c, body, person="jr"):
    return c.post(f"/api/b/ours/ss/import?person={person}", content=body, headers=XML)


def test_import_keeps_years_and_amounts_only(frozen, signed_in, db, engine):
    r = _post(signed_in, statement(row(2005, 30000) + row(2006, 31000) + row(2026, -1)))
    assert r.status_code == 201
    assert {k: v for k, v in r.json().items() if k != "undo"} == {"person": "jr", "years": 2, "first_year": 2005, "last_year": 2006, "skipped": 1}
    assert db.execute(select(SsEarnings.person, SsEarnings.year, SsEarnings.earnings_cents).order_by(SsEarnings.year)).all() == \
        [("jr", 2005, 3_000_000), ("jr", 2006, 3_100_000)]
    with engine.connect() as conn:                       # nothing from the file but years and amounts, anywhere
        for table in inspect(conn).get_table_names():
            dump = repr(conn.execute(text(f'SELECT * FROM "{table}"')).all())
            assert "Pat Example" not in dump and "1982-05-01" not in dump, table
    summary = signed_in.get("/api/b/ours/ss").json()["records"]
    assert summary["jr"]["years"] == 2 and summary["jr"]["last_year"] == 2006 and summary["spouse"] is None
    assert db.scalar(select(EventLog.message)) == "Imported a Social Security earnings record: 2 years."


def test_reimport_replaces_that_persons_rows_only(frozen, signed_in, db):
    _post(signed_in, statement(row(2005, 30000) + row(2006, 31000)))
    _post(signed_in, statement(row(2010, 20000)), person="spouse")
    _post(signed_in, statement(row(2007, 40000)))
    assert db.execute(select(SsEarnings.person, SsEarnings.year).order_by(SsEarnings.person, SsEarnings.year)).all() == \
        [("jr", 2007), ("spouse", 2010)]


def test_entity_bomb_is_rejected_and_the_old_record_stays(frozen, signed_in, db):
    _post(signed_in, statement(row(2005, 30000)))
    r = _post(signed_in, BOMB)
    assert r.status_code == 422 and r.json() == {"error": "That file doesn't look like a Social Security earnings record."}
    assert db.execute(select(SsEarnings.year)).scalars().all() == [2005]


def test_foreign_and_html_files_are_rejected(frozen, signed_in, db):
    for body in (b"<html><body>my Social Security</body></html>", b"<?xml version='1.0'?><bank><row/></bank>", b"year,amount\n2005,1\n"):
        r = _post(signed_in, body)
        assert r.status_code == 422 and r.json() == {"error": "That file doesn't look like a Social Security earnings record."}
    assert db.scalar(select(SsEarnings.year)) is None


def test_person_and_size_are_checked(frozen, signed_in):
    r = _post(signed_in, statement(row(2005, 1)), person="cousin")
    assert r.status_code == 422 and r.json() == {"error": "Say whose record this is."}
    r = signed_in.post("/api/b/ours/ss/import", content=statement(row(2005, 1)), headers=XML)
    assert r.status_code == 422 and r.json() == {"error": "Say whose record this is."}
    r = _post(signed_in, b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413 and r.json() == {"error": "That file is bigger than 1 MB."}


def test_the_upload_never_touches_disk(frozen, signed_in, monkeypatch):
    import tempfile

    def no_disk(*a, **k):
        raise AssertionError("the earnings file must not be written to disk")
    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, no_disk)
    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", no_disk)
    assert _post(signed_in, statement(row(2005, 30000))).status_code == 201


def test_import_needs_sign_in(client):
    assert client.post("/api/b/ours/ss/import?person=jr", content=b"<x/>", headers=XML).status_code == 401
    assert client.get("/api/b/ours/ss").status_code == 401


def test_only_xml_or_octet_stream_content_types_are_accepted(frozen, signed_in, db):
    body = statement(row(2005, 30000))
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "application/json"):
        r = signed_in.post("/api/b/ours/ss/import?person=jr", content=body, headers={"content-type": ctype})
        assert r.status_code == 415 and r.json() == {"error": "That request wasn't understood."}, ctype
    assert db.scalar(select(SsEarnings.year)) is None
    for ctype in ("application/xml; charset=utf-8", "application/octet-stream"):
        r = signed_in.post("/api/b/ours/ss/import?person=jr", content=body, headers={"content-type": ctype})
        assert r.status_code == 201, ctype


def test_import_returns_undo_that_brings_back_the_replaced_record(frozen, signed_in, db):
    _post(signed_in, statement(row(2005, 30000) + row(2006, 31000)))
    second = _post(signed_in, statement(row(2007, 40000)))
    assert second.status_code == 201 and second.json()["undo"]
    assert signed_in.post(f"/api/b/ours/undo/{second.json()['undo']}").status_code == 200
    db.rollback()   # end the read snapshot so we see the request's commit
    assert db.execute(select(SsEarnings.person, SsEarnings.year, SsEarnings.earnings_cents).order_by(SsEarnings.year)).all() == \
        [("jr", 2005, 3_000_000), ("jr", 2006, 3_100_000)]


def test_undoing_a_first_import_removes_it(frozen, signed_in, db):
    first = _post(signed_in, statement(row(2005, 30000))).json()
    assert signed_in.post(f"/api/b/ours/undo/{first['undo']}").status_code == 200
    db.rollback()
    assert db.scalars(select(SsEarnings)).all() == []
