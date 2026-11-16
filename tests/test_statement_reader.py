"""The reader (spec P6, P7, P17, P22, P31-P33): one job at a time, extraction and learned reads before new layouts;
the gateway away leaves new layouts waiting; a restart resumes text and says so for the rest; a failure is retried
once; PDF bytes only in memory, under the caps; nothing written to disk."""
import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from steward.db.models import StatementStage
from steward.services.statements.reader import SCAN_MARK, Busy, StatementReader
from tests.factories import login, make_account, make_person
from tests.statement_files import pdf
from tests.statement_helpers import StandIn, answering, remember, scanned_pdf, upload


def _jr(ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])


def _stage(db, sid):
    db.rollback()                       # end the test session's read snapshot, so it sees what the reader committed
    return db.get(StatementStage, sid)


def test_a_learned_layout_reads_on_the_nas_alone(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn())
    remember(db, "chase_checking")
    sid = upload(client, "Statement_0324.pdf", pdf("chase_checking")[0]).json()["statement"]["id"]
    assert app.state.statements.run_once() is True
    s = _stage(db, sid)
    assert (s.state, s.gap_cents, s.kind, s.pages) == ("ready", 0, "text", pdf("chase_checking")[1].pages)
    assert stand_in.calls == [] and not app.state.statements.has(ours.id, sid)       # bytes dropped once read


