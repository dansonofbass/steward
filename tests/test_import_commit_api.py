"""The commit (spec P18, P19, P20; Batch preview and commit; Undo): the server recomputes, a changed plan is a 409 with
the new preview, one transaction for the batch, one model allowance, layouts and OFX hints saved at commit, one Undo
for the batch, and JR's existing rows untouched."""
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import EventLog, ImportBatch, ImportHint, ImportLayout, ImportSet, Transaction
from tests.factories import login, make_account, make_person, make_txn
from tests.import_helpers import file_choice, import_file, preview, stage

COLUMNS = ("id", "account_id", "posted_at", "amount_cents", "raw_description", "external_id", "merchant", "category",
           "is_transfer", "transfer_peer_id", "reviewed_at", "import_batch_id", "business_pct")


def _jr(client, ddb, ours):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")


def _count(db, model) -> int:
    db.rollback()
    return db.scalar(select(func.count()).select_from(model))


def test_a_commit_imports_n_saves_the_layout_and_negates_amex(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Amex", type="credit")
    r = stage(client, "amex-basic.csv")
    batch, [e] = r.json()["batch"], r.json()["files"]
    files = [file_choice(e, card.id, negate=True)]
    p = preview(client, batch, files).json()
    assert _count(db, ImportLayout) == 0                          # saved at commit, not at preview
    c = client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "simplefin_include": [],
                                                              "digest": p["digest"]})
    assert c.status_code == 201
    body = c.json()
    assert {k: body[k] for k in ("imported", "accounts", "account", "skipped", "months")} == \
        {"imported": 10, "accounts": 1, "account": "Amex", "skipped": 0, "months": 3}
    db.rollback()
    coffee = db.scalar(select(Transaction).where(Transaction.raw_description == "BLUE BOTTLE COFFEE",
                                                 Transaction.posted_at == date(2024, 10, 2)))
    assert coffee.amount_cents == -650                            # a purchase is money out
    s = db.get(ImportSet, body["set_id"])
    [b] = db.scalars(select(ImportBatch).where(ImportBatch.set_id == s.id)).all()
    lay = db.get(ImportLayout, b.layout_id)
    assert (b.id, b.format, b.row_count, len(b.content_sha256)) == (body["batch_ids"][0], "layout", 10, 64)
    assert (lay.label, lay.header, lay.negate, lay.date_format, lay.account_id, lay.uses) == \
        ("Amex", '["Date", "Description", "Amount"]', True, "%m/%d/%Y", card.id, 1)
    assert db.scalars(select(EventLog.message).where(EventLog.kind == "import")).all() == \
        ["Imported 10 rows into Amex from amex-basic.csv"]
    [again] = stage(client, "amex-basic.csv").json()["files"]
    assert (again["state"], again["label"], again["account_id"], again["suggested_by"], again["imported_before"]) == \
        ("remembered", "Amex", card.id, "layout", "2026-10-30")


def test_a_row_inserted_after_the_preview_is_a_409_with_the_new_preview(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    r = stage(client, "chase-card.csv")
    batch, files = r.json()["batch"], [file_choice(r.json()["files"][0], card.id)]
    p = preview(client, batch, files).json()
    make_txn(db, card, date(2024, 10, 3), -6418, "TRADER JOE'S #552")
    c = client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "digest": p["digest"]})
    assert c.status_code == 409
    assert c.json()["error"] == "Something changed since the preview. Check the new numbers."
    assert (c.json()["preview"]["new"], c.json()["preview"]["already"]) == (4, 1)
    assert _count(db, ImportSet) == 0 and _count(db, ImportBatch) == 0


class _Landing:
    """A categorizer that, while it's asked, lets a sync land a row the file also has."""
    last_error, missed = None, False

    def __init__(self, engine, account_id):
        self.engine, self.account_id, self.calls = engine, account_id, 0

    def categorize(self, d, a):
        raise AssertionError("batches only")

    def categorize_batch(self, rows, examples=()):
        self.calls += 1
        with Session(self.engine.execution_options(immediate=True)) as w:
            w.add(Transaction(account_id=self.account_id, posted_at=date(2024, 10, 7), amount_cents=-1549,
                              raw_description="STREAMFLIX.COM", external_id="sfin-landed"))
            w.commit()
        return [None] * len(rows)


def test_a_row_that_lands_during_the_model_call_is_a_409(app, client, db, ddb, ours, engine):
    """Review focus 3 (plan Engineering choice 7): the plan is recomputed under the write lock after the model."""
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    app.state.model = _Landing(engine, card.id)
    r = stage(client, "chase-card.csv")
    batch, files = r.json()["batch"], [file_choice(r.json()["files"][0], card.id)]
    p = preview(client, batch, files).json()
    c = client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "digest": p["digest"]})
    assert (c.status_code, c.json()["preview"]["already"]) == (409, 1)
    assert app.state.model.calls == 1
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == card.id)) == 1


