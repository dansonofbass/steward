"""Spec 11.1-11.3 in the NAS suite: the sets are what the generator makes and fictional; the exact pass removes every
identifier the book knows; with the stand-in detectors, pattern identifiers and listed third-party names are gone;
and no more than 3% of the keep set changes."""
from datetime import date

import pytest
from sqlalchemy.orm import Session

from steward.advisor.aliases import Aliases
from steward.advisor.identifiers import load_identifiers
from steward.advisor.redact import exact_redact
from steward.books.service import add_membership, create_book
from steward.demo import seed, seed_people
from steward.demo_parent import seed_parent
from steward_boundary.text import outgoing_text
from steward_gateway.redact import redact
from steward_gateway.redact.patterns import PatternDetector, luhn
from tests.advisor.identities import PATTERNS, leaks, seed_household_identities, seed_parent_identities
from tests.advisor.pii_set.make_sets import ADDED, HERE, build_keep, build_pii, read_jsonl
from tests.gateway.fakes import THIRD_PARTY_NAMES, NameListDetector

PII = read_jsonl(HERE / "questions.jsonl")
KEEP = read_jsonl(HERE / "keep.jsonl")
TODAY = date(2026, 10, 19)


def test_the_committed_sets_are_what_the_generator_makes():
    assert PII == build_pii() and KEEP == build_keep()
    n = 400 + len(ADDED)            # rows added later are numbered after the first 400, which never move
    assert len(PII) == n and len(KEEP) == 200 and len({(r["book"], r["text"]) for r in PII}) == n


def test_every_awkward_case_is_there_and_every_span_is_right():
    variants = {r["variant"] for r in PII}
    assert {"lowercase", "lookalike", "spaced", "dashed", "zero_width", "spelled", "compact",
            "dob_1", "dob_2", "dob_3", "dob_4", "dob_5", "dob_6"} <= variants
    assert any("brother" in r["text"] for r in PII) and any("'s" in r["text"] for r in PII)
    assert any("Unit 4B" in r["text"] for r in PII) and any("Account Number" in r["text"] for r in PII)
    for r in PII:
        for s in r["spans"]:
            assert 0 <= s["start"] < s["end"] <= len(r["text"])


def test_the_sets_are_fictional():
    for v in PATTERNS["ssn"]:
        assert v.startswith("9")
    for v in PATTERNS["card"]:
        assert luhn("".join(c for c in v if c.isdigit()))
    for r in PII:
        for s in r["spans"]:
            if s["kind"] == "email":
                assert s["value"].endswith("@example.com")
            if s["kind"] == "phone":
                assert "555-01" in s["value"]


@pytest.fixture
def idents(books, ours, ddb):
    with Session(books.engine_for(ours)) as db:
        seed(db, years=2, seed=7)
    seed_people(ddb, ours.id)
    mom = create_book(books, ddb, name="Margaret Ellis", kind="parent", owner_labels=["Margaret", "Robert (husband)", "Joint"])
    jr = next(p for p in books.people(ours.id) if p.username == "alex")
    add_membership(ddb, jr.id, mom.id, "manager", by=None)
    ddb.commit()
    out = {}
    with Session(books.engine_for(ours)) as db:
        seed_household_identities(db, ddb)
        people = books.people(ours.id)
        out["household"] = load_identifiers(db, ours, people, books.directory, Aliases(db, ours, people), TODAY)
        db.commit()
    with Session(books.engine_for(mom)) as db:
        seed_parent(db, TODAY)
        seed_parent_identities(db)
        people = books.people(mom.id)
        out["parent"] = load_identifiers(db, mom, people, books.directory, Aliases(db, mom, people), TODAY)
        db.commit()
    return out


def test_the_exact_pass_removes_every_identifier_the_book_knows(idents):
    misses = []
    for r in PII:
        known = [s for s in r["spans"] if s["known"]]
        if not known:
            continue
        out, _ = exact_redact(r["text"], idents[r["book"]])
        misses += [(r["id"], s["kind"], out) for s in known if leaks(out, s["kind"], s["value"])]
    assert misses == []


def test_with_the_stand_in_models_no_pattern_or_listed_name_survives(idents):
    det = [PatternDetector(), NameListDetector()]
    misses = []
    for r in PII:
        for s in r["spans"]:
            if s["kind"] in PATTERNS or (s["kind"] == "name" and s["value"] in THIRD_PARTY_NAMES) or s["kind"] == "dob":
                first, _ = exact_redact(r["text"], idents[r["book"]])
                out = outgoing_text(redact(first, det).text)
                if leaks(out, s["kind"], s["value"]):
                    misses.append((r["id"], s["kind"], out))
    assert misses == []


SECRETS = [r for r in PII if r["category"] == "secret"]


def test_the_exact_pass_alone_removes_every_pin_password_and_code(idents):
    """Click-through feedback, 2026-10-25: "Here's my pin for my debit card 1111" went out as written."""
    assert len(SECRETS) == 7
    misses = []
    for r in SECRETS:
        out, chips = exact_redact(r["text"], idents[r["book"]])
        misses += [(r["id"], out) for s in r["spans"] if leaks(out, s["kind"], s["value"])]
        assert "[secret]" in {c["label"] for c in chips}, out
    assert misses == []


def test_the_gateway_alone_removes_every_pin_password_and_code():
    """The gateway holds without the NAS: its pattern detector reads the boundary's rule too."""
    det = [PatternDetector()]
    misses = [(r["id"], out) for r in SECRETS for s in r["spans"]
              if leaks(out := redact(r["text"], det).text, s["kind"], s["value"])]
    assert misses == []


def test_no_more_than_3_percent_of_the_keep_set_changes(idents):
    det = [PatternDetector(), NameListDetector()]
    changed = []
    for r in KEEP:
        first, _ = exact_redact(r["text"], idents["household"])
        if redact(first, det).text != r["text"]:
            changed.append((r["id"], r["text"]))
    assert len(changed) <= 6, changed


def test_leaks_sees_spelled_out_digits():
    from tests.advisor.identities import leaks
    assert leaks("My SSN is nine zero zero one two three four five six", "ssn", "900-12-3456")
    assert leaks("call seven one four, five five five, zero one zero two", "phone", "(714) 555-0102")
    assert not leaks("My SSN is [number]", "ssn", "900-12-3456")
    assert not leaks("I have two kids and three cars", "ssn", "900-12-3456")


def test_leaks_sees_spelled_digits_with_any_separator_and_half_in_digits():
    """The checker reads a spelled number the way the production rule does (final review F2, F4, F6)."""
    from tests.advisor.identities import leaks
    for text in ("nine zero zero / one two / three four five six", "nine zero zero and one two three four five six",
                 "nine.zero.zero.one.two.three.four.five.six", "nine zero zero 12 3456", "SSN 900 one two 3456"):
        assert leaks(text, "ssn", "900-12-3456"), text
    assert not leaks("nine zero zero and [number]", "ssn", "900-12-3456")