def test_a_new_layout_waits_for_looks_right_even_when_it_adds_up(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn())
    sid = upload(client, "eStmt_2026-03.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    app.state.statements.run_once()                                   # extract
    assert _stage(db, sid).state == "queued"
    app.state.statements.run_once()                                   # the layout from the gateway
    s = _stage(db, sid)
    assert (s.state, s.gap_cents, s.layout_id) == ("layout", 0, None) and stand_in.calls == [None]
    assert json.loads(s.proposal) == pdf("chase_card")[1].layout


def test_extraction_goes_before_a_new_layout(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn())
    first = upload(client, "a.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    app.state.statements.run_once()                                   # a.pdf extracted, now waits for its layout
    second = upload(client, "b.pdf", pdf("boa_checking")[0]).json()["statement"]["id"]
    app.state.statements.run_once()
    assert _stage(db, second).lines is not None and _stage(db, first).state == "queued"


def test_gateway_away_leaves_new_layouts_waiting_while_learned_ones_finish(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn())
    app.state.statements.health = lambda: None
    remember(db, "boa_checking")
    new = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    learned = upload(client, "boa.pdf", pdf("boa_checking")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    assert (_stage(db, new).state, _stage(db, learned).state) == ("waiting", "ready") and stand_in.calls == []
    app.state.statements.health = lambda: {"statement_features": ["layout"]}
    assert app.state.statements.run_once() is True and _stage(db, new).state == "layout"


def test_the_gateway_state_for_the_list(app, client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    assert client.get("/api/b/ours/import/statements").json()["gateway"] == "unpaired"
    answering(app, StandIn())
    assert client.get("/api/b/ours/import/statements").json()["gateway"] == "answering"
    reader.peek = lambda: {"categorizer": True}
    assert client.get("/api/b/ours/import/statements").json()["gateway"] == "old"
    reader.peek = lambda: None
    assert client.get("/api/b/ours/import/statements").json()["gateway"] == "waiting"


def test_a_read_file_waiting_for_a_model_the_gateway_lacks_says_so(app, client, db, ddb, ours):
    """Install gate INS-12: paired, answering, but no layout model pulled: the new layout waits, and its line says it
    needs a model, not the gateway. Away, unpaired or with the model, it doesn't."""
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    answering(app, StandIn(), features=("extract", "render"))          # the gateway answers with no local model
    sid = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    while reader.run_once():
        pass
    assert _stage(db, sid).state == "waiting"
    line = lambda: client.get("/api/b/ours/import/statements").json()["statements"][0]     # noqa: E731
    assert (line()["state"], line()["needs_model"]) == ("waiting", True)
    reader.peek = lambda: None                                          # away: it waits for the gateway itself
    assert line()["needs_model"] is False
    reader.peek = lambda: {"statement_features": ["layout"]}
    assert line()["needs_model"] is False
    reader.client = type("Unpaired", (), {"paired": False})()
    reader.peek = lambda: {"statement_features": []}
    assert line()["needs_model"] is False


def test_a_file_not_yet_read_never_says_it_needs_a_model(app, client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn(), features=())
    upload(client, "card.pdf", pdf("chase_card")[0])
    assert client.get("/api/b/ours/import/statements").json()["statements"][0]["needs_model"] is False      # queued


def test_a_failure_is_retried_once_then_says_so(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn(answer=None))
    sid = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    app.state.statements.run_once()
    app.state.statements.run_once()
    assert (_stage(db, sid).state, _stage(db, sid).tries) == ("queued", 1)
    app.state.statements.run_once()
    s = _stage(db, sid)                                  # P17: a layout the model can't give is read as a scan instead
    assert (s.state, s.error, s.tries) == ("queued", None, 0) and s.proposal.startswith(SCAN_MARK) and len(stand_in.calls) == 2


def test_a_file_behind_a_new_layout_waits_for_its_check(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn())
    from datetime import date
    from steward_gateway.evals.statement_set import build
    a = upload(client, "march.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    b = upload(client, "april.pdf", build("chase_card", end=date(2026, 4, 30))[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    assert (_stage(db, a).state, _stage(db, b).state, len(stand_in.calls)) == ("layout", "queued", 1)


def test_a_drifted_learned_layout_asks_once_and_with_gateway_away_goes_to_row_review(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn(answer=lambda sent, hint: pdf("chase_checking", "drifted")[1].layout))
    remember(db, "chase_checking")
    sid = upload(client, "drifted.pdf", pdf("chase_checking", "drifted")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    s = _stage(db, sid)
    assert (s.state, s.gap_cents) == ("layout", 0) and stand_in.calls[0]["previous"] == pdf("chase_checking")[1].layout
    app.state.statements.health = lambda: None
    away = upload(client, "drifted2.pdf", pdf("chase_checking", "drifted")[0] + b"\n%again").json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    assert _stage(db, away).state == "off" and _stage(db, away).gap_cents != 0


def test_a_drifted_layout_the_model_cannot_fix_keeps_its_stored_reading_for_row_review(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn(answer=None))
    remember(db, "chase_checking")
    sid = upload(client, "drifted.pdf", pdf("chase_checking", "drifted")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    s = _stage(db, sid)
    assert (s.state, s.error, s.layout_id is not None) == ("off", None, True) and s.gap_cents != 0


def test_a_combined_statement_becomes_a_line_per_account(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn())
    upload(client, "cu.pdf", pdf("cu_savings")[0])
    while app.state.statements.run_once():
        pass
    lines = client.get("/api/b/ours/import/statements").json()["statements"]
    assert [(x["name"], x["last4"], x["state"], x["gap_cents"]) for x in lines] == [
        ("cu.pdf · ••0011", "0011", "layout", 0), ("cu.pdf · ••0029", "0029", "layout", 0)]


def _parts(db):
    db.rollback()
    return [(x.part, x.filename, x.state, x.gap_cents)
            for x in db.scalars(select(StatementStage).order_by(StatementStage.part, StatementStage.id))]


def test_a_remembered_combined_statement_that_does_not_add_up_keeps_one_line_per_account(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn())
    remember(db, "cu_savings")
    upload(client, "cu.pdf", pdf("cu_savings", "off")[0])
    while app.state.statements.run_once():
        pass
    assert _parts(db) == [(0, "cu.pdf · ••0011", "off", -1240), (1, "cu.pdf · ••0029", "off", 0)]
    assert len(stand_in.calls) == 1                     # the part-0 job asked once and wrote both parts


def test_a_drifted_combined_statement_with_gateway_away_keeps_one_line_per_account(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    stand_in = answering(app, StandIn())
    app.state.statements.health = lambda: None
    remember(db, "cu_savings")
    upload(client, "cu.pdf", pdf("cu_savings", "off")[0])
    while app.state.statements.run_once():
        pass
    assert _parts(db) == [(0, "cu.pdf · ••0011", "off", -1240), (1, "cu.pdf · ••0029", "off", 0)]
    assert stand_in.calls == []


def test_scans_wait_for_the_vision_model_and_a_card_answered_as_an_investment_is_no_answer(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn(answer=lambda sent, hint: {**pdf("chase_card")[1].layout, "kind": "investment"}))
    scan = upload(client, "scan.pdf", scanned_pdf()).json()["statement"]["id"]
    card = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    assert (_stage(db, scan).state, _stage(db, scan).error) == ("waiting", None)      # no `scan` feature: it waits
    assert (_stage(db, card).state, _stage(db, card).error) == ("waiting", None)      # fails validation twice (P17)


def test_a_bad_file_fails_only_its_own_line(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn())
    remember(db, "boa_checking")
    bad = upload(client, "pw.pdf", pdf("boa_checking", "password")[0]).json()["statement"]["id"]
    good = upload(client, "boa.pdf", pdf("boa_checking")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    assert (_stage(db, bad).state, _stage(db, bad).error, _stage(db, good).state) == ("error", "password", "ready")
    line = next(x for x in client.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == bad)
    assert line["error_text"] == "This PDF has a password. Save a copy without one and try again."


def test_startup_requeues_reading_text_and_marks_unread_files(app, client, db, ddb, ours, settings, books):
    from fastapi.testclient import TestClient

    from steward.app import create_app
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn())
    read = upload(client, "a.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    app.state.statements.run_once()
    unread = upload(client, "b.pdf", pdf("boa_checking")[0]).json()["statement"]["id"]
    _stage(db, read).state = "reading"
    db.commit()
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as again:
        login(again, "jr")
        assert (_stage(db, read).state, _stage(db, unread).state, _stage(db, unread).error) == ("queued", "error", "gone")
        assert upload(again, "b.pdf", pdf("boa_checking")[0]).status_code == 201         # the same bytes replace it
        db.rollback()
        assert [(s.state, s.error) for s in db.scalars(select(StatementStage).where(StatementStage.filename == "b.pdf"))] \
            == [("queued", None)]


def test_the_memory_caps(app, client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    reader.cap = 2 * 1024 * 1024
    r = upload(client, "big.pdf", b"%PDF-" + b"0" * (3 * 1024 * 1024))
    assert (r.status_code, r.json()) == (503, {"error": "Steward is busy with other files. Try again in a few minutes."})
    reader.cap, reader.per_person = 300 * 1024 * 1024, 1
    assert upload(client, "a.pdf", pdf("boa_checking")[0]).status_code == 201
    assert upload(client, "b.pdf", pdf("chase_card")[0]).status_code == 503
    assert reader.held_bytes() >= len(pdf("boa_checking")[0])


def test_reserve_counts_what_is_allocated(books):
    reader = StatementReader(books, StandIn(), lambda: None, lambda: None, cap=1000)
    rid = reader.reserve(1, 900)
    try:
        reader.reserve(2, 200)
        raise AssertionError("no Busy")
    except Busy:
        pass
    reader.release(rid)
    data = bytearray(b"x" * 500)
    reader.hold(1, 1, 1, data, reader.reserve(1, 600))
    import sys
    assert reader.held_bytes() == sys.getsizeof(data)


def test_reserve_counts_the_page_picture_while_it_is_held(books):
    reader = StatementReader(books, StandIn(), lambda: None, lambda: None, cap=1000)
    reader._png = 800
    assert reader.held_bytes() == 800
    try:
        reader.reserve(1, 300)
        raise AssertionError("no Busy")
    except Busy:
        pass
    reader._png = 0
    reader.release(reader.reserve(1, 300))


def test_upload_and_read_write_nothing_to_disk(app, client, db, ddb, ours, settings, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch-tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    _jr(ddb, ours)
    login(client, "jr")
    answering(app, StandIn())
    remember(db, "citi_card")
    client.get("/api/b/ours/import/statements")

    def listing():
        return {str(p) for root in (Path(settings.data_dir), scratch) for p in root.rglob("*")
                if not p.name.endswith(("-wal", "-shm", "-journal"))}
    before = listing()
    upload(client, "citi.pdf", pdf("citi_card")[0])
    while app.state.statements.run_once():
        pass
    assert listing() == before
