"""Investment and loan statements through the reader and the routes (spec "Investment statements", P23, P39): a new
layout's holdings wait for Looks right; a learned one that adds up is ready; a loan's balance; holdings review with
the gap to the total; a scan of an investment account asks for positions."""
import json

import pytest
from sqlalchemy import func, select

from steward.db.models import (BalanceSnapshot, Holding, ImportBatch, PositionsImport, StatementLayout, StatementStage,
                               UndoEntry)
from tests.factories import login, make_account, make_person
from tests.statement_files import pdf
from tests.statement_helpers import StandIn, answering, commit, remember, truth_answers, upload

pytestmark = pytest.mark.usefixtures("undo_entries_hold_no_text")


@pytest.fixture
def jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    return client


def _read(app, client, name, data):
    sid = upload(client, name, data).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    return sid


def _line(client, sid):
    return next(x for x in client.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == sid)


def test_a_new_brokerage_waits_for_looks_right_then_the_next_reads_alone(app, jr, db):
    from datetime import date
    from steward_gateway.evals.statement_set import build
    stand_in = answering(app, StandIn(answer=lambda sent, hint: pdf("fidelity_brokerage")[1].layout))
    sid = _read(app, jr, "q1.pdf", pdf("fidelity_brokerage")[0])
    line = _line(jr, sid)
    assert (line["state"], line["holdings"], line["gap_cents"]) == ("holdings", 3, 0)
    detail = jr.get(f"/api/b/ours/import/statements/{sid}").json()
    assert detail["statement"]["total_cents"] == pdf("fidelity_brokerage")[1].total_cents and len(detail["holdings"]) == 3
    assert jr.post(f"/api/b/ours/import/statements/{sid}/layout", json={"answer": "right"}).status_code == 200
    nxt = _read(app, jr, "q2.pdf", build("fidelity_brokerage", end=date(2026, 4, 30))[0])
    assert _line(jr, nxt)["state"] == "ready" and len(stand_in.calls) == 1
    assert db.scalar(select(StatementLayout.kind)) == "investment"


def test_holdings_review_counts_the_gap_to_the_total_down(app, jr, db):
    answering(app, StandIn(answer=lambda sent, hint: pdf("fidelity_brokerage")[1].layout))
    sid = _read(app, jr, "off.pdf", pdf("fidelity_brokerage", "off")[0])
    assert (_line(jr, sid)["state"], _line(jr, sid)["gap_cents"]) == ("off", 287)
    before = db.scalar(select(func.count()).select_from(UndoEntry))
    r = jr.post(f"/api/b/ours/import/statements/{sid}/holdings",
                json={"ops": [{"op": "add", "name": "Pending dividend", "value_cents": 287}], "done": True})
    assert (r.status_code, r.json()["gap_cents"], r.json()["state"]) == (200, 0, "ready")
    assert db.scalar(select(func.count()).select_from(UndoEntry)) == before
    for body in ({"ops": [{"op": "remove", "i": 0}] * 2}, {"ops": [{"op": "edit", "i": 9, "value_cents": 1}]},
                 {"ops": [{"op": "add", "name": "", "value_cents": 1}]}, {"ops": [{"op": "edit", "i": 0, "value_cents": 10**14}]}):
        assert jr.post(f"/api/b/ours/import/statements/{sid}/holdings", json=body).status_code in (409, 422)


def test_a_holding_removed_twice_is_refused_so_restore_still_puts_it_back(app, jr):
    answering(app, StandIn(answer=lambda sent, hint: pdf("fidelity_brokerage")[1].layout))
    sid = _read(app, jr, "off.pdf", pdf("fidelity_brokerage", "off")[0])
    url = f"/api/b/ours/import/statements/{sid}/holdings"
    assert jr.post(url, json={"ops": [{"op": "remove", "i": 0}]}).json()["holdings"][0]["state"] == "removed"
    assert jr.post(url, json={"ops": [{"op": "remove", "i": 0}]}).status_code == 422
    r = jr.post(url, json={"ops": [{"op": "restore", "i": 0}]})
    assert (r.status_code, r.json()["holdings"][0]["state"]) == (200, "read")


