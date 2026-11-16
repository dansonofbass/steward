from steward import clock
from datetime import timedelta

import hashlib

import pytest
from sqlalchemy import select, update

from steward.books.service import INVITE_DAYS, create_book
from steward.db.directory_models import Membership, MembershipChange, PasswordReset, PendingInvite, User
from tests.factories import login, make_person


@pytest.fixture
def world(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    sam = make_person(ddb, "sam", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"], by=jr.id)
    vee = make_person(ddb, "vee", [(mom.id, "viewer")])
    return {"jr": jr.id, "sam": sam.id, "vee": vee.id, "mom": mom, "ours": ours}


def test_me_lists_my_books_with_role_kind_owners_and_household_profile_marks(world, client):
    login(client, "jr")
    books = client.get("/api/auth/me").json()["books"]
    assert [(b["slug"], b["kind"], b["role"], b["available"]) for b in books] == [
        ("ours", "household", "manager", True), ("mom", "parent", "manager", True)]
    assert books[0]["owners"][:2] == [{"key": "jr", "label": "Jr"}, {"key": "spouse", "label": "Sam"}]
    assert books[0]["profile"] == {"seen": False, "confirmed": False, "later_until": None}
    assert books[1]["profile"] is None and books[1]["owners"][0] == {"key": "margaret", "label": "Margaret"}
    login(client, "vee")
    assert [b["slug"] for b in client.get("/api/books").json()["books"]] == ["mom"]


def test_a_manager_makes_a_parent_book_and_becomes_its_manager(world, client, ddb):
    login(client, "jr")
    r = client.post("/api/books", json={"name": "Dad", "kind": "parent", "owner_names": ["Joe", "Joint"]})
    assert r.status_code == 201 and r.json()["book"]["slug"] == "dad" and r.json()["book"]["role"] == "manager"
    bad = client.post("/api/books", json={"name": "Dad", "kind": "parent", "owner_names": []})
    assert (bad.status_code, bad.json()) == (422, {"error": "Enter one to eight owner names of up to 40 characters."})
    assert client.post("/api/books", json={"name": "", "kind": "parent", "owner_names": ["A"]}).status_code == 422
    login(client, "vee")
    r = client.post("/api/books", json={"name": "Mine", "kind": "parent", "owner_names": ["A"]})
    assert (r.status_code, r.json()) == (403, {"error": "Only a manager of a book can add a book."})


def test_renaming_keeps_the_slug(world, client):
    login(client, "jr")
    r = client.patch("/api/books/mom", json={"name": "Mom (Robin's)"})
    assert r.json()["book"]["name"] == "Mom (Robin's)" and r.json()["book"]["slug"] == "mom"
    assert client.patch("/api/books/mom", json={"name": "x" * 61}).status_code == 422


def test_inviting_someone_new_makes_their_account_and_emails_a_seven_day_link(world, client, ddb, app):
    login(client, "jr")
    r = client.post("/api/books/mom/members", json={"email": "Wren@Example.com", "display_name": "Wren", "role": "viewer"})
    assert r.status_code == 201 and r.json()["invited"] is True
    assert r.json()["member"] == {"email": "Wren@Example.com", "role": "viewer", "status": "Invited"}
    ddb.rollback()   # drop the fixture session's old snapshot so it sees what the request wrote
    wren = ddb.scalar(select(User).where(User.email == "wren@example.com"))
    assert wren.username.startswith("invited-") and wren.display_name == "Wren"
    reset = ddb.scalar(select(PasswordReset).where(PasswordReset.user_id == wren.id))
    assert abs(reset.expires_at - clock.now() - timedelta(days=INVITE_DAYS)) < timedelta(minutes=1)
    assert ddb.get(Membership, (wren.id, world["mom"].id)) is None   # nothing until they accept
    pend = ddb.scalar(select(PendingInvite).where(PendingInvite.user_id == wren.id))
    assert (pend.book_id, pend.role, pend.invited_by) == (world["mom"].id, "viewer", world["jr"])
    to, subject, body = app.state.mailer.sent[-1]
    assert (to, subject) == ("wren@example.com", "You've been invited to Mom")
    assert 'invited you to "Mom" in Steward as a viewer' in body and "&invite=1" in body
    assert "elder" not in body.lower()
    token = body.split("reset?token=")[1].split("&")[0]
    assert client.post("/api/auth/reset", json={"token": token, "password": "a-new-pass-word"}).status_code == 200
    login(client, "wren", "a-new-pass-word")   # the username is given when the password is set
    ddb.rollback()
    assert ddb.get(User, wren.id).username == "wren"
    assert client.get("/api/books").json()["books"] == []
    invite_token = body.split("/invite?token=")[1].split()[0]
    assert client.post("/api/invites/accept", json={"token": invite_token}).status_code == 200
    assert [b["slug"] for b in client.get("/api/books").json()["books"]] == ["mom"]


def test_inviting_an_existing_person_adds_them_at_once(world, client, app):
    login(client, "jr")
    r = client.post("/api/books/mom/members", json={"email": "sam@x.com", "role": "manager"})
    assert r.status_code == 201 and r.json()["invited"] is False and r.json()["member"]["role"] == "manager"
    to, subject, body = app.state.mailer.sent[-1]
    assert (to, subject) == ("sam@x.com", "You've been added to Mom")
    assert "/b/mom" in body
    again = client.post("/api/books/mom/members", json={"email": "sam@x.com", "role": "viewer"})
    assert (again.status_code, again.json()) == (409, {"error": "Sam is already in this book."})
    assert client.post("/api/books/mom/members", json={"email": "nope", "role": "viewer"}).status_code == 422
    assert client.post("/api/books/mom/members", json={"email": "new@x.com", "role": "viewer"}).json() == \
        {"error": "Enter their name, up to 80 characters."}


def test_the_last_manager_stays_and_changes_are_kept(world, client, ddb):
    login(client, "jr")
    r = client.patch(f"/api/books/mom/members/{world['jr']}", json={"role": "viewer"})
    assert (r.status_code, r.json()) == (409, {"error": "A book needs at least one manager."})
    assert client.delete(f"/api/books/mom/members/{world['jr']}").status_code == 409
    assert client.patch(f"/api/books/mom/members/{world['vee']}", json={"role": "manager"}).json()["member"]["role"] == "manager"
    assert client.delete(f"/api/books/mom/members/{world['vee']}").status_code == 204
    ddb.rollback()
    assert ddb.get(Membership, (world["vee"], world["mom"].id)) is None
    actions = ddb.execute(select(MembershipChange.action, MembershipChange.role_before, MembershipChange.role_after)
                          .where(MembershipChange.user_id == world["vee"]).order_by(MembershipChange.id)).all()
    assert actions == [("added", None, "viewer"), ("role_changed", "viewer", "manager"), ("removed", "manager", None)]
    login(client, "vee")
    assert client.get("/api/b/mom/accounts").status_code == 404   # gone means gone
    assert client.get("/api/auth/me").json()["books"] == []


def test_members_list_is_for_members_and_changes_are_for_managers(world, client):
    login(client, "vee")
    members = client.get("/api/books/mom/members").json()["members"]
    assert [(m["username"], m["role"]) for m in members] == [("jr", "manager"), ("vee", "viewer")]
    assert client.patch("/api/books/mom", json={"name": "Mine"}).status_code == 403
    login(client, "sam")
    assert client.get("/api/books/mom/members").status_code == 404


def test_a_viewer_cannot_reset_anyone_and_sees_only_people_in_their_books(world, client):
    login(client, "vee")
    people = client.get("/api/users").json()["users"]
    assert sorted(p["username"] for p in people) == ["jr", "vee"]
    assert all(p["can_reset"] is False for p in people)
    r = client.post(f"/api/users/{world['jr']}/reset-password",
                    json={"current_password": "pw-one-two-3", "password": "taken-over-now"})
    assert (r.status_code, r.json()) == (403, {"error": "You can reset a password only for people in books you manage."})
    r = client.post(f"/api/users/{world['sam']}/reset-password",
                    json={"current_password": "pw-one-two-3", "password": "taken-over-now"})
    assert r.status_code == 404   # sam shares no book with vee
    login(client, "jr")
    people = {p["username"]: p["can_reset"] for p in client.get("/api/users").json()["users"]}
    assert people == {"jr": False, "sam": True, "vee": True}
    login(client, "sam")   # sam manages ours only; jr is also in mom, which sam doesn't manage
    assert {p["username"]: p["can_reset"] for p in client.get("/api/users").json()["users"]}["jr"] is False


def test_cancelling_an_invite_never_removes_a_real_account_named_invited(world, ddb):
    from steward.auth.users import create_user
    from steward.books.service import cancel_invite
    real = create_user(ddb, "invited-x", "invited-x@example.com", "Real Person", "pw-one-two-3")
    ddb.commit()
    assert real.is_placeholder is False
    t = clock.now()
    pend = PendingInvite(book_id=world["mom"].id, user_id=real.id, role="viewer", invited_by=world["jr"],
                         token_hash=hashlib.sha256(b"t").hexdigest(), created_at=t, expires_at=t + timedelta(days=7))
    ddb.add(pend)
    ddb.commit()
    cancel_invite(ddb, world["mom"].id, str(pend.id), by=world["jr"])
    ddb.commit()
    assert ddb.get(User, real.id) is not None


def test_cancelling_an_invite_removes_the_placeholder_account_the_invite_made(world, ddb):
    from steward.books.service import cancel_invite, invite
    res = invite(ddb, world["mom"].id, "wren@example.com", "Wren", "viewer", by=world["jr"])
    ddb.commit()
    assert res.user.is_placeholder is True
    pend = ddb.scalar(select(PendingInvite).where(PendingInvite.user_id == res.user.id))
    uid = res.user.id
    cancel_invite(ddb, world["mom"].id, str(pend.id), by=world["jr"])
    ddb.commit()
    assert ddb.get(User, uid) is None


def test_a_manager_of_only_archived_books_cannot_add_a_book(world, client, ddb):
    from steward.db.directory_models import Book
    lone = make_person(ddb, "lone", [(world["mom"].id, "manager")])
    ddb.execute(update(Book).where(Book.id == world["mom"].id).values(archived_at=clock.now()))
    ddb.commit()
    login(client, "lone")
    r = client.post("/api/books", json={"name": "Mine", "kind": "parent", "owner_names": ["A"]})
    assert (r.status_code, r.json()) == (403, {"error": "Only a manager of a book can add a book."})


ONE_HOUSEHOLD = "Steward has one household book, made at setup. Add a parent book instead."


def _households(ddb) -> list[int]:
    from steward.db.directory_models import Book
    ddb.rollback()   # see what the requests wrote
    return list(ddb.scalars(select(Book.id).where(Book.kind == "household").order_by(Book.id)))


def _archive(ddb, book_id: int) -> None:
    """No route or command archives a book today; an older install, or a hand edit, might have one archived."""
    from steward.db.directory_models import Book
    ddb.execute(update(Book).where(Book.id == book_id).values(archived_at=clock.now()))
    ddb.commit()


def test_a_parent_book_manager_cannot_make_a_household_book(world, client, ddb):
    """The escalation the Nov 8 review found: a manager of a parent book only made a household book, managed it, and so
    reached the install's settings (the email server, the gateway pairing)."""
    make_person(ddb, "momsmgr", [(world["mom"].id, "manager")])
    login(client, "momsmgr")
    r = client.post("/api/books", json={"name": "Ours too", "kind": "household", "owner_names": []})
    assert (r.status_code, r.json()) == (422, {"error": ONE_HOUSEHOLD})
    assert _households(ddb) == [world["ours"].id]
    assert client.get("/api/install/settings").status_code == 404


def test_the_api_never_makes_a_household_book_even_with_none_open(world, client, ddb):
    """With the household archived there is no install manager at all; a parent-book manager still can't make one."""
    make_person(ddb, "momsmgr", [(world["mom"].id, "manager")])
    _archive(ddb, world["ours"].id)
    for who in ("jr", "momsmgr"):
        login(client, who)
        r = client.post("/api/books", json={"name": "Ours too", "kind": "household", "owner_names": []})
        assert (r.status_code, r.json()) == (422, {"error": ONE_HOUSEHOLD}), who
        assert client.get("/api/install/settings").status_code == 404, who
    assert _households(ddb) == [world["ours"].id]


def test_nobody_makes_a_second_household_book(world, client, books, ddb):
    from steward.books.service import BookRefused
    login(client, "jr")                                  # a manager of the household itself
    r = client.post("/api/books", json={"name": "Ours too", "kind": "household", "owner_names": []})
    assert (r.status_code, r.json()) == (422, {"error": ONE_HOUSEHOLD})
    for allow in (False, True):                          # nor the service, even as `steward book create` calls it
        with pytest.raises(BookRefused, match=ONE_HOUSEHOLD):
            create_book(books, ddb, name="Second", kind="household", managers=[world["jr"]], allow_household=allow)
    assert _households(ddb) == [world["ours"].id]


def test_only_the_command_line_makes_a_household_book_and_only_while_none_is_open(world, books, ddb):
    from steward.books.service import BookRefused
    _archive(ddb, world["ours"].id)
    with pytest.raises(BookRefused, match=ONE_HOUSEHOLD):
        create_book(books, ddb, name="Ours again", kind="household", managers=[world["jr"]])
    again = create_book(books, ddb, name="Ours again", kind="household", managers=[world["jr"]], allow_household=True)
    with pytest.raises(BookRefused, match=ONE_HOUSEHOLD):
        create_book(books, ddb, name="Third", kind="household", managers=[world["jr"]], allow_household=True)
    assert _households(ddb) == [world["ours"].id, again.id]
