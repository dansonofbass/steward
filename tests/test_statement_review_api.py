"""The layout check, row review and the rest (spec P23, P33-P35, API): Looks right remembers the layout at once, so the
next statement reads with no layout request; Not right opens row review and remembers nothing; row ops recompute the
gap and never touch undo_entry; Import anyway only while off; Forget with Undo."""
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from steward.db.models import StatementLayout, StatementStage, UndoEntry
from steward_gateway.evals.statement_set import build
from tests.factories import login, make_account, make_person
from tests.statement_files import pdf
from tests.statement_helpers import StandIn, answering, upload

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")


@pytest.fixture
def jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    return client


def _read(app, client, name, data, slug="ours"):
    sid = upload(client, name, data, slug=slug).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    return sid


def _post(client, sid, path, body=None):
    return client.post(f"/api/b/ours/import/statements/{sid}/{path}", json=body or {})


def test_looks_right_remembers_the_layout_and_the_next_month_reads_alone(app, jr, db):
    stand_in = answering(app, StandIn())
    sid = _read(app, jr, "march.pdf", pdf("chase_card")[0])
    r = _post(jr, sid, "layout", {"answer": "right"})
    assert r.status_code == 200 and r.json()["statement"]["state"] == "ready"
    row = db.scalar(select(StatementLayout))
    assert (row.label, row.kind, row.uses) == ("Summit Card Services", "card", 0)
    a = json.loads(row.anchors)
    assert not any(ch.isdigit() for t in [h["text"] for h in a["header"]] + a["sections"] for ch in t)
    april = _read(app, jr, "april.pdf", build("chase_card", end=date(2026, 4, 30))[0])
    assert jr.get(f"/api/b/ours/import/statements/{april}").json()["state"] == "ready" and len(stand_in.calls) == 1


def test_a_remembered_layout_belongs_to_its_book(app, client, margaret):
    login(client, "jr")
    jr = client
    stand_in = answering(app, StandIn())
    sid = _read(app, jr, "march.pdf", pdf("chase_card")[0])
    _post(jr, sid, "layout", {"answer": "right"})
    other = _read(app, jr, "march.pdf", pdf("chase_card")[0], slug=margaret.slug)
    assert len(stand_in.calls) == 2
    r = jr.get(f"/api/b/{margaret.slug}/import/statements/{other}")
    assert r.json()["state"] == "layout"


def test_not_right_opens_row_review_and_remembers_nothing(app, jr, db):
    answering(app, StandIn())
    sid = _read(app, jr, "march.pdf", pdf("chase_card")[0])
    assert _post(jr, sid, "layout", {"answer": "wrong"}).json()["statement"]["state"] == "off"
    assert db.scalar(select(func.count()).select_from(StatementLayout)) == 0


def test_the_layout_answer_is_strict(app, jr):
    answering(app, StandIn())
    sid = _read(app, jr, "march.pdf", pdf("chase_card")[0])
    for body in ({"answer": "maybe"}, {"answer": "right", "x": 1}, {}):
        assert _post(jr, sid, "layout", body).status_code == 422
    _post(jr, sid, "layout", {"answer": "right"})
    assert _post(jr, sid, "layout", {"answer": "right"}).status_code == 409


def test_row_review_counts_the_gap_down_and_done_makes_it_ready(app, jr, db):
    answering(app, StandIn(answer=lambda sent, hint: pdf("chase_checking")[1].layout))
    sid = _read(app, jr, "off.pdf", pdf("chase_checking", "off")[0])
    detail = jr.get(f"/api/b/ours/import/statements/{sid}").json()
    assert (detail["state"], detail["gap_cents"]) == ("off", 1240)
    off_row = next(r for r in detail["rows"] if r["section"] == "ELECTRONIC WITHDRAWALS")
    before = db.scalar(select(func.count()).select_from(UndoEntry))
    r = _post(jr, sid, "rows", {"ops": [{"op": "edit", "i": off_row["i"], "amount_cents": off_row["amount_cents"] + 1240}]})
    assert (r.status_code, r.json()["gap_cents"], r.json()["state"]) == (200, 0, "off")
    assert _post(jr, sid, "rows", {"ops": [], "done": True}).json()["state"] == "ready"
    assert db.scalar(select(func.count()).select_from(UndoEntry)) == before


def test_bad_row_ops_are_422(app, jr):
    answering(app, StandIn(answer=lambda sent, hint: pdf("chase_checking")[1].layout))
    sid = _read(app, jr, "off.pdf", pdf("chase_checking", "off")[0])
    for body in ({"ops": [{"op": "remove", "i": 0}] * 2}, {"ops": [{"op": "remove", "i": 999}]},
                 {"ops": [{"op": "remove", "i": 0}] * 101}, {"ops": "x"}, {"ops": [], "extra": 1}):
        assert _post(jr, sid, "rows", body).status_code == 422, body