def test_a_loan_waits_in_layout_and_reads_its_principal(app, jr):
    answering(app, StandIn())
    sid = _read(app, jr, "mortgage.pdf", pdf("mortgage")[0])
    line = _line(jr, sid)
    assert (line["state"], line["balance_cents"]) == ("layout", pdf("mortgage")[1].closing_cents)
    assert jr.post(f"/api/b/ours/import/statements/{sid}/layout", json={"answer": "right"}).json()["statement"]["state"] == "ready"
    other = _read(app, jr, "auto.pdf", pdf("auto_loan")[0])
    assert jr.post(f"/api/b/ours/import/statements/{other}/layout", json={"answer": "wrong"}).json()["statement"]["error"] == \
        "not_statement"


def test_a_learned_loan_with_no_period_and_gateway_away_says_no_period(app, jr, db):
    from datetime import date
    from steward_gateway.evals.statement_set import build
    answering(app, StandIn(), features=())                                  # away: no layout request can go
    remember(db, "mortgage")
    sid = _read(app, jr, "old.pdf", build("mortgage", end=date(2022, 3, 31))[0])     # older than three years
    line = _line(jr, sid)
    assert (line["state"], line["error"]) == ("error", "no_period")


def test_a_scan_of_an_investment_account_asks_for_positions(app, jr, db):
    truth = pdf("vanguard_ira")[1]
    stand_in = answering(app, StandIn(pages=truth_answers(truth)), features=("layout", "holdings", "scan"))
    ira = make_account(db, "IRA 8765", type="traditional_ira")
    sid = upload(jr, "ira-scan.pdf", pdf("vanguard_ira", "scan")[0]).json()["statement"]["id"]
    jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": ira.id})
    while app.state.statements.run_once():
        pass
    assert {c[2] for c in stand_in.page_calls} == {"holdings"}
    db.rollback()
    s = db.get(StatementStage, sid)
    assert (s.state, s.gap_cents, len(json.loads(s.holdings))) == ("ready", 0, len(truth.holdings))


@pytest.mark.parametrize(("features", "update"), [(("layout", "scan"), True), (("layout", "holdings", "scan"), False)])
def test_a_scan_read_for_rows_because_gateway_lacks_holdings_says_it_needs_an_update(app, jr, db, features, update):
    truth = pdf("vanguard_ira")[1]
    pages = truth_answers(truth) if not update else [{**a, "holdings": []} for a in truth_answers(truth)]
    stand_in = answering(app, StandIn(pages=pages), features=features)
    ira = make_account(db, "IRA 8765", type="traditional_ira")
    sid = upload(jr, "ira-scan.pdf", pdf("vanguard_ira", "scan")[0]).json()["statement"]["id"]
    jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": ira.id})
    while app.state.statements.run_once():
        pass
    assert {c[2] for c in stand_in.page_calls} == {"rows" if update else "holdings"}
    detail = jr.get(f"/api/b/ours/import/statements/{sid}").json()
    assert detail["holdings_update"] is update
    if update:
        assert (detail["state"], detail["gap_cents"], detail["holdings"]) == ("off", None, [])


def test_a_bank_scan_never_says_gateway_needs_an_update_for_holdings(app, jr, db):
    answering(app, StandIn(pages=truth_answers(pdf("chase_checking")[1])), features=("layout", "scan"))
    acct = make_account(db, "Checking", type="checking")
    sid = upload(jr, "c.pdf", pdf("chase_checking", "scan")[0]).json()["statement"]["id"]
    jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": acct.id})
    while app.state.statements.run_once():
        pass
    assert jr.get(f"/api/b/ours/import/statements/{sid}").json()["holdings_update"] is False


def test_rows_on_an_investment_statement_are_refused(app, jr):
    answering(app, StandIn(answer=lambda sent, hint: pdf("fidelity_brokerage")[1].layout))
    sid = _read(app, jr, "q1.pdf", pdf("fidelity_brokerage")[0])
    assert jr.post(f"/api/b/ours/import/statements/{sid}/rows", json={"ops": []}).status_code == 409


def test_holdings_review_is_for_managers_of_this_book_only(app, jr, client, ddb, ours):
    answering(app, StandIn(answer=lambda sent, hint: pdf("fidelity_brokerage")[1].layout))
    sid = _read(app, jr, "off.pdf", pdf("fidelity_brokerage", "off")[0])
    assert jr.post("/api/b/ours/import/statements/99999/holdings", json={"ops": []}).status_code == 404
    make_person(ddb, "viewer", [(ours.id, "viewer")])
    login(client, "viewer")
    assert client.post(f"/api/b/ours/import/statements/{sid}/holdings", json={"ops": []}).status_code == 404


