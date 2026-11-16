"""Came from, Privacy (JR, Oct 31): the line and the filename never enter Ask's About context or any gateway payload,
as notes and nicknames don't. Ask builds what a question is about from typed columns only (steward/advisor/about.py);
this asks it about a row imported from a file whose name is an invented word."""
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.advisor.about import AboutIn, resolve
from steward.advisor.aliases import Aliases
from steward.db.models import Transaction
from steward_boundary.about import about_text
from tests.factories import login, make_account, make_person
from tests.import_helpers import import_file

TODAY = date(2026, 10, 30)


def test_asking_about_an_imported_row_never_carries_the_file(client, books, ours, ddb, db):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    card = make_account(db, "Card", type="credit")
    raw = ("Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
           "10/03/2024,10/04/2024,HARBOR GROCERY,Groceries,Sale,-64.18,\n").encode()
    bid = import_file(client, "zorblax-quillfeather.csv", card.id, raw=raw).json()["batch_ids"][0]
    db.rollback()
    tid = db.scalar(select(Transaction.id).where(Transaction.import_batch_id == bid))
    with Session(books.engine_for(ours)) as s:
        out = resolve(s, ours, Aliases(s, ours, books.people(ours.id), save=False), AboutIn("transaction", tid), TODAY)
        s.rollback()
    said = json.dumps(out) + about_text(out)
    assert "zorblax" not in said and "quillfeather" not in said and "came_from" not in said and "imported" not in said
