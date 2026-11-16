from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from steward import clock
from steward.app import create_app
from steward.books.registry import household_book_id
from steward.books.service import add_membership, create_book, welcome_kind
from steward.cli import app
from steward.db.directory_models import Book, Membership
from steward.db.models import CategorySource
from steward.mail import FakeMailer
from tests.factories import login, make_account, make_person, make_txn


def _m(ddb, user_id, book_id):
    return ddb.get(Membership, (user_id, book_id))


def test_the_household_maker_gets_the_first_run_and_anyone_else_the_partner_welcome(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])                 # created_by NULL, as steward setup makes it
    sam = make_person(ddb, "sam")
    add_membership(ddb, sam.id, ours.id, "manager", by=jr.id)            # added by jr
    vee = make_person(ddb, "vee", [(ours.id, "viewer")])
    ddb.commit()
    hh, book = household_book_id(ddb), ddb.get(Book, ours.id)
    assert welcome_kind(book, _m(ddb, jr.id, ours.id), hh, jr.id) == "first_run"
    assert welcome_kind(book, _m(ddb, sam.id, ours.id), hh, sam.id) == "partner"
    assert welcome_kind(book, _m(ddb, vee.id, ours.id), hh, vee.id) == "partner"   # a viewer never runs setup


def test_a_mark_ends_it_unless_ignored_for_a_replay(ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    m = _m(ddb, jr.id, ours.id)
    m.welcome_seen_at = m.created_at
    ddb.commit()
    hh, book = household_book_id(ddb), ddb.get(Book, ours.id)
    assert welcome_kind(book, m, hh, jr.id) is None
    assert welcome_kind(book, m, hh, jr.id, ignore_mark=True) == "first_run"


def test_a_legacy_second_household_book_never_plays_the_first_run(books, ddb, ours):
    older = create_book(books, ddb, name="Older", kind="parent", owner_labels=["Lee"])
    ddb.get(Book, older.id).kind = "household"
    lee = make_person(ddb, "lee", [(older.id, "manager")])
    ddb.commit()
    assert welcome_kind(ddb.get(Book, older.id), _m(ddb, lee.id, older.id), household_book_id(ddb), lee.id) == "partner"


def test_a_sample_plays_no_welcome(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    s = create_book(books, ddb, name="Sample", kind="household", by=jr.id, sample_of=jr.id)
    m = _m(ddb, jr.id, s.id)
    m.welcome_seen_at = None
    ddb.commit()
    assert welcome_kind(ddb.get(Book, s.id), m, household_book_id(ddb), jr.id, ignore_mark=True) is None


def test_whoever_makes_or_restores_a_book_is_welcomed_and_an_invite_is_not(books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"], by=jr.id)
    assert _m(ddb, jr.id, mom.id).welcome_seen_at is not None
    assert _m(ddb, jr.id, ours.id).welcome_seen_at is None             # steward setup's membership waits for the first run
    m = add_membership(ddb, make_person(ddb, "pat").id, mom.id, "viewer", by=jr.id)
    assert m.welcome_seen_at is None
    assert add_membership(ddb, make_person(ddb, "kit").id, mom.id, "viewer", by=None, welcomed=True).welcome_seen_at


def test_steward_create_user_welcomes_the_person_it_makes(settings):
    runner = CliRunner()
    assert runner.invoke(app, ["init-key"]).exit_code == 0
    assert runner.invoke(app, ["migrate"]).exit_code == 0
    r = runner.invoke(app, ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"])
    assert r.exit_code == 0, r.output
    from steward.books.registry import open_books
    reg = open_books(settings)
    try:
        with Session(reg.directory) as ddb:
            rows = ddb.scalars(select(Membership)).all()
            assert rows and all(m.welcome_seen_at is not None for m in rows)
    finally:
        reg.dispose()


def _books_by_slug(client):
    return {b["slug"]: b for b in client.get("/api/auth/me").json()["books"]}


def test_me_tells_each_book_its_welcome_sample_and_install(client, books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    add_membership(ddb, jr.id, mom.id, "viewer", by=None)
    ddb.commit()
    login(client, "jr")
    b = _books_by_slug(client)
    assert (b["ours"]["welcome"], b["ours"]["sample"], b["ours"]["install"]) == ("first_run", False, True)
    assert (b["mom"]["welcome"], b["mom"]["install"]) == ("partner", False)


def test_finish_or_skip_marks_it_once_and_marks_profile_seen(client, books, ddb, ours, fake_clock):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    assert client.post("/api/books/ours/welcome").json() == {"welcome": None}
    first = ddb.scalar(select(Membership.welcome_seen_at))
    fake_clock.advance(timedelta(minutes=5))
    client.post("/api/books/ours/welcome")
    ddb.rollback()
    assert ddb.scalar(select(Membership.welcome_seen_at)) == first             # once per book
    assert _books_by_slug(client)["ours"]["welcome"] is None
    assert _books_by_slug(client)["ours"]["profile"]["seen"] is True             # Go to Home lands on Home (plan D6)


def test_a_viewer_marks_their_own_welcome(client, books, ddb):
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    make_person(ddb, "vee", [(mom.id, "viewer")])
    login(client, "vee")
    assert client.post("/api/books/mom/welcome").status_code == 200
    assert _books_by_slug(client)["mom"]["welcome"] is None


def test_the_welcome_state_says_what_to_play_and_where_to_resume(client, books, ddb, ours, db):
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    s = client.get("/api/b/ours/welcome").json()
    assert (s["kind"], s["seen"], s["step"], s["money"]["in"]) == ("first_run", False, "money", False)
    t = make_txn(db, make_account(db, "Checking"), date(2026, 10, 29), -1200, "COFFEE")   # uncategorized: it waits
    assert client.get("/api/b/ours/welcome").json()["step"] == "sort"
    t.category, t.category_source, t.reviewed_at = "groceries", CategorySource.rule, clock.now()
    db.commit()
    assert client.get("/api/b/ours/welcome").json()["step"] == "extras"
    client.post("/api/books/ours/welcome")
    assert client.get("/api/b/ours/welcome").json()["kind"] == "first_run"        # Help's replay still knows


def test_a_partner_hears_who_invited_them_and_the_parent_book_wording(client, books, ddb, ours):
    jr = make_person(ddb, "jr", [(ours.id, "manager")])
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"], by=jr.id)
    pat = make_person(ddb, "pat")
    add_membership(ddb, pat.id, mom.id, "viewer", by=jr.id)
    ddb.commit()
    login(client, "pat")
    s = client.get("/api/b/mom/welcome").json()
    assert (s["kind"], s["inviter"], s["zone_needed"]) == ("partner", "Jr", False)
    login(client, "jr")                                        # the book's maker, replaying from Help
    assert client.get("/api/b/mom/welcome").json()["inviter"] is None


def test_a_partner_with_no_inviter_reads_your_household(client, books, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])                              # created_by NULL, unmarked
    login(client, "vee")
    s = client.get("/api/b/ours/welcome").json()
    assert (s["kind"], s["inviter"]) == ("partner", None)


def test_the_time_zone_is_asked_only_when_nothing_sets_it(settings, books, ddb, ours, monkeypatch):
    make_person(ddb, "jr", [(ours.id, "manager")])
    monkeypatch.delenv("STEWARD_TIMEZONE", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    from steward.settings import Settings
    with TestClient(create_app(Settings(_env_file=None), books), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "jr")
        assert c.get("/api/b/ours/welcome").json()["zone_needed"] is True
    with TestClient(create_app(settings, books), base_url="https://nas.tail1234.ts.net") as c:   # STEWARD_TIMEZONE set
        login(c, "jr")
        assert c.get("/api/b/ours/welcome").json()["zone_needed"] is False


def test_a_sample_plays_nothing(client, books, ddb, ours, monkeypatch):
    monkeypatch.setattr("steward.books.sample.YEARS", 1)
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(client, "jr")
    slug = client.post("/api/books/sample").json()["book"]["slug"]
    assert _books_by_slug(client)[slug]["welcome"] is None and _books_by_slug(client)[slug]["sample"] is True
    assert client.get(f"/api/b/{slug}/welcome").json()["kind"] is None


@pytest.fixture
def mail_off(settings, books):
    app = create_app(settings, books, mailer=FakeMailer(configured=False))
    with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
        yield c, app


def test_with_email_off_an_install_manager_gets_the_text_to_send_and_nothing_is_sent(mail_off, ddb, ours, caplog):
    c, app = mail_off
    make_person(ddb, "jr", [(ours.id, "manager")])
    login(c, "jr")
    r = c.post("/api/books/ours/members", json={"email": "new@example.com", "display_name": "Sam", "role": "manager"})
    body = r.json()["send_yourself"]
    assert "/invite?token=" in body and "/reset?token=" in body and app.state.mailer.sent == []
    token = body.split("/invite?token=")[1].split()[0]
    assert token not in caplog.text


def test_with_email_off_a_parent_only_managers_answers_still_match(mail_off, books, ddb, ours):
    c, app = mail_off
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    make_person(ddb, "momsmgr", [(mom.id, "manager")])
    make_person(ddb, "stranger")
    login(c, "momsmgr")
    a = c.post("/api/books/mom/members", json={"email": "stranger@x.com", "display_name": "S", "role": "viewer"})
    b = c.post("/api/books/mom/members", json={"email": "brand.new@x.com", "display_name": "S", "role": "viewer"})
    assert a.json() == {"member": {"email": "stranger@x.com", "role": "viewer", "status": "Invited"}, "invited": True,
                        "mail_off": True}
    assert {**b.json(), "member": None} == {**a.json(), "member": None}


def test_with_email_off_adding_someone_from_another_managed_book_is_not_an_unsent_invite(mail_off, books, ddb, ours):
    """They are added at once; neither the install manager's copy-it-yourself sheet nor the email-off line shows."""
    c, app = mail_off
    mom = create_book(books, ddb, name="Mom", kind="parent", owner_labels=["Margaret"])
    dad = create_book(books, ddb, name="Dad", kind="parent", owner_labels=["Doug"])
    make_person(ddb, "momsmgr", [(mom.id, "manager"), (dad.id, "manager")])
    kit = make_person(ddb, "kit", [(dad.id, "viewer")])
    login(c, "momsmgr")
    r = c.post("/api/books/mom/members", json={"email": "kit@x.com", "role": "viewer"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invited"] is False and "send_yourself" not in body and "mail_off" not in body, body
    ddb.expire_all()
    assert _m(ddb, kit.id, mom.id) is not None and app.state.mailer.sent == []
