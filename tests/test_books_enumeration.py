"""Task 9.6: a manager must not learn whether an address that shares no book they manage has an account.

`known` is a real account (bob, a manager of a book jr does not manage); `unknown` has no account. Every
response, the Members list afterwards and the other routes a manager can reach must match field for field."""
import json
import time

import pytest
from sqlalchemy import select

from steward.books.service import create_book
from steward.db.directory_models import Membership, User
from tests.factories import login, make_person

NAME_RULE = {"error": "Enter their name, up to 80 characters."}


@pytest.fixture
def twins(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"], by=jr.id)
    pat = make_person(ddb, "pat", [(ours.id, "viewer")])
    other = create_book(books, ddb, name="Other", kind="parent", owner_labels=["Pat"], by=pat.id)
    make_person(ddb, "bob", [(other.id, "manager")])
    return {"jr": jr.id, "mom": mom, "known": "bob@x.com", "unknown": "ghost@x.com"}


def blank(value, email):
    return json.loads(json.dumps(value).replace(email, "<EMAIL>"))


def invite(client, email, **extra):
    r = client.post("/api/books/mom/members", json={"email": email, "display_name": "Zed", "role": "viewer", **extra})
    return r.status_code, blank(r.json(), email)


def pending(client, email):
    rows = client.get("/api/books/mom/members").json()["members"]
    return [blank(m, email) for m in rows if m.get("status") == "Invited" and m["email"] == email]


def same_row(rows):
    """The pending row without its counter: the id is a plain number for both and only the counter differs."""
    assert all(r["invite_id"].isdigit() for r in rows)
    return [{k: v for k, v in r.items() if k != "invite_id"} for r in rows]


def test_leak_first_invite_and_the_members_list_afterwards_match(twins, client):
    login(client, "jr")
    known, unknown = invite(client, twins["known"]), invite(client, twins["unknown"])
    assert known == unknown and known[0] == 201
    assert known[1] == {"member": {"email": "<EMAIL>", "role": "viewer", "status": "Invited"}, "invited": True}
    assert same_row(pending(client, twins["known"])) == same_row(pending(client, twins["unknown"]))
    rows = client.get("/api/books/mom/members").json()["members"]
    assert [m["username"] for m in rows if m.get("status") != "Invited"] == ["jr"]   # nobody was added


def test_leak_a_missing_or_bad_name_is_refused_the_same_way(twins, client):
    login(client, "jr")
    for extra in ({"display_name": None}, {"display_name": ""}, {"display_name": "   "}, {"display_name": "x" * 81}):
        a, b = invite(client, twins["known"], **extra), invite(client, twins["unknown"], **extra)
        assert a == b == (422, NAME_RULE)
    a = client.post("/api/books/mom/members", json={"email": twins["known"], "role": "viewer"})
    b = client.post("/api/books/mom/members", json={"email": twins["unknown"], "role": "viewer"})
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (422, NAME_RULE)


def test_leak_repeating_an_invite_replaces_the_pending_row_for_both(twins, client):
    login(client, "jr")
    for email in (twins["known"], twins["unknown"]):
        first, again = invite(client, email), invite(client, email, role="manager")
        assert first[0] == again[0] == 201
        assert again[1]["member"] == {"email": "<EMAIL>", "role": "manager", "status": "Invited"}
    assert same_row(pending(client, twins["known"])) == same_row(pending(client, twins["unknown"]))
    rows = client.get("/api/books/mom/members").json()["members"]
    assert len([m for m in rows if m.get("status") == "Invited"]) == 2


def test_leak_invite_ids_and_cancelling_look_alike(twins, client):
    login(client, "jr")
    outcomes = {}
    for key in ("known", "unknown"):
        email = twins[key]
        invite(client, email)
        invite_id = pending(client, email)[0]["invite_id"]
        assert invite_id.isdigit()
        first = client.delete(f"/api/books/mom/invites/{invite_id}")
        again = client.delete(f"/api/books/mom/invites/{invite_id}")
        outcomes[key] = (first.status_code, first.text, again.status_code, again.json())
        assert pending(client, email) == []
    assert outcomes["known"] == outcomes["unknown"] == (204, "", 404, {"error": "That invite isn't here."})


def test_leak_users_and_books_show_nothing_new_before_accepting(twins, client):
    login(client, "jr")
    users, books = client.get("/api/users").json(), client.get("/api/books").json()
    invite(client, twins["known"])
    invite(client, twins["unknown"])
    assert client.get("/api/users").json() == users
    assert client.get("/api/books").json() == books


def test_leak_a_stranger_token_looks_like_a_bad_one(twins, client, app):
    login(client, "jr")
    invite(client, twins["known"])
    invite(client, twins["unknown"])
    sent = {to: body for to, _s, body in app.state.mailer.sent}
    login(client, "pat")   # neither invitee
    answers = {(r.status_code, r.text) for r in (
        client.post("/api/invites/accept", json={"token": sent[twins["known"]].split("/invite?token=")[1].split()[0]}),
        client.post("/api/invites/accept", json={"token": sent[twins["unknown"]].split("/invite?token=")[1].split()[0]}),
        client.post("/api/invites/accept", json={"token": "nope"}))}
    assert len(answers) == 1 and next(iter(answers))[0] == 404


def test_leak_the_emails_have_the_same_subject_and_both_carry_the_accept_link(twins, client, app):
    login(client, "jr")
    invite(client, twins["known"])
    invite(client, twins["unknown"])
    sent = {to: (subject, body) for to, subject, body in app.state.mailer.sent}
    assert len(app.state.mailer.sent) == 2
    assert sent[twins["known"]][0] == sent[twins["unknown"]][0]
    assert all("/invite?token=" in body for _s, body in sent.values())


def test_leak_both_paths_do_the_same_work_so_timing_does_not_tell(twins, client, monkeypatch):
    """Password hashing (the slow part) runs once in each path; the username is only chosen when someone joins."""
    from steward.books import service
    calls = []
    real_hash = service.hash_password
    monkeypatch.setattr(service, "hash_password", lambda p: calls.append("hash") or real_hash(p))
    login(client, "jr")
    invite(client, twins["known"])
    known, calls[:] = sorted(calls), []
    invite(client, twins["unknown"])
    assert known == sorted(calls) == ["hash"]


def test_jr_adds_someone_from_a_book_he_manages_at_once(twins, client, ddb):
    sam = make_person(ddb, "sam", [(twins["mom"].id, "viewer")])
    mom2 = create_book(client.app.state.books, ddb, name="Dad", kind="parent", owner_labels=["Joe"], by=twins["jr"])
    login(client, "jr")
    r = client.post(f"/api/books/{mom2.slug}/members", json={"email": "sam@x.com", "role": "viewer"})
    assert r.status_code == 201 and r.json()["invited"] is False and r.json()["member"]["username"] == "sam"
    ddb.rollback()
    assert ddb.get(Membership, (sam.id, mom2.id)) is not None


def join(client, ddb, app, email):
    """A manager invites `email` to Mom; that person sets a password and accepts. Returns the person's row."""
    login(client, "jr")
    assert client.post("/api/books/mom/members", json={"email": email, "display_name": "Zed", "role": "viewer"}
                       ).status_code == 201
    body = next(b for to, _s, b in app.state.mailer.sent if to == email)
    reset_token = body.split("reset?token=")[1].split("&")[0]
    invite_token = body.split("/invite?token=")[1].split()[0]
    assert client.post("/api/auth/reset", json={"token": reset_token, "password": "a-new-pass-word"}).status_code == 200
    login(client, email, "a-new-pass-word")
    assert client.post("/api/invites/accept", json={"token": invite_token}).status_code == 200
    login(client, "jr")
    rows = client.get("/api/books/mom/members").json()["members"]
    ddb.rollback()
    return next(m for m in rows if m.get("status") != "Invited" and m["display_name"] == "Zed"
                and ddb.get(User, m["user_id"]).email == email)


@pytest.mark.parametrize("label", ["known", "unknown"])
def test_leak_the_next_person_to_join_gets_the_same_id_and_username_either_way(twins, client, ddb, app, label):
    """Inviting an unknown address must not use up a user id or the username its local part would give: someone
    who joins after the target was invited, with the local part ghost@x.com would take, must show nothing different
    (run once per kind of target, each on a fresh directory)."""
    a = join(client, ddb, app, "first@mine.com")
    client.post("/api/books/mom/members", json={"email": twins[label], "display_name": "Zed", "role": "viewer"})
    b = join(client, ddb, app, "ghost@mine.com")
    assert b["user_id"] not in (a["user_id"] + 1, a["user_id"] + 2)   # the target did not use up an id
    assert b["username"] == "ghost"                                   # nor its username
