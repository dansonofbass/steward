"""Statements in the import round's preview and commit (spec P35, P37, P38, P40, P42, Batch preview and commit, Undo):
counted per account with CSVs, the widened Looks the same, the same statement twice, only ready statements, the
closing balance kept or written, one Undo, and Came from."""
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from steward.db.models import BalanceSnapshot, ImportBatch, ImportSet, StatementLayout, StatementStage, Transaction
from tests.factories import login, make_account, make_person, make_txn
from tests.import_helpers import file_choice, stage as stage_csv
from tests.statement_files import pdf
from tests.statement_helpers import StandIn, answering, chase_card_csv, commit, remember, upload


@pytest.fixture
def jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    return client


def _ready(app, client, db, sid_name="Statement_0326.pdf", which="chase_card", variant=None):
    """A statement read with its layout remembered: ready at once."""
    remember(db, which)
    sid = upload(client, sid_name, pdf(which, variant)[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    return sid


def test_a_statement_imports_its_rows_page_period_check_and_closing_balance(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = _ready(app, jr, db)
    r = commit(jr, [{"id": sid, "account_id": card.id, "include": []}])
    assert r.status_code == 201
    body = r.json()
    truth = pdf("chase_card")[1]
    assert (body["imported"], body["statements"], body["added_up"]) == (len(truth.rows), 1, 1)
    db.rollback()
    b = db.scalar(select(ImportBatch))
    assert (b.format, b.period_start, b.period_end, b.check_state, b.check_gap_cents) == \
        ("pdf", truth.period[0], truth.period[1], "adds_up", 0)
    assert (b.snapshot_as_of, b.snapshot_cents) == (truth.period[1], -truth.closing_cents)      # owed is negative
    snap = db.get(BalanceSnapshot, (card.id, truth.period[1]))
    assert snap.balance_cents == -truth.closing_cents
    pages = {t.raw_description: t.statement_page for t in db.scalars(select(Transaction))}
    assert set(pages.values()) == {1} and db.get(StatementStage, sid) is None
    purchases = [t for t in db.scalars(select(Transaction)) if t.raw_description != "AUTOMATIC PAYMENT - THANK YOU"
                 and not t.raw_description.startswith("RETURN")]
    assert all(t.amount_cents < 0 for t in purchases)


def test_an_existing_balance_is_kept_and_said(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    truth = pdf("chase_card")[1]
    db.add(BalanceSnapshot(account_id=card.id, as_of=truth.period[1], balance_cents=-12345))
    db.commit()
    sid = _ready(app, jr, db)
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": card.id, "include": []}], "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    assert p["balances"] == {"n": 1, "kept": 1, "rows": [{"account": "Mom's card", "as_of": truth.period[1].isoformat(),
                                                          "cents": -truth.closing_cents, "kept": True}]}
    r = jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    assert r.json()["kept_balances"] == [truth.period[1].isoformat()]
    db.rollback()
    assert db.get(BalanceSnapshot, (card.id, truth.period[1])).balance_cents == -12345


def test_a_csv_and_a_statement_of_the_same_month_see_each_other(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = _ready(app, jr, db)
    staged = stage_csv(jr, "chase-march.csv", chase_card_csv(pdf("chase_card")[1])).json()
    files = [file_choice(e, card.id) for e in staged["files"]]
    body = {"batch": staged["batch"], "files": files, "statements": [{"id": sid, "account_id": card.id, "include": []}],
            "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    by = {f["token"]: f for f in p["files"]}
    assert by[f"s{sid}"]["already"] == len(pdf("chase_card")[1].rows) and by[f"s{sid}"]["new"] == 0


def _deli(truth):
    deli = next(r for r in truth.rows if r["section"] == "PURCHASE")
    return deli, date.fromisoformat(deli["date"]), deli["description"].split()[0]


def test_the_widened_looks_the_same_for_statement_rows(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    deli, day, first = _deli(pdf("chase_card")[1])
    make_txn(db, card, day + timedelta(days=3), deli["amount_cents"], f"{first} SOMETHING ELSE")      # ± 3 days, first word
    make_txn(db, card, day - timedelta(days=4), deli["amount_cents"], f"{first} TOO FAR")             # 4 days: no
    sid = _ready(app, jr, db)
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": card.id, "include": []}], "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    same = [s for s in p["look"]["same"] if s["description"] == deli["description"]]
    assert len(same) == 1 and same[0]["match"]["description"] == f"{first} SOMETHING ELSE"


def test_a_different_first_word_within_three_days_is_not_looks_the_same(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    deli, day, first = _deli(pdf("chase_card")[1])
    make_txn(db, card, day + timedelta(days=2), deli["amount_cents"], f"ZZZZ{first} SOMETHING ELSE")
    sid = _ready(app, jr, db)
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": card.id, "include": []}], "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    assert not [s for s in p["look"]["same"] if s["description"] == deli["description"]]


def test_the_same_statement_twice_is_all_already(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = _ready(app, jr, db)
    commit(jr, [{"id": sid, "account_id": card.id, "include": []}])
    again = upload(jr, "again.pdf", pdf("chase_card")[0] + b"\n%copy").json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    body = {"batch": None, "files": [], "statements": [{"id": again, "account_id": card.id, "include": []}],
            "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    assert (p["new"], p["already"]) == (0, len(pdf("chase_card")[1].rows))
    jr.patch(f"/api/b/ours/import/statements/{again}", json={"account_id": card.id})
    line = next(x for x in jr.get("/api/b/ours/import/statements").json()["statements"] if x["id"] == again)
    assert line["imported_before"] == "2026-10-30"


def test_a_row_edit_after_the_preview_is_a_409(app, jr, db):
    answering(app, StandIn(answer=lambda sent, hint: pdf("chase_checking")[1].layout))
    acct = make_account(db, "Checking", type="checking")
    sid = upload(jr, "off.pdf", pdf("chase_checking", "off")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    jr.patch(f"/api/b/ours/import/statements/{sid}", json={"anyway": True})
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": acct.id, "include": []}], "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    jr.post(f"/api/b/ours/import/statements/{sid}/rows", json={"ops": [{"op": "remove", "i": 0}]})
    r = jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    assert r.status_code == 409 and "preview" in r.json()


def test_import_anyway_marks_the_batch_and_came_from(app, jr, db):
    answering(app, StandIn(answer=lambda sent, hint: pdf("chase_checking")[1].layout))
    acct = make_account(db, "Checking", type="checking")
    sid = upload(jr, "off.pdf", pdf("chase_checking", "off")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    jr.patch(f"/api/b/ours/import/statements/{sid}", json={"anyway": True})
    r = commit(jr, [{"id": sid, "account_id": acct.id, "include": []}])
    assert (r.status_code, r.json()["added_up"]) == (201, 0)
    db.rollback()
    b = db.scalar(select(ImportBatch))
    assert (b.check_state, b.check_gap_cents) == ("anyway", 1240)
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == b.id))
    came = jr.get(f"/api/b/ours/transactions/{tid}/came-from").json()["came_from"]
    assert (came["kind"], came["check"], came["gap_cents"], came["period"]) == \
        ("statement", "anyway", 1240, {"start": "2026-03-01", "end": "2026-03-31"})
    assert came["page"] in (1, 2)


def test_past_imports_tags_a_statement_with_its_period_and_check(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = _ready(app, jr, db)
    commit(jr, [{"id": sid, "account_id": card.id, "include": []}])
    f = jr.get("/api/b/ours/import/batches").json()["imports"][0]["files"][0]
    assert (f["format"], f["period_end"], f["check_state"], f["check_gap_cents"]) == \
        ("pdf", pdf("chase_card")[1].period[1].isoformat(), "adds_up", 0)


def test_only_ready_statements_reach_a_preview(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = upload(jr, "march.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass                                                 # waiting for Looks right
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": card.id, "include": []}], "simplefin_include": []}
    r = jr.post("/api/b/ours/import/batch/preview", json=body)
    assert (r.status_code, r.json()) == (422, {"error": "These files aren't ready yet."})


@pytest.mark.parametrize("statements", [
    [{"id": 1, "account_id": 1, "include": []}] * 2,                         # an id twice
    [{"id": 1, "account_id": 1, "include": [0, 0]}],                          # a row twice
    [{"id": 1, "account_id": 1, "include": [999]}],                           # a row it doesn't have
    [{"id": 1, "account_id": 1, "include": [], "extra": 1}],
    [{"id": True, "account_id": 1, "include": []}],
    [{"id": k, "account_id": 1, "include": []} for k in range(31)],
    [{"id": 10**30, "account_id": 1, "include": []}],
    [{"id": -1, "account_id": 1, "include": []}],
    "x"])
def test_the_statements_list_is_bounded(app, jr, db, statements):
    answering(app, StandIn())
    make_account(db, "Mom's card", type="credit")
    _ready(app, jr, db)
    body = {"batch": None, "files": [], "statements": statements, "simplefin_include": []}
    assert jr.post("/api/b/ours/import/batch/preview", json=body).status_code == 422


def test_an_oversized_account_id_is_refused_not_a_traceback(app, jr, db):
    answering(app, StandIn())
    make_account(db, "Mom's card", type="credit")
    sid = _ready(app, jr, db)
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": 10**30, "include": []}],
            "simplefin_include": []}
    r = jr.post("/api/b/ours/import/batch/preview", json=body)
    assert (r.status_code, r.json()) == (422, {"error": "These files aren't ready yet."})


@pytest.mark.parametrize("change", ["edit", "forget"])
def test_a_statement_changed_during_the_model_call_is_a_409_and_imports_nothing(app, jr, db, monkeypatch, change):
    from steward.api import imports as api
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    sid = _ready(app, jr, db)
    body = {"batch": None, "files": [], "statements": [{"id": sid, "account_id": card.id, "include": []}],
            "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    real = api.model_fill

    def meanwhile(*a, **k):
        st = db.get(StatementStage, sid)
        if change == "edit":
            st.updated_at = st.updated_at + timedelta(minutes=1)
        else:
            st.removed_at = st.updated_at
        db.commit()
        return real(*a, **k)
    monkeypatch.setattr(api, "model_fill", meanwhile)
    r = jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    assert r.status_code == 409 and r.json()["error"] == "Something changed since the preview. Check the new numbers."
    db.rollback()
    for m in (ImportSet, ImportBatch, Transaction, BalanceSnapshot):
        assert db.scalar(select(func.count()).select_from(m)) == 0, m
    assert db.get(StatementStage, sid) is not None


def test_undo_removes_the_rows_and_the_balance_it_wrote_unless_changed(app, jr, db):
    answering(app, StandIn())
    card = make_account(db, "Mom's card", type="credit")
    other = make_account(db, "Checking", type="checking")
    before = [(t.id, t.amount_cents, t.raw_description) for t in [make_txn(db, other, date(2026, 3, 2), -500, "MINE")]]
    sid = _ready(app, jr, db)
    set_id = commit(jr, [{"id": sid, "account_id": card.id, "include": []}]).json()["set_id"]
    truth = pdf("chase_card")[1]
    r = jr.post(f"/api/b/ours/import/sets/{set_id}/rollback")
    assert r.status_code == 200 and r.json()["kept"] == []
    db.rollback()
    assert db.get(BalanceSnapshot, (card.id, truth.period[1])) is None
    assert [(t.id, t.amount_cents, t.raw_description) for t in db.scalars(select(Transaction))] == before
    sid2 = _ready(app, jr, db, "again.pdf")
    set2 = commit(jr, [{"id": sid2, "account_id": card.id, "include": []}]).json()["set_id"]
    db.rollback()
    db.get(BalanceSnapshot, (card.id, truth.period[1])).balance_cents = 1
    db.commit()
    kept = jr.post(f"/api/b/ours/import/sets/{set2}/rollback").json()["kept"]
    assert kept == ["The Mar 31 balance was changed since, so it stays."]


def test_a_parent_book_records_one_import_per_statement(app, client, ddb, margaret, mdb):
    from steward.db.models import ChangeRecord
    login(client, "jr")
    answering(app, StandIn())
    acct = make_account(mdb, "Margaret's checking", type="checking")
    remember(mdb, "boa_checking")
    sid = upload(client, "boa.pdf", pdf("boa_checking")[0], slug=margaret.slug).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    r = commit(client, [{"id": sid, "account_id": acct.id, "include": []}], slug=margaret.slug)
    assert r.status_code == 201
    mdb.rollback()
    assert [c.action for c in mdb.scalars(select(ChangeRecord))].count("import.add") == 1


def test_the_model_is_asked_once_for_the_whole_batch(app, jr, db):
    from steward.services.categorize import INLINE_ROWS

    class Model:
        features, missed, last_error = frozenset(), False, None

        def __init__(self):
            self.calls = []

        def categorize_batch(self, rows, examples=()):
            self.calls.append(list(rows))
            return [None] * len(rows)
    answering(app, StandIn())
    model = app.state.model = Model()
    card = make_account(db, "Mom's card", type="credit")
    other = make_account(db, "Venture", type="credit")
    one = _ready(app, jr, db)
    two = _ready(app, jr, db, "venture.pdf", which="capone_card")
    r = commit(jr, [{"id": one, "account_id": card.id, "include": []}, {"id": two, "account_id": other.id, "include": []}])
    assert r.status_code == 201
    assert r.json()["imported"] > INLINE_ROWS                     # together they pass the shared allowance
    asked = sum(len(c) for c in model.calls)
    assert 0 < asked <= INLINE_ROWS


def test_a_failure_in_the_third_statement_leaves_nothing(app, jr, db, monkeypatch):
    from steward.api import imports as api
    answering(app, StandIn())
    accts = [make_account(db, n, type="credit") for n in ("A", "B", "C")]
    ids = [_ready(app, jr, db, "a.pdf", "chase_card"), _ready(app, jr, db, "b.pdf", "capone_card"),
           _ready(app, jr, db, "c.pdf", "amex_card")]
    real, calls = api._statement_extras, []

    def failing(*a, **k):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(api, "_statement_extras", failing)
    statements = [{"id": i, "account_id": a.id, "include": []} for i, a in zip(ids, accts)]
    body = {"batch": None, "files": [], "statements": statements, "simplefin_include": []}
    p = jr.post("/api/b/ours/import/batch/preview", json=body).json()
    with pytest.raises(RuntimeError):
        jr.post("/api/b/ours/import/batch/commit", json={**body, "digest": p["digest"]})
    db.rollback()
    db.rollback()
    for model in (ImportSet, ImportBatch, Transaction, BalanceSnapshot):
        assert db.scalar(select(func.count()).select_from(model)) == 0, model
    assert db.scalar(select(func.count()).select_from(StatementStage).where(StatementStage.id.in_(ids))) == 3


def test_the_encrypted_export_empties_staged_statements():
    from steward.services.book_export import EXPORT_EMPTIES, RESTORE_BLANKS
    assert "statement_stage" in EXPORT_EMPTIES and "statement_stage" in RESTORE_BLANKS
    assert {"chat_turn", "chat_message", "mail_outbox"} <= set(EXPORT_EMPTIES)         # the import round's stay


def test_merging_two_accounts_carries_staged_statements_and_layouts(app, jr, db):
    from steward.services.same_account.merge import merge
    answering(app, StandIn())
    keep, other = make_account(db, "Card A", type="credit"), make_account(db, "Card B", type="credit")
    sid = _ready(app, jr, db)
    jr.patch(f"/api/b/ours/import/statements/{sid}", json={"account_id": other.id})
    db.rollback()
    db.scalar(select(StatementLayout)).account_id = other.id
    db.commit()
    merge(db, keep.id, other.id, user_id=1, now=db.get(StatementStage, sid).updated_at)
    db.commit()
    db.rollback()
    assert db.get(StatementStage, sid).account_id == keep.id and db.scalar(select(StatementLayout)).account_id == keep.id
