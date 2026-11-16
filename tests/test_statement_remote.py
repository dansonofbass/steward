"""Reading PDFs on the gateway (remote-reading P54-P66): where PDFs are opened, files held while the gateway is away and
read when it returns, no try spent on an absent gateway, Try again after two bad answers, the restart line, the caps,
and nothing of a statement in Ask."""
import json
import logging
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import gateway_name
from steward.db.models import StatementStage, Transaction
from steward.services.statements import where
from steward.services.statements.client import AWAY
from steward.services.statements.copy import BUSY, HELD
from steward_pdf import sandbox as S
from tests.factories import login, make_account, make_person
from tests.gateway.test_statements_page import ANSWER
from tests.statement_files import pdf
from tests.statement_helpers import REMOTE, RemoteStandIn, answering, commit, remember, scanned_pdf, upload

LIST = "/api/b/ours/import/statements"


def _jr(ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])


def _stage(db, sid):
    db.rollback()
    return db.get(StatementStage, sid)


def _remote(app, stand, features=REMOTE):
    answering(app, stand, features)
    app.state.statements.place = "gateway"
    return stand


# ---- where PDFs are opened (P54, P55)

def test_auto_opens_pdfs_here_only_with_the_filter_and_the_wall():
    assert where.resolve("auto", probe=True, check=S.confinement) == "local"      # this machine has both
    walled = {"confined": True, "seccomp": 2, "walled": True, "probe": "refused", "canary": "ok"}
    assert where.resolve("auto", probe=True, check=lambda: walled) == "local"
    assert where.resolve("auto", probe=True, check=lambda: {"confined": True, "seccomp": 2}) == "gateway"  # SEC-2


def test_auto_sends_them_to_gateway_when_the_filter_wont_install(monkeypatch):
    from tests.test_pdf_wall import _main
    report = _main(monkeypatch, ["--confined"], confined=False, mode=-1)    # confine.install raises Unconfined
    assert where.resolve("auto", probe=True, check=lambda: report) == "gateway"
    assert where.resolve("auto", probe=True, check=dict) == "gateway"


def test_a_forced_setting_wins_and_the_test_env_never_spawns_a_child(caplog):
    def boom():
        raise AssertionError("a child ran")
    assert where.resolve("auto", probe=False, check=boom) == "local"
    assert where.resolve("gateway", probe=True, check=boom) == "gateway"
    caplog.set_level(logging.WARNING)
    assert where.resolve("local", probe=True, check=dict) == "local"
    assert "can't confine" in caplog.text


def test_the_setting_is_read_at_startup(settings, books, monkeypatch):
    from steward.app import create_app
    from steward.settings import Settings
    monkeypatch.setenv("STEWARD_STATEMENT_READING", "gateway")
    app = create_app(Settings(_env_file=None), books)
    with TestClient(app, base_url="https://nas.tail1234.ts.net"):
        assert app.state.statements.place == "gateway"


