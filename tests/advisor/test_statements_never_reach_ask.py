"""P52: Ask never sees any of it. An About for a statement's row carries no filename, page or period, and no advisor
module imports the statement wire. (The word check over the advisor, boundary and turn modules lives with the others in
test_tools_never_read_notes.py.)"""
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import steward.advisor
from steward.advisor.about import AboutIn, resolve
from steward.advisor.aliases import Aliases
from steward.db.models import Transaction
from steward_boundary.about import about_text
from tests.factories import login, make_account, make_person
from tests.statement_files import pdf
from tests.statement_helpers import StandIn, answering, commit, remember, upload

TODAY = date(2026, 10, 30)


def test_no_advisor_module_imports_the_wire():
    root = Path(steward.advisor.__file__).parent
    assert not [str(p) for p in root.rglob("*.py") if "statements_wire" in p.read_text()]


def test_asking_about_a_statement_row_never_carries_the_file_page_or_period(app, client, books, ours, ddb, db):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    answering(app, StandIn())
    card = make_account(db, "Card", type="credit")
    remember(db, "chase_card")
    sid = upload(client, "zorblax-quillfeather.pdf", pdf("chase_card")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    bid = commit(client, [{"id": sid, "account_id": card.id, "include": []}]).json()["batch_ids"][0]
    db.rollback()
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == bid))
    with Session(books.engine_for(ours)) as s:
        out = resolve(s, ours, Aliases(s, ours, books.people(ours.id), save=False), AboutIn("transaction", tid), TODAY)
        s.rollback()
    said = json.dumps(out) + about_text(out)
    for word in ("zorblax", "quillfeather", "statement", "page", "2026-03-01", "period", "pdf"):
        assert word not in said.lower(), word


def test_asking_about_an_investment_account_never_carries_the_statement(app, client, books, ours, ddb, db):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    answering(app, StandIn())
    acct = make_account(db, "Brokerage", type="brokerage_taxable")
    remember(db, "fidelity_brokerage")
    sid = upload(client, "zorblax-quillfeather.pdf", pdf("fidelity_brokerage")[0]).json()["statement"]["id"]
    while app.state.statements.run_once():
        pass
    commit(client, [{"id": sid, "account_id": acct.id, "include": []}])
    db.rollback()
    with Session(books.engine_for(ours)) as s:
        out = resolve(s, ours, Aliases(s, ours, books.people(ours.id), save=False), AboutIn("account", acct.id), TODAY)
        s.rollback()
    said = (json.dumps(out) + about_text(out)).lower()
    for word in ("zorblax", "quillfeather", "statement", "pdf"):
        assert word not in said, word
