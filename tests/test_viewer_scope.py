"""Feedback 2026-10-25, section 0: a viewer (Rory) sees only the books they belong to, and every members, admin and
settings change refuses them: 403 in their own book, 404 in a book they aren't in, as open_book answers everyone."""
from steward import clock

import pytest
from sqlalchemy import select, update

from steward.books.service import create_book, invite
from steward.db.directory_models import Book, Membership, PendingInvite
from steward.deps import NO_SUCH_BOOK, NOT_IN_THIS_BOOK, VIEWER_COPY
from tests.factories import login, make_person


@pytest.fixture
def rory(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    dad = create_book(books, ddb, name="Dad", kind="parent", owner_labels=["Joe", "Joint"], by=jr.id)
    old = create_book(books, ddb, name="Old", kind="parent", owner_labels=["Ann"], by=jr.id)
    rory = make_person(ddb, "rory", [(ours.id, "viewer"), (old.id, "viewer")])
    ddb.execute(update(Book).where(Book.id == old.id).values(archived_at=clock.now()))
    res = invite(ddb, ours.id, "wren@example.com", "Wren", "viewer", by=jr.id)
    ddb.commit()
    pend = ddb.scalar(select(PendingInvite).where(PendingInvite.user_id == res.user.id))
    return {"jr": jr.id, "rory": rory.id, "dad": dad, "invite": pend.id}


def test_a_viewer_lists_only_their_own_books_and_none_of_their_managers_lines(rory, client):
    login(client, "rory")
    for url in ("/api/books", "/api/auth/me"):
        books = client.get(url).json()["books"]
        assert [(b["slug"], b["role"]) for b in books] == [("ours", "viewer")], url   # not Dad, not the archived one
        assert books[0]["profile"] is None and books[0]["reason"] is None


def test_a_viewer_sees_who_is_in_their_book_but_not_other_emails_or_who_is_invited(rory, client):
    """Spec 2.5: every member sees who can see the book. The emails and invites are for the managers' Members page,
    which a viewer's Settings no longer lists."""
    login(client, "rory")
    members = client.get("/api/books/ours/members").json()["members"]
    assert [(m["username"], m["role"]) for m in members] == [("jr", "manager"), ("rory", "viewer")]
    assert all("email" not in m for m in members) and "@" not in str(members)   # no emails, so not Wren's invite
    r = client.get("/api/books/dad/members")
    assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK})
    login(client, "jr")
    members = client.get("/api/books/ours/members").json()["members"]
    assert [m["email"] for m in members] == ["jr@x.com", "rory@x.com", "wren@example.com"]


def changes(m: dict) -> list[tuple[str, str, dict | None]]:
    """Every members, admin and settings change a manager makes from Settings."""
    return [
        ("PATCH", "/api/books/{slug}", {"name": "Rory's book"}),
        ("POST", "/api/books/{slug}/members", {"email": "new@x.com", "display_name": "New", "role": "viewer"}),
        ("PATCH", f"/api/books/{{slug}}/members/{m['rory']}", {"role": "manager"}),   # promoting themself
        ("PATCH", f"/api/books/{{slug}}/members/{m['jr']}", {"role": "viewer"}),
        ("DELETE", f"/api/books/{{slug}}/members/{m['jr']}", None),
        ("DELETE", f"/api/books/{{slug}}/invites/{m['invite']}", None),
        ("POST", "/api/b/{slug}/simplefin/link", {"setup_token": "made-up"}),
        ("DELETE", "/api/b/{slug}/simplefin", None),
        ("POST", "/api/b/{slug}/sync", None),
        ("POST", "/api/b/{slug}/accounts", {"name": "Car", "type": "vehicle"}),
        ("PUT", "/api/b/{slug}/business/settings", {}),
        ("POST", "/api/b/{slug}/business/rules", {"pattern": "ADOBE"}),
        ("PATCH", "/api/b/{slug}/watching/large", {"cents": 50000}),
        ("PATCH", "/api/b/{slug}/watching/cash-floor", {"cents": 50000}),
        ("PATCH", f"/api/b/{{slug}}/watching/emails/{m['jr']}", {"urgent": False}),
        ("POST", "/api/b/{slug}/watching/test-email", None),
        ("POST", "/api/b/{slug}/chat/on", {"on": True}),
        ("POST", "/api/b/{slug}/chat/budget", {"cap_cents": 100}),
        ("POST", "/api/b/{slug}/chat/grants", {}),
        ("POST", "/api/b/{slug}/profile/confirm", None),
    ]


def test_every_settings_change_refuses_a_viewer_in_their_book_and_is_404_in_a_book_they_arent_in(rory, client, ddb):
    login(client, "rory")
    for method, path, body in changes(rory):
        r = client.request(method, path.format(slug="ours"), json=body)
        assert (r.status_code, r.json()) == (403, {"error": VIEWER_COPY}), (method, path, r.text)
        r = client.request(method, path.format(slug="dad"), json=body)
        assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK}), (method, path, r.text)
    ddb.rollback()
    roles = dict(ddb.execute(select(Membership.user_id, Membership.role)).all())
    assert roles[rory["rory"]] == "viewer" and roles[rory["jr"]] == "manager"   # nothing they sent changed anything
    assert ddb.get(PendingInvite, rory["invite"]) is not None


def test_a_viewer_cannot_read_the_managers_export_add_a_book_or_reset_a_password(rory, client):
    login(client, "rory")
    r = client.get("/api/b/ours/chat/export")
    assert (r.status_code, r.json()) == (404, {"error": NOT_IN_THIS_BOOK})
    r = client.get("/api/b/dad/chat/export")
    assert (r.status_code, r.json()) == (404, {"error": NO_SUCH_BOOK})
    r = client.post("/api/books", json={"name": "Mine", "kind": "parent", "owner_names": ["A"]})
    assert (r.status_code, r.json()) == (403, {"error": "Only a manager of a book can add a book."})
    r = client.post(f"/api/users/{rory['jr']}/reset-password",
                    json={"current_password": "pw-one-two-3", "password": "taken-over-now"})
    assert r.status_code == 403
    people = client.get("/api/users").json()["users"]
    assert sorted(p["username"] for p in people) == ["jr", "rory"] and not any(p["can_reset"] for p in people)
    assert {p["username"]: p.get("email") for p in people} == {"jr": None, "rory": "rory@x.com"}   # only their own email
    login(client, "jr")
    people = client.get("/api/users").json()["users"]
    assert {p["username"]: p.get("email") for p in people} == {"jr": "jr@x.com", "rory": "rory@x.com"}
