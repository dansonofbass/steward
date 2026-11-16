"""The exact pass on the NAS (spec 4.3): the book's known names, accounts, institutions, payees, emails, phones,
numbers and dates of birth, matched however they're typed."""
from datetime import date

import pytest
from sqlalchemy.orm import Session

from steward.advisor.aliases import Aliases
from steward.advisor.identifiers import dob_forms, load_identifiers
from steward.advisor import redact as redact_module
from steward.advisor.redact import APPROVABLE_KINDS, Refused, exact_redact, issued_now, turn_hash_sets, turn_hashes
from steward.db.models import Fact
from steward.demo import seed, seed_people
from steward.demo_parent import seed_parent
from steward_boundary.fingerprint import digest, hashes_for
from steward_boundary.protocol import START, check_frame, issued

TODAY = date(2026, 10, 18)


@pytest.fixture
def idents(margaret, mdb, books):
    seed_parent(mdb, TODAY)
    people = books.people(margaret.id)
    out = load_identifiers(mdb, margaret, people, books.directory, Aliases(mdb, margaret, people), TODAY)
    mdb.commit()
    return out


def red(text, idents):
    out, chips = exact_redact(text, idents)
    for c in chips:
        assert out[c["start"]:c["end"]] == c["label"]
    return out


@pytest.mark.parametrize("text, want", [
    ("How is Margaret's pension doing?", "How is Parent's pension doing?"),
    ("is margaret ok", "is Parent ok"),
    ("Did Robert sign it?", "Did Person 2 sign it?"),
    ("Ask Linda Park, or just linda", "Ask [name], or just [name]"),
    ("email dortiz@example.com or call (714) 555-0102", "email [email] or call [phone]"),
    ("call 714.555.0148 or 7145550148", "call [phone] or [phone]"),
    ("policy EM-LTC-0047730", "policy [account number]"),
    ("Did Evergreen Mutual get paid?", "Did [institution] get paid?"),
    ("Is the Fidelity IRA up?", "Is the [institution] IRA up?"),
])
def test_known_identifiers_are_replaced(idents, text, want):
    assert red(text, idents) == want


def test_an_account_name_becomes_its_alias_but_generic_names_stay(idents):
    out = red("Is Way2Save savings bigger than Joint checking?", idents)
    assert out.startswith("Is Account ") and out.endswith(" bigger than Joint checking?")


def test_disguised_identifiers_are_still_replaced(idents):
    assert red("Mar\u200bgaret's checks", idents) == "Parent's checks"
    assert red("write DOrtiz@EXAMPLE.com", idents) == "write [email]"
    assert red("ring (714) 555 - 0102", idents) == "ring [phone]"
    assert red("ring ７１４-555-0102", idents) == "ring [phone]"
    assert red("policy em ltc 0047730", idents) == "policy [account number]"
    assert red("MARGARET ELLIS", idents) == "Parent"
    assert red("M" + chr(0x430) + "rgaret's checks", idents) == "Parent's checks"
    assert red("her card is four one one one four one one one", idents) == "her card is [number]"
    assert red("one two three", idents) == "one two three"


def test_amounts_years_and_ages_survive(idents):
    assert red("Did $1,234.56 arrive in 2025 when she was 81?", idents) == "Did $1,234.56 arrive in 2025 when she was 81?"


def test_unknown_long_numbers_are_masked_last(idents):
    out, chips = exact_redact("Is account 123456789 Margaret's?", idents)
    assert out == "Is account •6789 Parent's?"
    assert [c["label"] for c in chips] == ["•", "Parent"]


def test_dates_of_birth_in_six_formats(db, books, ours):
    db.add(Fact(key="jr.dob", value="1985-06-14", as_of=date(2026, 10, 1)))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    forms = dob_forms(date(1985, 6, 14))
    assert forms == ["06/14/1985", "6/14/85", "June 14, 1985", "14 June 1985", "1985-06-14", "Jun. 14 1985"]
    for f in forms:
        assert red(f"I was born {f}", idents) == "I was born [date of birth]", f