def test_a_row_removed_twice_is_refused_so_restore_still_puts_it_back(app, jr):
    answering(app, StandIn(answer=lambda sent, hint: pdf("chase_checking")[1].layout))
    sid = _read(app, jr, "off.pdf", pdf("chase_checking", "off")[0])
    assert _post(jr, sid, "rows", {"ops": [{"op": "remove", "i": 0}]}).json()["rows"][0]["state"] == "removed"
    assert _post(jr, sid, "rows", {"ops": [{"op": "remove", "i": 0}]}).status_code == 422
    r = _post(jr, sid, "rows", {"ops": [{"op": "restore", "i": 0}]})
    assert (r.status_code, r.json()["rows"][0]["state"]) == (200, "read")


def test_import_anyway_only_while_off(app, jr, db):
    answering(app, StandIn())
    sid = _read(app, jr, "off.pdf", pdf("chase_checking", "off")[0])
    r = jr.patch(f"/api/b/ours/import/statements/{sid}", json={"anyway": True})
    assert (r.status_code, r.json()["statement"]["anyway"]) == (200, True)
    ok = _read(app, jr, "boa.pdf", pdf("boa_checking")[0])
    assert jr.get(f"/api/b/ours/import/statements/{ok}").json()["state"] == "layout"
    _post(jr, ok, "layout", {"answer": "right"})
    assert jr.get(f"/api/b/ours/import/statements/{ok}").json()["state"] == "ready"
    assert jr.patch(f"/api/b/ours/import/statements/{ok}", json={"anyway": True}).status_code == 409


def test_the_account_can_be_changed(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = _read(app, jr, "march.pdf", pdf("chase_card")[0])
    r = jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": card.id})
    assert (r.json()["statement"]["account_id"], r.json()["statement"]["suggested_by"]) == (card.id, None)
    assert jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": 999}).status_code == 404
    assert jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": "1"}).status_code == 422


def test_try_again_requeues_a_failed_layout(app, jr, db):
    stand_in = answering(app, StandIn(answer=None))
    sid = _read(app, jr, "card.pdf", pdf("chase_card")[0])
    db.rollback()
    s = db.get(StatementStage, sid)                  # the reader now falls back to a scan (P17); an old failed line remains
    s.state, s.error, s.proposal = "error", "layout_failed", None
    db.commit()
    assert jr.get(f"/api/b/ours/import/statements/{sid}").json()["state"] == "error"
    stand_in.answer = lambda sent, hint: pdf("chase_card")[1].layout
    assert _post(jr, sid, "retry").status_code == 200
    while app.state.statements.run_once():
        pass
    assert jr.get(f"/api/b/ours/import/statements/{sid}").json()["state"] == "layout"


def test_remove_restore_and_final(app, jr, db):
    answering(app, StandIn())
    sid = _read(app, jr, "card.pdf", pdf("chase_card")[0])
    assert jr.delete(f"/api/b/ours/import/statements/{sid}").status_code == 204
    assert jr.get("/api/b/ours/import/statements").json()["statements"][0]["removed"] is True
    assert _post(jr, sid, "restore").json()["statement"]["removed"] is False
    assert jr.delete(f"/api/b/ours/import/statements/{sid}?final=1").status_code == 204
    assert jr.get(f"/api/b/ours/import/statements/{sid}").status_code == 404


def test_forget_and_undo_and_the_layout_list(app, jr, db):
    answering(app, StandIn())
    sid = _read(app, jr, "march.pdf", pdf("chase_card")[0])
    _post(jr, sid, "layout", {"answer": "right"})
    listed = jr.get("/api/b/ours/import/layouts").json()["layouts"]
    [mine] = [x for x in listed if x["kind"] == "statement"]
    assert (mine["label"], mine["statement_kind"]) == ("Summit Card Services", "card")
    undo = jr.delete(f"/api/b/ours/import/statement-layouts/{mine['id']}").json()["undo"]
    assert not [x for x in jr.get("/api/b/ours/import/layouts").json()["layouts"] if x["kind"] == "statement"]
    assert jr.post(f"/api/b/ours/undo/{undo}").status_code == 200
    assert [x["id"] for x in jr.get("/api/b/ours/import/layouts").json()["layouts"] if x["kind"] == "statement"] == [mine["id"]]
    entry = db.scalar(select(UndoEntry).order_by(UndoEntry.created_at.desc()))
    assert json.loads(entry.before)["statement_layouts"][str(mine["id"])].keys() == {"account_id", "forgotten_at"}
