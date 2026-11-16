"""Spec 2026-11-05, section 7, "Generic household labels": the two people's labels come from the members' display
names, falling back to Person 1 and Person 2; Person 1 is the book's earliest manager by directory id; the internal
keys jr and spouse never change. A household of one offers Person 1, Joint and Business only."""
import json
from datetime import date

from sqlalchemy.orm import Session
from typer.testing import CliRunner

from steward.api.business import adults
from steward.books.owners import HOUSEHOLD_OWNER_NAMES, owner_options
from steward.books.people import Person, household_labels, household_people
from steward.cli import app as cli_app
from steward.taxes.household import household_tax
from tests.advisor.helpers import call
from tests.factories import add_fact, login, make_person

runner = CliRunner()
SAM, ROBIN, ALEX = Person(2, "sam", "Sam"), Person(3, "robin", "Robin"), Person(4, "alex", "Alex")


def test_person_1_is_the_earliest_manager_not_the_username():
    viewer_first = (Person(1, "kid", "Kid", "viewer"), Person(5, "jr", "JR", "manager"), Person(3, "lee", "Lee", "manager"))
    assert household_people(viewer_first) == (viewer_first[2], viewer_first[0])
    assert household_people((ROBIN, SAM)) == (SAM, ROBIN)
    assert household_people((Person(7, "a", "A", "viewer"), Person(6, "b", "B", "viewer")))[0].id == 6   # no manager
    assert household_people(()) == (None, None)


def test_labels_are_display_names_with_plain_fallbacks():
    assert household_labels((SAM, ROBIN)) == {"jr": "Sam", "spouse": "Robin"}
    assert household_labels((SAM,)) == {"jr": "Sam", "spouse": "Person 2"}
    assert household_labels(()) == {"jr": "Person 1", "spouse": "Person 2"}


def test_the_keys_never_change():
    assert [o.key for o in HOUSEHOLD_OWNER_NAMES] == ["jr", "spouse", "joint", "business"]
    assert [o.label for o in HOUSEHOLD_OWNER_NAMES] == ["Person 1", "Person 2", "Joint", "Business"]


def test_a_household_of_one_offers_person_1_joint_and_business():
    shown = owner_options("household", HOUSEHOLD_OWNER_NAMES, (ALEX,))
    assert [(o.key, o.label) for o in shown] == [("jr", "Alex"), ("joint", "Joint"), ("business", "Business")]
    assert [o.key for o in owner_options("household", HOUSEHOLD_OWNER_NAMES, (ALEX, SAM))] == ["jr", "spouse", "joint", "business"]


def _alone(books, ours):
    with Session(books.directory) as ddb:
        u = make_person(ddb, "alex", [(ours.id, "manager")])
        return u.id


def test_one_person_s_book_and_me(client, books, ours):
    _alone(books, ours)
    login(client, "alex")
    book = next(b for b in client.get("/api/auth/me").json()["books"] if b["slug"] == "ours")
    assert [o["label"] for o in book["owners"]] == ["Alex", "Joint", "Business"]


def test_ask_never_mentions_a_second_person(books, ours, engine):
    uid = _alone(books, ours)
    out = call(engine, ours, books.people(ours.id), uid, "book_summary", {}, date(2026, 10, 13))
    assert out["error"] is None and "Person 2" not in json.dumps(out["content"])
    assert [p["alias"] for p in out["content"]["people"][:3]] == ["Person 1", "Joint", "Business"]


def test_taxes_and_business_treat_one_person_filing_single_as_single(db, books, ours):
    _alone(books, ours)
    for k, v in (("jr.dob", "1984-03-02"), ("state", "TX"), ("filing_status", "single")):
        add_fact(db, k, v)
    db.commit()
    household_tax(db, 2026, date(2026, 10, 13))      # no spouse birth date asked for: no NotReady
    assert adults(db) == [{"key": "jr", "name": "Alex"}]


def test_book_people_lists_who_is_person_1_and_changes_nothing(settings):
    assert runner.invoke(cli_app, ["init-key"]).exit_code == 0
    assert runner.invoke(cli_app, ["migrate"]).exit_code == 0
    for args in (["create-user", "lee", "lee@x.com", "Lee", "--password", "pw-one-two-3", "--role", "viewer"],
                 ["create-user", "jr", "jr@x.com", "JR", "--password", "pw-one-two-3"],
                 ["create-user", "sam", "sam@x.com", "Sam", "--password", "pw-one-two-3"]):
        assert runner.invoke(cli_app, args).exit_code == 0
    files = lambda: {n: (settings.data_dir / n).read_bytes() for n in ("directory.db", "directory.db-wal")   # noqa: E731
                     if (settings.data_dir / n).exists()}       # -shm is SQLite's read index; reading may touch it
    before = files()
    r = runner.invoke(cli_app, ["book", "people"])
    assert r.exit_code == 0
    assert r.output.splitlines() == ["Person 2\tLee\tlee\tviewer\tid 1", "Person 1\tJR\tjr\tmanager\tid 2",
                                     "member\tSam\tsam\tmanager\tid 3"]
    assert files() == before
    assert runner.invoke(cli_app, ["book", "people", "nope"]).output.strip() == "No book nope."