def test_the_turns_fingerprints_cover_names_and_numbers(idents):
    hashes = set(turn_hashes(idents, "3" * 32))
    for form in ("margaret", "linda park", "7145550102", "dortiz example com"):
        assert digest("3" * 32, form) in hashes, form
    assert digest("3" * 32, "checking") not in hashes


def test_a_surviving_identifier_refuses_the_turn(idents, monkeypatch):
    """The pass ends with a survivors check (Task 2.5): if the matcher misses a known identifier, nothing goes out."""
    assert red("Did Robert sign it?", idents) == "Did Person 2 sign it?"
    monkeypatch.setattr(redact_module, "find_known", lambda v, table: [])
    with pytest.raises(Refused) as e:
        exact_redact("Did Robert sign it?", idents)
    assert "Nothing was sent" in str(e.value)
    out, _ = exact_redact("call (714) 555-0102", idents)      # a number the matcher missed is still masked
    assert "555" not in out


def test_an_edit_that_would_overlap_an_issued_alias_refuses_instead_of_guessing(idents):
    """The 2.5 review's deferred case: punctuation and digits right after an alias unprotect it; the mask then
    reaches into the alias chip, and the turn stops plainly instead of shipping wrong offsets."""
    try:
        out, chips = exact_redact("Robert,1234 5678", idents)
    except Refused:
        return
    for c in chips:
        assert out[c["start"]:c["end"]] == c["label"]


def test_the_aliases_issued_now_go_in_the_start_frame(idents):
    out, chips = exact_redact("Did Robert get the email at dortiz@example.com on 2025-01-02?", idents)
    now = issued_now(chips)
    assert {"Person 2", "[email]"} <= set(now)
    assert now == sorted(set(now))
    # only tokens the NAS put in this text: nothing else the book has aliases for
    assert "Parent" not in now and "Joint" not in now
    frame = {"type": "start", "protocol": 1, "turn_id": "t_" + "a" * 16, "book_id": 1, "user_id": 1, "question": out,
             "context": {"today": "2026-10-18", "book_kind": "parent", "asker": "Person 3"}, "history": [],
             "fingerprints": {"salt": "3" * 32, "hashes": turn_hashes(idents, "3" * 32)[:5]}, "issued": now}
    assert check_frame(START, frame) == []
    assert set(now) <= issued(frame)
    # a look-alike the person typed is not in the issued set
    _, chips = exact_redact("Person 12 and [name] are typed", idents)
    assert issued_now(chips) == []


def household_identifiers(db, books, ours):
    seed(db, years=1, seed=7)
    with Session(books.directory) as ddb:
        seed_people(ddb, ours.id)
    people = books.people(ours.id)
    return load_identifiers(db, ours, people, books.directory, Aliases(db, ours, people, save=False), date(2026, 10, 20))


def test_payee_and_institution_hashes_travel_apart(db, books, ours):
    idents = household_identifiers(db, books, ours)
    rest, approvable = turn_hash_sets(idents, "4" * 32)
    assert set(rest) | set(approvable) == set(turn_hashes(idents, "4" * 32))
    assert not set(rest) & set(approvable)
    payee = next(i for i in idents if i.kind in APPROVABLE_KINDS)
    name = next(i for i in idents if i.kind == "name")
    assert hashes_for([(payee.text, payee.name)], "4" * 32) <= set(approvable) | set(rest)
    assert hashes_for([(name.text, True)], "4" * 32) <= set(rest)
    # Preflight ruling P8: a payee or institution whose forms aren't all shared with the rest travels as approvable.
    apart = next(i for i in idents if i.kind in APPROVABLE_KINDS
                 and not hashes_for([(i.text, i.name)], "4" * 32) <= set(rest))
    assert set(approvable) & hashes_for([(apart.text, apart.name)], "4" * 32)



def test_a_removed_kids_name_is_still_scrubbed_until_it_is_purged(db, books, ours):
    from datetime import datetime, timezone
    from steward.db.models import Child
    db.add(Child(label="Zoë", birth_year=2015, cost_level="private", monthly_contribution_cents=0,
                 removed_at=datetime(2026, 10, 13, tzinfo=timezone.utc)))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    assert "Zoë" not in red("Zoë starts college in 2033.", idents)