def test_a_failure_in_the_third_file_leaves_nothing(client, db, ddb, ours, monkeypatch):
    from steward.services import imports as svc
    _jr(client, ddb, ours)
    accts = [make_account(db, f"Card {i}", type="credit") for i in range(3)]
    batch, entries = None, []
    for name in ("amex-basic.csv", "discover.csv", "citi.csv"):
        r = stage(client, name, batch=batch).json()
        batch, entries = r["batch"], entries + r["files"]
    files = [file_choice(e, a.id, negate=True) for e, a in zip(entries, accts)]
    p = preview(client, batch, files).json()
    real, calls = svc.commit_batch, []

    def third_fails(*a, **k):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("disk full")
        return real(*a, **k)
    monkeypatch.setattr(svc, "commit_batch", third_fails)
    with pytest.raises(RuntimeError):
        client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "digest": p["digest"]})
    assert [_count(db, m) for m in (ImportSet, ImportBatch, ImportLayout, Transaction)] == [0, 0, 0, 0]


def test_one_model_allowance_across_the_batch(app, client, db, ddb, ours):
    _jr(client, ddb, ours)

    class Counting:
        last_error, missed = None, False

        def __init__(self):
            self.batches = []

        def categorize(self, d, a):
            raise AssertionError("batches only")

        def categorize_batch(self, rows, examples=()):
            self.batches.append(len(rows))
            return [None] * len(rows)
    app.state.model = Counting()
    accts = [make_account(db, f"Card {i}", type="credit") for i in range(3)]
    batch, entries = None, []
    for i in range(3):
        rows = "".join(f"10/{d:02d}/2024,10/{d:02d}/2024,ODD SHOP {i}-{d},Shopping,Sale,-{d}.00,\n" for d in range(1, 31))
        raw = ("Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n" + rows).encode()
        r = stage(client, f"{i}.csv", raw, batch=batch).json()
        batch, entries = r["batch"], entries + r["files"]
    files = [file_choice(e, a.id) for e, a in zip(entries, accts)]
    p = preview(client, batch, files).json()
    c = client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "digest": p["digest"]})
    assert (c.status_code, c.json()["imported"]) == (201, 90)
    assert app.state.model.batches == [50] and app.state.model.missed is True


def test_household_matching_runs_once_per_batch(client, db, ddb, ours, monkeypatch):
    _jr(client, ddb, ours)
    calls = []
    monkeypatch.setattr("steward.api.imports.match_all", lambda s, today, by: calls.append(by))
    a, b = make_account(db, "A", type="credit"), make_account(db, "B", type="credit")
    r1 = stage(client, "chase-card.csv").json()
    r2 = stage(client, "discover.csv", batch=r1["batch"]).json()
    files = [file_choice(r1["files"][0], a.id), file_choice(r2["files"][0], b.id)]
    p = preview(client, r1["batch"], files).json()
    client.post("/api/b/ours/import/batch/commit", json={"batch": r1["batch"], "files": files, "digest": p["digest"]})
    assert len(calls) == 1


def test_a_parent_book_records_each_file_and_runs_its_hooks_once(client, margaret, mdb, monkeypatch):
    from steward.db.models import ChangeRecord
    login(client, "jr")
    hooks = []
    monkeypatch.setattr("steward.api.imports.after_new_data", lambda db, today, msg: hooks.append("after"))
    monkeypatch.setattr("steward.api.imports.watch_after", lambda s, why: hooks.append(why))
    a, b = make_account(mdb, "Joint checking"), make_account(mdb, "Savings", type="savings")
    r1 = stage(client, "chase-checking.csv", slug="margaret-ellis").json()
    r2 = stage(client, "bank.ofx", batch=r1["batch"], slug="margaret-ellis").json()
    files = [file_choice(r1["files"][0], a.id), file_choice(r2["files"][0], b.id)]
    p = preview(client, r1["batch"], files, slug="margaret-ellis").json()
    c = client.post("/api/b/margaret-ellis/import/batch/commit", json={"batch": r1["batch"], "files": files,
                                                                       "digest": p["digest"]})
    assert c.status_code == 201 and hooks == ["after", "import"]
    mdb.rollback()
    recs = mdb.scalars(select(ChangeRecord).where(ChangeRecord.action == "import.add").order_by(ChangeRecord.id)).all()
    assert [r.target_id for r in recs] == c.json()["batch_ids"]
    assert all(f'"set": {c.json()["set_id"]}' in r.after for r in recs)