def _ready(app, client, db, name, which):
    remember(db, which)
    sid = upload(client, name, pdf(which)[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    return sid


def _body(sid, account_id):
    return {"batch": None, "files": [], "statements": [{"id": sid, "account_id": account_id, "include": []}],
            "simplefin_include": []}


def test_an_investment_statement_saves_its_holdings_and_balance(app, jr, db):
    answering(app, StandIn())
    ira = make_account(db, "Brokerage", type="brokerage_taxable")
    truth = pdf("fidelity_brokerage")[1]
    sid = _ready(app, jr, db, "q1.pdf", "fidelity_brokerage")
    body = _body(sid, ira.id)
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    assert p["holdings"] == {"n": 1, "kept": 0, "rows": [{"account": "Brokerage", "as_of": truth.period[1].isoformat(),
                                                          "count": 3, "kept": False}]}
    assert p["writes"] == 3
    r = jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    assert r.status_code == 201 and r.json()["kept_holdings"] == []
    assert (r.json()["imported"], r.json()["accounts"], r.json()["account"]) == (3, 1, "Brokerage")
    db.rollback()
    pi = db.scalar(select(PositionsImport))
    assert (pi.source, pi.as_of, pi.check_state, pi.balance_cents, pi.row_count) == \
        ("pdf", truth.period[1], "adds_up", truth.closing_cents, 3)
    assert pi.set_id == r.json()["set_id"]
    held = db.scalars(select(Holding).where(Holding.account_id == ira.id)).all()
    assert sorted(h.market_value_cents for h in held) == sorted(h["value_cents"] for h in truth.holdings)
    assert db.get(BalanceSnapshot, (ira.id, truth.period[1])).balance_cents == truth.closing_cents


def test_a_day_with_holdings_is_kept_and_said(app, jr, db):
    from steward.services.holdings import Position, replace_holdings
    answering(app, StandIn())
    ira = make_account(db, "Brokerage", type="brokerage_taxable")
    truth = pdf("fidelity_brokerage")[1]
    replace_holdings(db, ira.id, truth.period[1], [Position("VTI", "Feed fund", 1000, 123_456)])
    db.commit()
    sid = _ready(app, jr, db, "q1.pdf", "fidelity_brokerage")
    body = _body(sid, ira.id)
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    assert p["holdings"]["kept"] == 1 and p["writes"] == 1                 # only the balance is new
    r = jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    assert r.json()["kept_holdings"] == [truth.period[1].isoformat()]
    db.rollback()
    assert [(h.symbol, h.market_value_cents) for h in db.scalars(select(Holding))] == [("VTI", 123_456)]
    assert db.scalar(select(PositionsImport)) is None


def test_undo_removes_holdings_and_an_unchanged_snapshot(app, jr, db):
    answering(app, StandIn())
    ira = make_account(db, "Brokerage", type="brokerage_taxable")
    other = make_account(db, "IRA", type="traditional_ira")
    truth = pdf("fidelity_brokerage")[1]
    sid = _ready(app, jr, db, "q1.pdf", "fidelity_brokerage")
    sid2 = _ready(app, jr, db, "ira.pdf", "vanguard_ira")
    ira_truth = pdf("vanguard_ira")[1]
    set_id = commit(jr, [{"id": sid, "account_id": ira.id, "include": []},
                         {"id": sid2, "account_id": other.id, "include": []}]).json()["set_id"]
    db.rollback()
    db.get(BalanceSnapshot, (ira.id, truth.period[1])).balance_cents += 1          # someone changed it since
    db.commit()
    r = jr.post(f"/api/b/ours/import/sets/{set_id}/rollback")
    day = truth.period[1]
    assert r.json()["kept"] == [f"The {day:%b} {day.day} balance was changed since, so it stays."]
    db.rollback()
    assert db.scalars(select(Holding)).all() == []
    assert all(x is not None for x in db.scalars(select(PositionsImport.rolled_back_at)))
    assert db.get(BalanceSnapshot, (ira.id, truth.period[1])) is not None           # the changed one stays
    assert db.get(BalanceSnapshot, (other.id, ira_truth.period[1])) is None         # the unchanged one goes


def _same_day_pair(app, jr, db):
    """Two statements for one account and one day, in one batch: the first writes the holdings, the second is kept."""
    answering(app, StandIn())
    acct = make_account(db, "Brokerage", type="brokerage_taxable")
    assert pdf("fidelity_brokerage")[1].period[1] == pdf("vanguard_ira")[1].period[1]
    first = _ready(app, jr, db, "q1.pdf", "fidelity_brokerage")
    second = _ready(app, jr, db, "ira.pdf", "vanguard_ira")
    return acct, [{"id": first, "account_id": acct.id, "include": []}, {"id": second, "account_id": acct.id, "include": []}]


def test_undo_of_the_kept_statement_leaves_the_writers_holdings(app, jr, db):
    acct, statements = _same_day_pair(app, jr, db)
    r = commit(jr, statements)
    assert r.status_code == 201
    writer, kept = r.json()["batch_ids"]
    db.rollback()
    pi = db.scalar(select(PositionsImport))
    assert pi.batch_id == writer and db.scalar(select(func.count()).select_from(PositionsImport)) == 1
    assert jr.post(f"/api/b/ours/import/batches/{kept}/rollback").status_code == 200
    db.rollback()
    assert len(db.scalars(select(Holding).where(Holding.account_id == acct.id)).all()) == 3
    assert db.scalar(select(PositionsImport.rolled_back_at)) is None
    assert jr.post(f"/api/b/ours/import/batches/{writer}/rollback").status_code == 200
    db.rollback()
    assert db.scalars(select(Holding)).all() == []
    assert db.scalar(select(PositionsImport.rolled_back_at)) is not None


def test_a_same_day_pair_previews_one_written_and_one_kept(app, jr, db):
    acct, statements = _same_day_pair(app, jr, db)
    body = {"batch": None, "files": [], "statements": statements, "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    assert [r["kept"] for r in p["holdings"]["rows"]] == [False, True] and p["holdings"]["kept"] == 1
    assert [r["kept"] for r in p["balances"]["rows"]] == [False, True] and p["balances"]["kept"] == 1
    assert p["writes"] == 3
    r = jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    assert r.json()["imported"] == p["writes"]


def test_a_loan_saves_its_principal_negative(app, jr, db):
    answering(app, StandIn())
    loan = make_account(db, "Mortgage", type="mortgage")
    truth = pdf("mortgage")[1]
    sid = _ready(app, jr, db, "mortgage.pdf", "mortgage")
    r = commit(jr, [{"id": sid, "account_id": loan.id, "include": []}])
    assert r.status_code == 201 and r.json()["imported"] == 1 and r.json()["account"] == "Mortgage"   # F22: the balance
    db.rollback()
    assert db.get(BalanceSnapshot, (loan.id, truth.period[1])).balance_cents == -truth.closing_cents
    assert db.scalar(select(ImportBatch.snapshot_cents)) == -truth.closing_cents and db.scalar(select(PositionsImport)) is None


def test_a_parent_books_inventory_shows_the_statements_holdings(app, client, ddb, margaret, mdb, books):
    from steward.db.models import InventoryItem
    login(client, "jr")
    answering(app, StandIn())
    ira = make_account(mdb, "Margaret's IRA", type="traditional_ira")
    item = InventoryItem(kind="account", name="Margaret's IRA", owner="Margaret", account_id=ira.id, data_source="statement",
                         status="confirmed", details="{}")
    mdb.add(item)
    mdb.commit()
    remember(mdb, "vanguard_ira")
    sid = upload(client, "ira.pdf", pdf("vanguard_ira")[0], slug=margaret.slug).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    assert commit(client, [{"id": sid, "account_id": ira.id, "include": []}], slug=margaret.slug).status_code == 201
    got = client.get(f"/api/b/{margaret.slug}/inventory/items/{item.id}").json()["holdings"]
    assert got["as_of"] == pdf("vanguard_ira")[1].period[1].isoformat() and len(got["rows"]) == 3


def test_the_investment_page_names_the_statement(app, jr, db):
    answering(app, StandIn())
    acct = make_account(db, "Brokerage", type="brokerage_taxable")
    sid = _ready(app, jr, db, "q1.pdf", "fidelity_brokerage")
    commit(jr, [{"id": sid, "account_id": acct.id, "include": []}])
    held = jr.get(f"/api/b/ours/accounts/{acct.id}/investment").json()["holdings"]
    assert (held["source"], held["statement_month"]) == ("statement", "Mar 2026")
