import pytest

from steward.books.service import create_book
from tests.factories import login, make_person


@pytest.fixture
def mom(books, ddb, ours):
    book = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Robert (husband)", "Joint"])
    make_person(ddb, "jr", [(ours.id, "manager"), (book.id, "manager")])
    return book


def test_a_parent_book_makes_accounts_through_its_items(mom, client):
    """Ruling 16. A parent book's owner keys are checked on its items (tests/test_inventory_items.py)."""
    login(client, "jr")
    r = client.post("/api/b/mom/accounts", json={"name": "Checking", "type": "checking", "owner": "robert-husband",
                                                 "balance_cents": 0})
    assert (r.status_code, r.json()) == (404, {"error": "This book doesn't have that."})


def test_ours_keeps_the_four_household_owners(mom, client):
    login(client, "jr")
    for key in ("jr", "spouse", "joint", "business"):
        r = client.post("/api/b/ours/accounts", json={"name": key, "type": "checking", "owner": key, "balance_cents": 0})
        assert r.status_code == 201, key
    assert client.post("/api/b/ours/accounts", json={"name": "x", "type": "checking", "owner": "margaret",
                                                     "balance_cents": 0}).status_code == 422


def test_the_transactions_filter_takes_the_books_keys(mom, client):
    login(client, "jr")
    assert client.get("/api/b/mom/transactions?owner=margaret").status_code == 200
    r = client.get("/api/b/mom/transactions?owner=jr")
    assert (r.status_code, r.json()) == (422, {"error": "Choose one of this book's owners."})


def test_a_new_feed_account_gets_the_books_default_owner(books, ddb):
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from steward.books.owners import default_owner
    from steward.db.models import Account, SimplefinLink
    from steward.services.simplefin.sync import sync_now
    from tests.fake_simplefin import make_fake

    # No Joint owner here, so the default is the first name; a sync that ignored the parameter would give "joint".
    book = create_book(books, ddb, name="Mom2", kind="parent", owner_labels=["Margaret", "Robert (husband)"])
    fake, state = make_fake()
    now = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
    state.add_account("conn1", "Big Bank", "bigbank", "acct1", 1000_00, int(now.timestamp()) - 3600, txns=[])
    eng = books.engine_for(book)
    with Session(eng) as db:
        db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=now))
        db.commit()
    with TestClient(fake) as http:
        sync_now(eng, http, None, now, ("testserver",), default_owner=default_owner(book.owner_names))
    with Session(eng) as db:
        assert db.scalar(select(Account.owner)) == "margaret"
