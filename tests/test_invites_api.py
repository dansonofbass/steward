"""Task 9.5: an invite never adds an existing account without that account's consent."""
from steward import clock
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from steward.books.service import INVITE_DAYS, create_book
from steward.db.directory_models import Membership, MembershipChange, PendingInvite, User
from tests.factories import login, make_person

GONE = {"error": "That invite link isn't valid any more."}


@pytest.fixture
def world(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    sam = make_person(ddb, "sam", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret", "Joint"], by=jr.id)
    vee = make_person(ddb, "vee", [(mom.id, "viewer")])
    return {"jr": jr.id, "sam": sam.id, "vee": vee.id, "mom": mom, "ours": ours}


def _invite(client, email, name="Typed Name", role="viewer", slug="mom"):
    return client.post(f"/api/books/{slug}/members", json={"email": email, "display_name": name, "role": role})


def _pending(world, client, app, email="stranger@x.com"):
    login(client, "jr")
    _invite(client, email, "S")
    return app.state.mailer.sent[-1][2].split("/invite?token=")[1].split()[0]


def test_an_invite_answers_the_same_for_a_new_email_an_unrelated_account_and_a_repeat(world, client, ddb):
    stranger = make_person(ddb, "stranger", [])
    login(client, "jr")
    answers = [(e, _invite(client, e)) for e in
               ("brand.new@example.com", "stranger@x.com", "stranger@x.com", "brand.new@example.com")]
    for email, r in answers:
        assert r.status_code == 201
        assert r.json() == {"member": {"email": email, "role": "viewer", "status": "Invited"}, "invited": True}
    ddb.rollback()
    assert ddb.get(Membership, (stranger.id, world["mom"].id)) is None
    # a name is asked for in both cases, so leaving it out does not tell them apart either
    a = client.post("/api/books/mom/members", json={"email": "stranger@x.com", "role": "viewer"})
    b = client.post("/api/books/mom/members", json={"email": "other.new@x.com", "role": "viewer"})
    assert (a.status_code, a.json()) == (b.status_code, b.json())


def test_inviting_an_unrelated_account_makes_a_pending_invite_and_emails_a_seven_day_link(world, client, ddb, app):
    stranger = make_person(ddb, "stranger", [])
    login(client, "jr")
    _invite(client, "stranger@x.com", "S", "manager")
    ddb.rollback()
    pend = ddb.scalar(select(PendingInvite).where(PendingInvite.user_id == stranger.id))
    assert (pend.book_id, pend.role, pend.invited_by, pend.accepted_at) == (world["mom"].id, "manager", world["jr"], None)
    assert abs(pend.expires_at - clock.now() - timedelta(days=INVITE_DAYS)) < timedelta(minutes=1)
    to, subject, body = app.state.mailer.sent[-1]
    assert (to, subject) == ("stranger@x.com", "You've been invited to Mom")
    assert 'Jr invited you to "Mom" in Steward as a manager. Open this link while signed in to accept. ' \
           "It works for 7 days." in body
    token = body.split("/invite?token=")[1].split()[0]
    assert pend.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_a_manager_cannot_reach_reset_other_by_inviting_an_unrelated_account(world, client, ddb):
    make_person(ddb, "mgr", [(world["ours"].id, "manager")])
    victim = make_person(ddb, "victim", [])
    login(client, "mgr")
    book = client.post("/api/books", json={"name": "Mine", "kind": "parent", "owner_names": ["A"]}).json()["book"]
    _invite(client, "victim@x.com", "V", slug=book["slug"])
    assert "victim" not in [p["username"] for p in client.get("/api/users").json()["users"]]
    r = client.post(f"/api/users/{victim.id}/reset-password",
                    json={"current_password": "pw-one-two-3", "password": "taken-over-now"})
    assert r.status_code == 404


def test_accepting_an_invite_adds_the_membership_once(world, client, ddb, app):
    person = make_person(ddb, "stranger", [])
    token = _pending(world, client, app)
    login(client, "stranger")
    r = client.post("/api/invites/accept", json={"token": token})
    assert (r.status_code, r.json()) == (200, {"book": {"slug": "mom", "name": "Mom"}})
    ddb.rollback()
    assert ddb.get(Membership, (person.id, world["mom"].id)).role == "viewer"
    change = ddb.scalar(select(MembershipChange).where(MembershipChange.user_id == person.id))
    assert (change.action, change.role_after, change.by_user_id) == ("added", "viewer", world["jr"])
    used = client.post("/api/invites/accept", json={"token": token})
    assert (used.status_code, used.json()) == (404, GONE)


def test_accept_refuses_the_wrong_person_an_expired_token_and_signed_out(world, client, ddb, app):
    person = make_person(ddb, "stranger", [])
    token = _pending(world, client, app)
    login(client, "sam")
    assert client.post("/api/invites/accept", json={"token": token}).json() == GONE
    ddb.rollback()
    assert ddb.get(Membership, (world["sam"], world["mom"].id)) is None
    ddb.execute(update(PendingInvite).values(expires_at=clock.now() - timedelta(minutes=1)))
    ddb.commit()
    login(client, "stranger")
    r = client.post("/api/invites/accept", json={"token": token})
    assert (r.status_code, r.json()) == (404, GONE)
    ddb.rollback()
    assert ddb.get(Membership, (person.id, world["mom"].id)) is None
    client.cookies.clear()
    assert client.post("/api/invites/accept", json={"token": token}).status_code == 401


def test_accept_fails_when_the_inviter_no_longer_manages_the_book(world, client, ddb, app):
    make_person(ddb, "stranger", [])
    token = _pending(world, client, app)
    ddb.rollback()
    ddb.execute(update(Membership).where(Membership.user_id == world["jr"],
                                         Membership.book_id == world["mom"].id).values(role="viewer"))
    ddb.commit()
    login(client, "stranger")
    assert client.post("/api/invites/accept", json={"token": token}).status_code == 404


def test_managers_see_pending_invites_and_can_cancel_them(world, client, ddb, app):
    make_person(ddb, "stranger", [])
    login(client, "stranger")   # has signed in, so cancelling the invite keeps the account (ruling 30)
    token = _pending(world, client, app)
    _invite(client, "wren@x.com", "Wren")

    def invited():
        return [m for m in client.get("/api/books/mom/members").json()["members"] if m.get("status") == "Invited"]
    rows = invited()
    assert sorted((m["email"], m["role"]) for m in rows) == [("stranger@x.com", "viewer"), ("wren@x.com", "viewer")]
    assert all(m["username"] is None and m["display_name"] is None and m["user_id"] is None for m in rows)
    assert {type(m["invite_id"]) for m in rows} == {str}
    login(client, "vee")
    assert not invited()
    assert client.delete(f"/api/books/mom/invites/{rows[0]['invite_id']}").status_code == 403
    login(client, "jr")
    for m in rows:
        assert client.delete(f"/api/books/mom/invites/{m['invite_id']}").status_code == 204
    assert client.delete(f"/api/books/mom/invites/{rows[0]['invite_id']}").status_code == 404
    login(client, "stranger")
    assert client.post("/api/invites/accept", json={"token": token}).status_code == 404
    login(client, "jr")
    assert not invited()


def test_adding_someone_who_shares_a_book_still_happens_at_once(world, client, ddb, app):
    login(client, "jr")
    r = client.post("/api/books/mom/members", json={"email": "sam@x.com", "role": "viewer"})
    assert (r.status_code, r.json()["invited"]) == (201, False)
    assert r.json()["member"]["username"] == "sam"
    ddb.rollback()
    assert ddb.get(Membership, (world["sam"], world["mom"].id)) is not None
    assert app.state.mailer.sent[-1][1] == "You've been added to Mom"


def _seen_by(client, ddb, email, name, slug="mom"):
    """What a manager can read after inviting `email`: /api/users, every book's people, the members list."""
    r = _invite(client, email, name, slug=slug)
    ddb.rollback()
    users = client.get("/api/users").json()["users"]
    members = client.get(f"/api/books/{slug}/members").json()["members"]
    return r.json(), [(u["username"], u["email"]) for u in users], members


def test_inviting_a_new_email_and_an_unrelated_account_look_alike_in_users_and_people(world, client, ddb, books):
    make_person(ddb, "stranger", [])
    login(client, "jr")
    before = [(u["username"], u["email"]) for u in client.get("/api/users").json()["users"]]
    people_before = [p.username for p in books.people(world["mom"].id)]
    _, new_users, new_members = _seen_by(client, ddb, "brand.new@example.com", "Brand New")
    _, old_users, old_members = _seen_by(client, ddb, "stranger@x.com", "Stranger")
    assert new_users == old_users == before          # neither invitee appears in /api/users
    assert [p.username for p in books.people(world["mom"].id)] == people_before
    invited = [m for m in old_members if m.get("status") == "Invited"]
    assert [m["email"] for m in invited] == ["brand.new@example.com", "stranger@x.com"]


def test_invite_ids_cannot_tell_a_new_email_from_an_existing_account(world, client, ddb):
    make_person(ddb, "stranger", [])
    login(client, "jr")
    # the existing account is invited first, so its id comes before the new person's in either ordering
    _invite(client, "stranger@x.com", "S")
    _invite(client, "brand.new@example.com", "B")
    _invite(client, "other.new@example.com", "O")
    rows = [m for m in client.get("/api/books/mom/members").json()["members"] if m.get("status") == "Invited"]
    assert [m["email"] for m in rows] == ["stranger@x.com", "brand.new@example.com", "other.new@example.com"]
    ids = [m["invite_id"] for m in rows]
    assert all(i.isdigit() for i in ids)                              # one form for every row
    assert [m["user_id"] for m in rows] == [None, None, None]
    # the order is the order invited, not existing-first
    assert ids == sorted(ids, key=int)


def _sign_in_token(app) -> str:
    body = app.state.mailer.sent[-1][2]
    return body.split("/reset?token=")[1].split("&")[0]


def _invite_id(client, email):
    rows = client.get("/api/books/mom/members").json()["members"]
    return next(m["invite_id"] for m in rows if m.get("status") == "Invited" and m["email"] == email)


def test_cancelling_an_invite_to_a_new_address_removes_the_account_and_closes_its_link(world, client, ddb, app):
    login(client, "jr")
    _invite(client, "new.person@example.com", "New Person")
    token = _sign_in_token(app)
    assert client.delete(f"/api/books/mom/invites/{_invite_id(client, 'new.person@example.com')}").status_code == 204
    ddb.rollback()
    assert ddb.scalar(select(User).where(User.email == "new.person@example.com")) is None
    r = client.post("/api/auth/reset", json={"token": token, "password": "a-long-new-password-1"})
    assert (r.status_code, r.json()) == (400, {"error": "That link has expired or was already used."})


def test_an_invited_account_with_another_open_invite_is_kept(world, client, ddb, books, app):
    from steward.books.service import create_book
    create_book(books, ddb, name="Dad", kind="parent", owner_labels=["Joe"], by=world["jr"])
    login(client, "jr")
    _invite(client, "two.books@example.com", "Two Books")
    client.post("/api/books/dad/members", json={"email": "two.books@example.com", "display_name": "Two Books",
                                                "role": "viewer"})
    assert client.delete(f"/api/books/mom/invites/{_invite_id(client, 'two.books@example.com')}").status_code == 204
    ddb.rollback()
    assert ddb.scalar(select(User).where(User.email == "two.books@example.com")) is not None


def test_an_invited_person_who_has_signed_in_is_kept(world, client, ddb):
    stranger = make_person(ddb, "stranger", [])
    login(client, "stranger")   # a session row now exists
    login(client, "jr")
    _invite(client, "stranger@x.com", "S")
    assert client.delete(f"/api/books/mom/invites/{_invite_id(client, 'stranger@x.com')}").status_code == 204
    ddb.rollback()
    assert ddb.get(User, stranger.id) is not None


def test_cancelling_an_invite_keeps_a_real_account_that_has_never_signed_in(world, client, ddb):
    quiet = make_person(ddb, "quiet", [])      # a real username, no session yet
    login(client, "jr")
    _invite(client, "quiet@x.com", "Quiet")
    assert client.delete(f"/api/books/mom/invites/{_invite_id(client, 'quiet@x.com')}").status_code == 204
    ddb.rollback()
    assert ddb.get(User, quiet.id) is not None