def test_a_parent_commit_watches_a_5_mb_recipient_in_time(frozen, client, margaret, mdb, monkeypatch):
    """SEC-3's class at commit: Watching runs payee() on every new row's raw text. A 5 MB OFX name of
    "ZELLE TO A TO A ... !" held the server for hours there. payee() itself is linear on such text
    (tests/test_linear_parsing.py); here the row reaches it cut to DESCRIPTION_MAX. The spy refuses longer text
    rather than run it: the commit runs in a worker thread, and one long `re` call there holds the interpreter lock,
    so no pytest timeout could end the run."""
    import steward.watch.checks as checks
    from steward.services.importers.base import DESCRIPTION_MAX
    seen, real = [], checks.payee

    def spy(raw, merchant=None):
        seen.append(raw)
        assert len(raw) <= DESCRIPTION_MAX
        return real(raw, merchant)

    monkeypatch.setattr(checks, "payee", spy)
    login(client, "jr")
    a = make_account(mdb, "Joint checking")
    name = "ZELLE" + " TO A" * ((5 * 1024 * 1024 - 200) // 5) + "!"
    raw = f"<OFX><STMTTRN><DTPOSTED>20261012<TRNAMT>-1.00<FITID>1<NAME>{name}</STMTTRN></OFX>".encode()
    c = import_file(client, "x.ofx", a.id, raw=raw, slug="margaret-ellis")
    assert c.status_code == 201, c.text
    mdb.rollback()
    (t,) = mdb.scalars(select(Transaction)).all()
    assert t.raw_description == name[:DESCRIPTION_MAX - 1] + "…"
    assert seen and all(len(r) <= DESCRIPTION_MAX for r in seen)
    assert t.raw_description in seen   # Watching read it
    assert mdb.scalar(select(func.count()).select_from(EventLog).where(EventLog.level == "error")) == 0


def test_the_set_undo_removes_every_file_still_in_and_skips_one_undone(client, db, ddb, ours):
    _jr(client, ddb, ours)
    a, b = make_account(db, "A", type="credit"), make_account(db, "B", type="credit")
    r1 = stage(client, "chase-card.csv").json()
    r2 = stage(client, "discover.csv", batch=r1["batch"]).json()
    files = [file_choice(r1["files"][0], a.id), file_choice(r2["files"][0], b.id)]
    p = preview(client, r1["batch"], files).json()
    c = client.post("/api/b/ours/import/batch/commit", json={"batch": r1["batch"], "files": files,
                                                             "digest": p["digest"]}).json()
    assert client.post(f"/api/b/ours/import/batches/{c['batch_ids'][0]}/rollback").json() == {"deleted": 5, "kept": []}
    assert client.post(f"/api/b/ours/import/sets/{c['set_id']}/rollback").json() == {"deleted": 3, "kept": []}
    assert _count(db, Transaction) == 0
    again = client.post(f"/api/b/ours/import/sets/{c['set_id']}/rollback")
    assert (again.status_code, again.json()) == (409, {"error": "That import was already undone."})
    assert client.post("/api/b/ours/import/sets/9999/rollback").json() == {"error": "That import doesn't exist."}
    [group] = client.get("/api/b/ours/import/batches").json()["imports"]
    assert (group["set_id"], len(group["files"]), group["rolled_back_at"] is not None) == (c["set_id"], 2, True)


def test_past_imports_group_files_by_batch_and_keep_legacy_ones_alone(client, db, ddb, ours):
    from datetime import datetime, timezone
    _jr(client, ddb, ours)
    a = make_account(db, "A", type="credit")
    db.add(ImportBatch(account_id=a.id, filename="old.csv", format="chase_card", row_count=2, imported_by=1,
                       imported_at=datetime(2026, 9, 1, tzinfo=timezone.utc)))
    db.commit()
    c = import_file(client, "two-accounts.ofx", a.id).json()
    groups = client.get("/api/b/ours/import/batches").json()["imports"]
    assert [(g["set_id"], [f["filename"] for f in g["files"]]) for g in groups] == [
        (c["set_id"], ["two-accounts.ofx · ••1111", "two-accounts.ofx · ••2222"]), (None, ["old.csv"])]
    assert set(groups[1]["files"][0]) == {"id", "account_id", "account_name", "filename", "format", "row_count",
                                          "imported_at", "imported_by", "rolled_back_at", "period_end", "check_state",
                                              "check_gap_cents"}


def test_an_ofx_hint_is_saved_and_the_full_account_number_is_stored_nowhere(client, db, ddb, ours, engine):
    _jr(client, ddb, ours)
    checking = make_account(db, "Checking")
    assert import_file(client, "bank.ofx", checking.id).status_code == 201
    db.rollback()
    assert db.get(ImportHint, "ofx:121000000:6789").account_id == checking.id
    with engine.connect() as conn:
        tables = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'").scalars().all()
        dump = "\n".join(repr(row) for t in tables for row in conn.exec_driver_sql(f'SELECT * FROM "{t}"'))
    assert "0000456789" not in dump and "ofx:121000000:6789" in dump


def test_jrs_existing_rows_are_untouched_by_an_import_and_its_undo(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Card", type="credit")
    mine = [make_txn(db, card, date(2024, 10, 3), -6418, "TRADER JOE'S #552", category="groceries"),
            make_txn(db, card, date(2024, 9, 1), -100, "OLDER ROW", category="dining")]
    cols = [getattr(Transaction, c) for c in COLUMNS]
    ids = [t.id for t in mine]

    def snapshot():
        db.rollback()
        return db.execute(select(*cols).where(Transaction.id.in_(ids)).order_by(Transaction.id)).all()
    before = snapshot()
    c = import_file(client, "chase-card.csv", card.id).json()
    assert (c["imported"], c["skipped"]) == (4, 1)
    assert snapshot() == before
    client.post(f"/api/b/ours/import/sets/{c['set_id']}/rollback")
    assert snapshot() == before and _count(db, Transaction) == 2


def test_a_row_in_another_account_is_not_already_and_a_simplefin_row_without_an_id_match_is(client, db, ddb, ours):
    _jr(client, ddb, ours)
    a, b = make_account(db, "A", type="credit"), make_account(db, "B", type="credit")
    make_txn(db, b, date(2024, 10, 3), -6418, "TRADER JOE'S #552", external_id="sfin-1")
    assert import_file(client, "chase-card.csv", a.id).json()["imported"] == 5
    assert import_file(client, "chase-card.csv", b.id).json()["imported"] == 4


def test_the_old_single_file_routes_are_gone(client, db, ddb, ours):
    _jr(client, ddb, ours)
    for path in ("/api/b/ours/import/preview", "/api/b/ours/import/commit"):
        assert client.post(path, content=b"x", headers={"content-type": "application/octet-stream"}).status_code in (404, 405)


def test_viewers_cant_commit_or_undo(client, ddb, ours):
    make_person(ddb, "val", [(ours.id, "viewer")])
    login(client, "val")
    assert client.post("/api/b/ours/import/batch/commit", json={}).status_code == 404
    assert client.post("/api/b/ours/import/sets/1/rollback").status_code == 404


def test_the_commit_says_how_many_of_its_new_rows_wait_in_review(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Amex", type="credit")
    r = stage(client, "amex-basic.csv")
    batch, [e] = r.json()["batch"], r.json()["files"]
    files = [file_choice(e, card.id, negate=True)]
    p = preview(client, batch, files).json()
    body = client.post("/api/b/ours/import/batch/commit", json={"batch": batch, "files": files, "simplefin_include": [],
                                                                 "digest": p["digest"]}).json()
    db.rollback()
    waiting = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.import_batch_id.in_(body["batch_ids"]), Transaction.category == "uncategorized",
        Transaction.is_transfer.is_(False), Transaction.reviewed_at.is_(None)))
    assert body["waiting"] == waiting and 0 <= waiting <= body["imported"]


def test_the_commit_counts_its_possible_duplicates_apart_from_rows_to_sort(client, db, ddb, ours):
    """Issue #32: the receipt says why rows wait. A row imported anyway beside one Steward has (same amount and
    description, a day apart) is a possible duplicate in Review; rows already in the book don't count."""
    _jr(client, ddb, ours)
    card = make_account(db, "Amex", type="credit")
    make_txn(db, card, date(2024, 10, 3), -650, "BLUE BOTTLE COFFEE")
    make_txn(db, card, date(2024, 1, 3), -900, "OLD SHOP")
    make_txn(db, card, date(2024, 1, 4), -900, "OLD SHOP")          # a pair from before, not this commit's
    body = import_file(client, "amex-basic.csv", card.id, negate=True, include_same=True).json()
    assert body["imported"] == 10 and body["duplicates"] == 1


def test_a_commit_with_no_near_rows_has_no_duplicates(client, db, ddb, ours):
    _jr(client, ddb, ours)
    card = make_account(db, "Amex", type="credit")
    assert import_file(client, "amex-basic.csv", card.id, negate=True).json()["duplicates"] == 0
