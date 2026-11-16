"""The reader with scans (spec P6, P7, P17, P26, P31-P33): page by page, one PNG at a time, bytes kept until the last
page; a layout the model can't give is read as a scan; a restart keeps the pages read and the same file finishes it;
a page that fails twice says so with Try again."""
import json

import pytest

from steward.db.models import StatementStage
from steward.services.statements import scan as scan_read
from steward_pdf.sandbox import Rendered
from steward.services.statements.stage import SCAN_MARK
from tests.factories import login, make_account, make_person
from tests.statement_files import pdf
from tests.statement_helpers import StandIn, answering, truth_answers, upload


def _jr(ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])


def _stage(db, sid):
    db.rollback()                       # end the test session's read snapshot, so it sees what the reader committed
    return db.get(StatementStage, sid)


def _drain(app):
    while app.state.statements.run_once():
        pass


def test_a_scan_reads_page_by_page_and_adds_up(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    stand_in = answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    make_account(db, "Northpoint 2218", type="credit")
    sid = upload(client, "scan.pdf", pdf("capone_card", "scan")[0]).json()["statement"]["id"]
    app.state.statements.run_once()                                       # extract: every page a scan
    assert (_stage(db, sid).kind, _stage(db, sid).state) == ("scan", "queued")
    app.state.statements.run_once()                                       # page 1
    s = _stage(db, sid)
    assert (s.state, s.pages_done, s.pages) == ("queued", 1, truth.pages)
    line = next(x for x in client.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == sid)
    assert line["progress"] == {"done": 1, "of": truth.pages}
    _drain(app)
    s = _stage(db, sid)
    assert (s.state, s.gap_cents, s.account_id is not None) == ("ready", 0, True)
    assert all(r["scan"] for r in json.loads(s.rows)) and [c[0] for c in stand_in.page_calls] == list(range(1, truth.pages + 1))
    assert not app.state.statements.has(ours.id, sid) and app.state.statements.held_bytes() == 0


def test_one_png_at_a_time_and_none_after(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("boa_checking")[1]
    seen = []
    reader = app.state.statements

    def pages(n):
        seen.append(reader._png)
        return truth_answers(truth)
    answering(app, StandIn(pages=pages), features=("layout", "scan"))
    upload(client, "scan.pdf", pdf("boa_checking", "scan")[0])
    _drain(app)
    assert seen and all(0 < x <= 3 * 1024 * 1024 for x in seen) and reader._png == 0


def test_gateway_without_the_vision_model_leaves_scans_waiting(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn(pages=truth_answers(pdf("boa_checking")[1])), features=("layout",))
    sid = upload(client, "scan.pdf", pdf("boa_checking", "scan")[0]).json()["statement"]["id"]
    _drain(app)
    assert _stage(db, sid).state == "waiting" and app.state.statements.has(ours.id, sid)


def test_a_layout_the_model_cant_give_is_read_as_a_scan(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("boa_checking")[1]
    stand_in = answering(app, StandIn(answer=None, pages=truth_answers(truth)), features=("layout", "scan"))
    sid = upload(client, "text.pdf", pdf("boa_checking")[0]).json()["statement"]["id"]
    _drain(app)
    s = _stage(db, sid)
    assert len(stand_in.calls) == 2 and stand_in.page_calls and (s.kind, s.state, s.gap_cents) == ("text", "ready", None)   # no account yet: nothing to check by
    assert s.layout_id is None and json.loads(s.statement)["scan"] is True


def test_a_mixed_file_is_read_as_a_scan(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    stand_in = answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    sid = upload(client, "mixed.pdf", pdf("capone_card", "mixed")[0]).json()["statement"]["id"]
    _drain(app)
    assert (_stage(db, sid).kind, stand_in.calls) == ("mixed", []) and len(stand_in.page_calls) == truth.pages


def test_picking_an_account_of_the_other_sense_rereads_the_scan(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    checking = make_account(db, "Checking", type="checking")
    card = make_account(db, "Card", type="credit")
    sid = upload(client, "scan.pdf", pdf("capone_card", "scan")[0]).json()["statement"]["id"]
    client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": checking.id})
    _drain(app)
    assert _stage(db, sid).state == "off"                          # read as a bank, a card's statement doesn't add up
    r = client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": card.id})
    assert (r.json()["statement"]["state"], r.json()["statement"]["gap_cents"]) == ("ready", 0)


def test_a_scan_with_no_account_has_no_gap_until_one_is_chosen(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    sid = upload(client, "scan.pdf", pdf("capone_card", "scan")[0]).json()["statement"]["id"]
    _drain(app)                                                     # no account exists, so none is suggested

    def line():
        return next(x for x in client.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == sid)
    s = _stage(db, sid)
    assert (s.account_id, s.gap_cents, s.state) == (None, None, "ready")
    assert (line()["needs_account"], line()["gap_cents"], line()["account_id"]) == (True, None, None)
    assert client.patch(f"/api/b/ours/import/statements/{sid}", json={"anyway": True}).status_code == 409
    checking = make_account(db, "Checking", type="checking")
    card = make_account(db, "Card", type="credit")
    r = client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": card.id}).json()["statement"]
    assert (r["needs_account"], r["state"], r["gap_cents"]) == (False, "ready", 0)
    r = client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": checking.id}).json()["statement"]
    assert (r["needs_account"], r["state"]) == (False, "off") and r["gap_cents"]
    r = client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": None}).json()["statement"]
    assert (r["needs_account"], r["state"], r["gap_cents"]) == (True, "ready", None)


def test_an_edited_scan_keeps_its_rows_when_the_account_changes_sense(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    checking = make_account(db, "Checking", type="checking")
    card = make_account(db, "Card", type="credit")
    sid = upload(client, "scan.pdf", pdf("capone_card", "scan")[0]).json()["statement"]["id"]
    client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": checking.id})
    _drain(app)
    s = _stage(db, sid)
    rows = json.loads(s.rows)
    rows[0]["state"] = "edited"
    s.rows = json.dumps(rows)
    db.commit()
    client.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": card.id})
    after = _stage(db, sid)
    assert json.loads(after.rows) == rows and json.loads(after.statement)["kind"] != "bank"


def test_scan_rows_are_marked_for_checking_and_import_as_pdf_scan(app, client, db, ddb, ours):
    from sqlalchemy import select

    from steward.db.models import ImportBatch
    from tests.statement_helpers import commit
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("boa_checking")[1]
    answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    acct = make_account(db, "Checking 3456", type="checking")
    sid = upload(client, "scan.pdf", pdf("boa_checking", "scan")[0]).json()["statement"]["id"]
    _drain(app)
    detail = client.get(f"/api/b/ours/import/statements/{sid}").json()
    assert detail["rows"] and all(r["scan"] for r in detail["rows"])
    assert commit(client, [{"id": sid, "account_id": acct.id, "include": []}]).status_code == 201
    db.rollback()
    assert db.scalar(select(ImportBatch.format)) == "pdf_scan"


def test_a_page_failed_retry_needs_its_bytes(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn(pages=None), features=("layout", "scan"))
    sid = upload(client, "scan.pdf", pdf("boa_checking", "scan")[0]).json()["statement"]["id"]
    _drain(app)
    assert _stage(db, sid).error == "page_failed"
    app.state.statements.drop(ours.id, sid)
    assert client.post(f"/api/b/ours/import/statements/{sid}/retry").status_code == 409


def test_a_page_that_fails_twice_says_so_and_try_again_goes_on(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    answers = truth_answers(truth)
    make_account(db, "Northpoint 2218", type="credit")
    stand_in = answering(app, StandIn(pages=lambda n: None if n == 2 else answers), features=("layout", "scan"))
    sid = upload(client, "scan.pdf", pdf("capone_card", "scan")[0]).json()["statement"]["id"]
    _drain(app)
    s = _stage(db, sid)
    assert (s.state, s.error, s.pages_done) == ("error", "page_failed", 1)
    line = next(x for x in client.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == sid)
    assert line["error_text"] == "The gateway couldn't read page 2 · Try again"
    stand_in.pages = answers
    assert client.post(f"/api/b/ours/import/statements/{sid}/retry").status_code == 200
    _drain(app)
    assert _stage(db, sid).state == "ready"


def test_a_restarted_scan_resumes_from_the_next_page(app, client, db, ddb, ours, settings, books):
    from fastapi.testclient import TestClient

    from steward.app import create_app
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("capone_card")[1]
    make_account(db, "Northpoint 2218", type="credit")
    answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    data = pdf("capone_card", "scan")[0]
    sid = upload(client, "scan.pdf", data).json()["statement"]["id"]
    app.state.statements.run_once()
    app.state.statements.run_once()                                       # page 1 read, then the restart
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as again:
        login(again, "jr")
        s = _stage(db, sid)
        assert (s.state, s.error, s.pages_done) == ("error", "restarted", 1)
        line = next(x for x in again.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == sid)
        assert line["error_text"] == f"Steward restarted on page 1 of {truth.pages}. Add the file again to finish."
        stand_in = answering(again.app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
        r = upload(again, "scan.pdf", data)
        assert (r.status_code, r.json()["statement"]["id"]) == (201, sid)
        _drain(again.app)
        assert [c[0] for c in stand_in.page_calls] == list(range(2, truth.pages + 1)) and _stage(db, sid).state == "ready"


def _line_of(client, sid):
    return next(x for x in client.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == sid)


def _boom(*_a, **_k):
    raise ValueError("a bug while assembling")


@pytest.mark.parametrize("breaks", ["mask_answer", "assemble", "proposal"])
def test_a_scan_that_fails_while_assembling_says_so_and_can_be_added_again(app, client, db, ddb, ours, monkeypatch,
                                                                          breaks):
    """Not 'reading' until a restart: the line says the file couldn't be read, its bytes go, and adding the same file
    again starts it afresh."""
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("boa_checking")[1]
    answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "scan"))
    data = pdf("boa_checking", "scan")[0]
    sid = upload(client, "scan.pdf", data).json()["statement"]["id"]
    app.state.statements.run_once()                                       # extract
    if breaks == "proposal":
        s = _stage(db, sid)
        s.proposal = SCAN_MARK + ", not json"
        db.commit()
    else:
        monkeypatch.setattr(scan_read, breaks, _boom)
    _drain(app)
    s = _stage(db, sid)
    assert (s.state, s.error) == ("error", "unreadable") and not app.state.statements.has(ours.id, sid)
    assert _line_of(client, sid)["error_text"] == "This PDF couldn't be read."
    _readded(app, client, db, ours, data)


def _readded(app, client, db, ours, data):
    """An upload of a file whose line has an error other than restarted or page_failed deletes it and adds it afresh
    (SQLite may give the new line the old id)."""
    r = upload(client, "scan.pdf", data)
    assert r.status_code == 201
    s = _stage(db, r.json()["statement"]["id"])
    assert (s.state, s.error, s.lines, s.proposal, s.pages_done) == ("queued", None, None, None, 0)
    assert app.state.statements.has(ours.id, s.id)


def test_a_late_answer_for_a_page_already_read_is_dropped(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answers = truth_answers(pdf("boa_checking")[1])
    sid = None

    def pages(n):
        s = _stage(db, sid)
        s.pages_done = n                                                  # meanwhile, this page was read
        db.commit()
        return answers
    answering(app, StandIn(pages=pages), features=("layout", "scan"))
    sid = upload(client, "scan.pdf", pdf("boa_checking", "scan")[0]).json()["statement"]["id"]
    app.state.statements.run_once()                                       # extract
    before = _stage(db, sid).proposal
    app.state.statements.run_once()                                       # page 1, answered late
    s = _stage(db, sid)
    assert (s.proposal, s.pages_done, s.tries) == (before, 1, 0) and json.loads(s.proposal)["pages"] == []


def test_a_page_that_wont_render_says_why_and_the_file_can_be_added_again(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn(pages=truth_answers(pdf("boa_checking")[1])), features=("layout", "scan"))
    data = pdf("boa_checking", "scan")[0]
    sid = upload(client, "scan.pdf", data).json()["statement"]["id"]
    app.state.statements.run_once()                                       # extract
    app.state.statements._render = lambda _data, _n: Rendered(None, 0, 0, "too_slow")
    _drain(app)
    s = _stage(db, sid)
    assert (s.state, s.error, stand_in.page_calls) == ("error", "too_slow", [])
    assert not app.state.statements.has(ours.id, sid)
    assert _line_of(client, sid)["error_text"] == "This PDF took too long to read."
    _readded(app, client, db, ours, data)


def test_a_restart_turns_a_failed_page_into_restarted(app, client, db, ddb, ours):
    """P32: the bytes a Try again needs went with the restart; the line asks for the file again."""
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn(pages=None), features=("layout", "scan"))
    sid = upload(client, "scan.pdf", pdf("boa_checking", "scan")[0]).json()["statement"]["id"]
    _drain(app)
    assert (_stage(db, sid).error, _stage(db, sid).pages_done) == ("page_failed", 0)
    app.state.statements.recover()
    s = _stage(db, sid)
    assert (s.state, s.error) == ("error", "restarted")
    assert _line_of(client, sid)["error_text"].startswith("Steward restarted on page")


def test_a_scan_without_its_opening_balance_can_be_imported_anyway(app, client, db, ddb, ours):
    """P17: no file reaches a dead end while the gateway answers. A balance the model didn't read (P25 lets it be null)
    leaves the scan off with no gap; row review says why, and Import anyway takes it, marked."""
    from sqlalchemy import select

    from steward.db.models import ImportBatch
    from tests.statement_helpers import commit
    _jr(ddb, ours)
    login(client, "jr")
    truth = pdf("boa_checking")[1]
    answers = truth_answers(truth)
    answers[0]["opening"] = None
    answering(app, StandIn(pages=answers), features=("layout", "scan"))
    acct = make_account(db, "Checking 3456", type="checking")
    sid = upload(client, "scan.pdf", pdf("boa_checking", "scan")[0]).json()["statement"]["id"]
    _drain(app)
    s = _stage(db, sid)
    assert (s.state, s.gap_cents, s.error) == ("off", None, None)
    detail = client.get(f"/api/b/ours/import/statements/{sid}").json()
    assert {"page": 1, "text": "the opening balance wasn't found."} in detail["unreadable"]
    r = client.patch(f"/api/b/ours/import/statements/{sid}", json={"anyway": True})
    assert (r.status_code, r.json()["statement"]["anyway"]) == (200, True)
    assert commit(client, [{"id": sid, "account_id": acct.id, "include": []}]).status_code == 201
    db.rollback()
    batch = db.scalars(select(ImportBatch)).one()
    assert (batch.check_state, batch.check_gap_cents) == ("anyway", None)
