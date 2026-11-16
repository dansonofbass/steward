import pytest
from sqlalchemy.orm import Session

from steward.books.service import create_book
from steward.db.engine import WrongKey, check_key, make_engine
from steward.db.keys import directory_key
from steward.deps import NO_SUCH_BOOK, NOT_IN_THIS_BOOK, VIEWER_COPY
from tests.factories import login, make_person

NEW = {"name": "Checking", "type": "checking", "owner": "joint", "balance_cents": 1000}


@pytest.fixture
def world(books, ddb, ours):
    mom = create_book(books, ddb, name="Mom (Robin's)", kind="parent", owner_labels=["Margaret", "Joint"])
    make_person(ddb, "jr", [(ours.id, "manager"), (mom.id, "manager")])
    make_person(ddb, "vee", [(mom.id, "viewer")])
    make_person(ddb, "pat", [(ours.id, "manager")])
    return {"ours": ours, "mom": mom}


def test_a_new_book_gets_a_slug_its_own_file_and_a_derived_key(world, books):
    mom = world["mom"]
    assert (mom.slug, mom.kind, mom.key_scheme, mom.file) == ("mom-robins", "parent", "derived", "books/mom-robins/book.db")
    assert books.path_for(mom).exists()
    assert [o.key for o in mom.owner_names] == ["margaret", "joint"]


def test_one_books_file_cannot_be_opened_with_any_other_key(world, books, ddb):
    other = create_book(books, ddb, name="Dad", kind="parent", owner_labels=["Joe"])
    mom, ours = world["mom"], world["ours"]
    for book in (mom, other):
        for key in (books.master, directory_key(books.master), books.key_for(ours if book is other else other)):
            eng = make_engine(books.path_for(book), key)
            with pytest.raises(WrongKey):
                check_key(eng)
            eng.dispose()
    eng = make_engine(books.path_for(ours), books.key_for(mom))
    with pytest.raises(WrongKey):
        check_key(eng)
    eng.dispose()


def test_non_members_get_404_and_never_403(world, client):
    login(client, "pat")
    for method, path in (("get", "/api/b/mom-robins/accounts"), ("post", "/api/b/mom-robins/accounts"),
                         ("get", "/api/b/nope/accounts")):
        r = getattr(client, method)(path)
        assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK})


def test_viewers_read_and_get_the_plain_refusal_on_writes(world, client):
    login(client, "vee")
    assert client.get("/api/b/mom-robins/accounts").json() == {"accounts": []}
    r = client.post("/api/b/mom-robins/accounts", json=NEW)
    assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY})


def test_books_keep_their_money_apart(world, client):
    login(client, "jr")
    # A parent book makes accounts through its inventory items (ruling 16), so the household book takes this one.
    assert client.post("/api/b/ours/accounts", json={**NEW, "name": "Our checking"}).status_code == 201
    assert [a["name"] for a in client.get("/api/b/ours/accounts").json()["accounts"]] == ["Our checking"]
    assert client.get("/api/b/mom-robins/accounts").json() == {"accounts": []}


def test_household_screens_are_not_in_a_parent_book(world, client):
    login(client, "jr")
    for path in ("/api/b/mom-robins/plan", "/api/b/mom-robins/profile", "/api/b/mom-robins/children",
                 "/api/b/mom-robins/facts", "/api/b/mom-robins/ss", "/api/b/mom-robins/checklist",
                 "/api/b/mom-robins/next-dollar",
                 "/api/b/mom-robins/asset-classes"):
        r = client.get(path)
        assert (r.status_code, r.json()) == (404, {"error": NOT_IN_THIS_BOOK}), path
    assert client.get("/api/b/ours/profile").status_code == 200


def test_an_unavailable_book_says_so_with_the_reason_for_managers_only(world, client, books):
    mom = world["mom"]
    books.close(mom.id)
    books.unavailable[mom.id] = "The book's file is missing."
    login(client, "jr")
    r = client.get("/api/b/mom-robins/accounts")
    assert (r.status_code, r.json()) == (503, {"error": "This book can't be opened right now.",
                                               "reason": "The book's file is missing."})
    login(client, "vee")
    assert client.get("/api/b/mom-robins/accounts").json()["reason"] is None
    assert client.get("/api/b/ours/accounts").status_code == 404   # vee isn't in ours
    login(client, "jr")
    assert client.get("/api/b/ours/accounts").status_code == 200   # the other books still work


def test_the_engine_is_opened_once_and_reused(world, client, books):
    login(client, "jr")
    books.close(world["mom"].id)
    client.get("/api/b/mom-robins/accounts")
    first = books.engine_for(world["mom"])
    client.get("/api/b/mom-robins/accounts")
    assert books.engine_for(world["mom"]) is first


def test_the_slug_skips_reserved_and_taken_names(books, ddb):
    assert create_book(books, ddb, name="Directory", kind="parent", owner_labels=["A"]).slug == "directory-2"
    assert create_book(books, ddb, name="Mom", kind="parent", owner_labels=["A"]).slug == "mom"
    assert create_book(books, ddb, name="Mom!", kind="parent", owner_labels=["A"]).slug == "mom-2"