def test_settings_chat_and_the_list_say_where_pdfs_are_read(app, client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    assert client.get("/api/b/ours/chat").json()["gateway"]["pdf_place"] == "local"
    assert client.get(LIST).json()["reading"] == "local"
    app.state.statements.place = "gateway"
    assert client.get("/api/b/ours/chat").json()["gateway"]["pdf_place"] == "gateway"
    assert client.get(LIST).json()["reading"] == "gateway"


# ---- waiting and reading on return (P63, P64, P66)

def test_away_files_wait_then_read_when_gateway_returns(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    stand = _remote(app, RemoteStandIn())
    reader.health = lambda: None                                  # the gateway away
    data = pdf("chase_card")[0]
    sid = upload(client, "card.pdf", data).json()["statement"]["id"]
    assert reader.run_once() is False
    s = _stage(db, sid)
    assert (s.state, s.lines, s.tries) == ("waiting", None, 0) and reader.has(ours.id, sid) and stand.extract_calls == []
    assert client.get(LIST).json()["statements"][0]["state"] == "waiting"
    _remote(app, stand)                                           # back, with extract
    assert reader.run_once() is True                              # extracted on the gateway
    assert _stage(db, sid).lines is not None and stand.extract_calls == [len(data)]
    assert reader.run_once() is True                              # the new layout, as ever
    assert _stage(db, sid).state == "layout" and stand.calls == [None]


def test_a_file_already_waiting_opens_no_write_on_the_next_pass(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    _remote(app, RemoteStandIn())
    reader.health = lambda: None                                  # the gateway away
    sid = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    assert reader.run_once() is False and _stage(db, sid).state == "waiting"
    writes, write = [], reader._write

    def counted(book):
        writes.append(book.id)
        return write(book)
    reader._write = counted
    assert reader.run_once() is False and reader.run_once() is False
    assert writes == [] and _stage(db, sid).state == "waiting"


def test_in_gateway_mode_even_a_learned_layout_waits_for_gateway(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    remember(db, "boa_checking")
    stand = _remote(app, RemoteStandIn(), features=("layout",))  # answers, but can't open PDFs
    sid = upload(client, "boa.pdf", pdf("boa_checking")[0]).json()["statement"]["id"]
    assert reader.run_once() is False and _stage(db, sid).state == "waiting"
    assert client.get(LIST).json()["gateway"] == "old"
    _remote(app, stand)
    assert reader.run_once() is True
    assert _stage(db, sid).state == "ready" and stand.calls == [] and len(stand.extract_calls) == 1


def test_unreachable_mid_request_waits_without_spending_a_try(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    stand = _remote(app, RemoteStandIn(extract=AWAY))
    sid = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    assert reader.run_once() is False
    s = _stage(db, sid)
    assert (s.state, s.tries, s.error) == ("waiting", 0, None) and reader.has(ours.id, sid)
    assert reader.run_once() is False and len(stand.extract_calls) == 1          # nothing more until a wake
    stand.extract_answer = None
    reader.wake()                                                 # the next health tick
    assert reader.run_once() is True and _stage(db, sid).lines is not None


def test_another_bad_answer_twice_says_try_again_and_try_again_reads(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    stand = _remote(app, RemoteStandIn(extract=lambda _d: None))
    sid = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    assert reader.run_once() is True and (_stage(db, sid).state, _stage(db, sid).tries) == ("queued", 1)
    assert reader.run_once() is True
    line = client.get(LIST).json()["statements"][0]
    assert (line["state"], line["error"], line["error_text"]) == (
        "error", "read_failed", "The gateway couldn't read this file · Try again")
    assert reader.has(ours.id, sid)
    stand.extract_answer = None
    assert client.post(f"{LIST}/{sid}/retry", json={}).status_code == 200
    assert reader.run_once() is True and _stage(db, sid).lines is not None


def test_a_scan_renders_on_gateway_then_its_page_is_read(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    stand = _remote(app, RemoteStandIn(pages=[ANSWER]))
    sid = upload(client, "scan.pdf", scanned_pdf()).json()["statement"]["id"]
    assert reader.run_once() is True                              # extracted: every page a scan
    assert reader.run_once() is True                              # rendered on the gateway, then the vision model
    assert stand.render_calls == [1] and stand.page_calls[0][:2] == (1, 1)
    assert _stage(db, sid).pages_done == 1


def test_a_page_gateway_wont_render_twice_is_page_failed(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    _remote(app, RemoteStandIn(pages=[ANSWER], render=lambda _d, _n: None))
    sid = upload(client, "scan.pdf", scanned_pdf()).json()["statement"]["id"]
    for _ in range(3):
        assert reader.run_once() is True
    s = _stage(db, sid)
    assert (s.state, s.error) == ("error", "page_failed") and reader.has(ours.id, sid)


def test_a_restart_says_add_the_file_again(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    _remote(app, RemoteStandIn(), features=())
    sid = upload(client, "card.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    assert reader.run_once() is False and _stage(db, sid).state == "waiting"
    reader._held.clear()                                          # the restart took the bytes
    reader.recover()
    line = client.get(LIST).json()["statements"][0]
    assert (line["state"], line["error_text"]) == ("error", "Steward restarted before reading this. Add the file again.")


def test_a_part_read_scan_after_a_restart_says_add_it_again(app, client, db, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    _remote(app, RemoteStandIn(pages=[ANSWER]))
    sid = upload(client, "scan.pdf", scanned_pdf()).json()["statement"]["id"]
    assert reader.run_once() is True                              # extracted; the scan is queued
    reader._held.clear()                                          # the restart took the bytes
    reader.recover()
    s = _stage(db, sid)
    assert (s.state, s.error) == ("error", "restarted")
    line = client.get(LIST).json()["statements"][0]
    assert line["error_text"] == "Steward restarted on page 1 of 1. Add the file again to finish."


# ---- caps (P65)

def test_past_the_cap_while_away_says_steward_is_holding_files(app, client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    _remote(app, RemoteStandIn(), features=())
    reader.cap = 1000
    r = upload(client, "a.pdf", pdf("chase_card")[0])
    assert (r.status_code, r.json()) == (503, {"error": gateway_name.fill(HELD)})
    reader.place = "local"
    r = upload(client, "a.pdf", pdf("chase_card")[0])
    assert (r.status_code, r.json()) == (503, {"error": BUSY})


def test_the_copy_on_its_way_to_gateway_counts(app, client, ddb, ours):
    _jr(ddb, ours)
    login(client, "jr")
    reader = app.state.statements
    seen = []

    def extract(data):
        seen.append(reader.held_bytes())
        return AWAY
    _remote(app, RemoteStandIn(extract=extract))
    data = pdf("chase_card")[0]
    upload(client, "card.pdf", data)
    held = reader.held_bytes()
    reader.run_once()
    assert seen[0] >= held + len(data) and reader.held_bytes() == held


# ---- privacy (P52, P61)

def test_a_row_read_on_gateway_never_reaches_ask(app, client, books, ours, ddb, db):
    from steward.advisor.about import AboutIn, resolve
    from steward.advisor.aliases import Aliases
    from steward_boundary.about import about_text
    _jr(ddb, ours)
    login(client, "jr")
    _remote(app, RemoteStandIn())
    card = make_account(db, "Card", type="credit")
    remember(db, "chase_card")
    sid = upload(client, "zorblax-quillfeather.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    bid = commit(client, [{"id": sid, "account_id": card.id, "include": []}]).json()["batch_ids"][0]
    db.rollback()
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == bid))
    with Session(books.engine_for(ours)) as s:
        out = resolve(s, ours, Aliases(s, ours, books.people(ours.id), save=False), AboutIn("transaction", tid),
                      date(2026, 10, 30))
        s.rollback()
    said = json.dumps(out) + about_text(out)
    for word in ("zorblax", "quillfeather", "statement", "page", "period", "pdf"):
        assert word not in said.lower(), word
