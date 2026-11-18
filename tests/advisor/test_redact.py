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


def test_dates_of_birth_in_eight_formats(db, books, ours):
    db.add(Fact(key="jr.dob", value="1985-06-14", as_of=date(2026, 10, 1)))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    forms = dob_forms(date(1985, 6, 14))
    assert forms == ["06/14/1985", "6/14/85", "June 14, 1985", "14 June 1985", "1985-06-14", "Jun. 14 1985",
                     "6/14/1985", "06/14/85"]
    assert len(dob_forms(date(1985, 12, 25))) == 6           # no leading zero to add or drop
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


# --- Public issue #2: the four widenings of the exact pass ------------------------------------------------------------

def test_a_two_letter_name_part_is_matched_alone(db, books, ours):
    from steward.db.models import Child
    db.add(Child(label="Li Wei", birth_year=2015, cost_level="private", monthly_contribution_cents=0))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    out = red("How much did Li spend on groceries? And Wei?", idents)
    assert "Li " not in out and "Wei" not in out and out.count("Child ") == 2


def test_a_known_name_made_of_everyday_words_is_kept_and_matched_in_the_question(db, books, ours):
    """A child called August is replaced in a question, even where the word is the month: the exact pass can't tell
    them apart, and Privacy says so. Its fingerprint isn't sent, since the gateway's own context names the month."""
    from steward.db.models import Child
    db.add(Child(label="August", birth_year=2015, cost_level="private", monthly_contribution_cents=0))
    db.add(Child(label="June Roth", birth_year=2017, cost_level="private", monthly_contribution_cents=0))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    august = next(i for i in idents if i.text == "August")
    assert august.everyday and august.kind == "name"
    assert "August" not in red("Is August's tuition due?", idents)
    assert "June Roth" not in red("Did June Roth's fund grow?", idents)
    assert red("Is the Roth IRA up?", idents) == "Is the Roth IRA up?"      # a part that is an everyday word stays
    rest = set(turn_hashes(idents, "4" * 32))
    assert digest("4" * 32, "august") not in rest                        # "Today is Monday, August 3" never stops
    assert digest("4" * 32, "june roth") in rest


def test_a_held_street_address_typed_short_is_matched(db, books, ours):
    import json
    from steward.db.models import InventoryItem
    db.add(InventoryItem(kind="insurance", name="Homeowners", owner="joint", status="confirmed", details=json.dumps(
        {"address": "1234 North Elm Street Apt 5 Springfield IL 62704"})))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    for typed in ("We live at 1234 North Elm Street, can we refinance?", "Is 1234 North Elm worth more?",
                  "We live at 1234 north elm st"):
        assert "Elm" not in red(typed, idents).title(), typed
    assert red("We moved 1234 boxes", idents) == "We moved 1234 boxes"


def test_names_steward_held_but_never_loaded_are_replaced(db, books, ours):
    """Reimbursers, set-asides, merchant nicknames, institutions added by hand and payees last seen more than 400
    days ago."""
    from datetime import date as d
    from steward.db.models import (Account, AccountType, CategorySource, Institution, MerchantRule, Reimburser,
                                   SetAside, Source, Transaction)
    inst = Institution(name="Ridgeway Credit Cooperative", source=Source.manual)
    db.add(inst)
    db.flush()
    acct = Account(name="Plain", type=AccountType.checking, institution_id=inst.id, owner="joint", source=Source.manual)
    db.add(acct)
    db.add(Reimburser(name="Quillfeather Labs"))
    db.add(SetAside(name="Grandma Odette's care", kind="one_off", amount_cents=100_00, due_year=2027, due_month=3,
                    first_month=d(2026, 11, 1)))
    db.add(MerchantRule(pattern="SQ ZEPHYRA", merchant="Zephyra", category="dining", source=CategorySource.correction,
                        nickname="Tobiah's lunches"))
    db.flush()
    db.add(Transaction(account_id=acct.id, posted_at=d(2026, 10, 1), amount_cents=-500, raw_description="POS 1",
                       merchant="Corner Shop", nickname="Nadiya bakery", category="dining",
                       category_source=CategorySource.none))
    db.add(Transaction(account_id=acct.id, posted_at=d(2023, 1, 5), amount_cents=-900, raw_description="ZELLE TO "
                       "BARTHOLOMEW KADE", category="gifts", category_source=CategorySource.none))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    for typed, gone in (("Did Quillfeather Labs pay us back?", "Quillfeather"),
                        ("How is Grandma Odette's care set-aside?", "Odette"),
                        ("How much on Tobiah's lunches?", "Tobiah"),
                        ("What did Nadiya bakery cost?", "Nadiya"),
                        ("Is Ridgeway Credit Cooperative safe?", "Ridgeway"),
                        ("When did we last pay Bartholomew Kade?", "Bartholomew")):
        assert gone not in red(typed, idents), typed


def _plain_account(db):
    from steward.db.models import Account, AccountType, Institution, Source
    inst = Institution(name="Plain", source=Source.manual)
    db.add(inst)
    db.flush()
    acct = Account(name="Plain", type=AccountType.checking, institution_id=inst.id, owner="joint", source=Source.manual)
    db.add(acct)
    db.flush()
    return acct


def test_a_set_aside_or_nickname_named_for_a_payee_leaves_the_payee_its_alias(db, books, ours):
    """Review round 1 of public issue #2: a set-aside or nickname is often a store's name. The store keeps its payee
    alias in the question, and its approvable hash, so the manager can still approve its rows."""
    from datetime import date as d
    from steward.db.models import AdvisorAlias, CategorySource, MerchantRule, SetAside, Transaction
    acct = _plain_account(db)
    db.add(SetAside(name="Costco", kind="one_off", amount_cents=100_00, due_year=2027, due_month=3,
                    first_month=d(2026, 11, 1)))
    db.add(MerchantRule(pattern="COSTCO", merchant="Costco", category="groceries", source=CategorySource.correction,
                        nickname="Costco"))
    db.add(Transaction(account_id=acct.id, posted_at=d(2026, 10, 1), amount_cents=-500, raw_description="COSTCO WHSE "
                       "#1234 BREA CA", merchant="Costco", nickname="costco", category="groceries",
                       category_source=CategorySource.none))
    db.add(AdvisorAlias(kind="payee", target="COSTCO", alias="Payee 3"))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    assert red("How much at Costco?", idents) == "How much at Payee 3?"
    assert {i.kind for i in idents if i.text.lower() == "costco"} == {"payee"}
    rest, approvable = turn_hash_sets(idents, "4" * 32)
    assert digest("4" * 32, "costco") in approvable and digest("4" * 32, "costco") not in rest


def test_a_book_with_more_payees_than_the_budget_still_starts_a_turn_and_keeps_the_newest(db, books, ours,
                                                                                         monkeypatch):
    """The START frame takes at most 200,000 hashes per set. Payees load newest first, and `approvable` stops before
    its budget, so a long history never makes every turn a bad request."""
    from datetime import date as d, timedelta
    from steward.db.models import CategorySource, Transaction
    acct = _plain_account(db)
    day = d(2020, 1, 1)
    db.add_all([Transaction(account_id=acct.id, posted_at=day + timedelta(days=n), amount_cents=-100,
                            raw_description="QUOLL " + "".join(chr(65 + int(c)) for c in f"{n:03d}") + " STORE",
                            category="dining", category_source=CategorySource.none) for n in range(60)])
    db.commit()
    monkeypatch.setattr(redact_module, "APPROVABLE_BUDGET", 20)
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    rest, approvable = turn_hash_sets(idents, "4" * 32)
    assert 0 < len(approvable) <= 20
    payees = [i for i in idents if i.kind == "payee"]
    assert set(hashes_for([(payees[0].text, False)], "4" * 32)) <= set(approvable)       # the newest is kept
    assert not set(hashes_for([(payees[-1].text, False)], "4" * 32)) & set(approvable)   # the oldest goes without
    assert (payees[0].text.lower(), payees[-1].text.lower()) == ("quoll afj store", "quoll aaa store")
    frame = {"type": "start", "protocol": 1, "turn_id": "t_" + "a" * 16, "book_id": 1, "user_id": 1,
             "question": "How much on dining?", "context": {"today": "2026-10-18", "book_kind": "household",
                                                            "asker": "Person 1"}, "history": [],
             "fingerprints": {"salt": "4" * 32, "hashes": rest, "approvable": approvable}, "issued": []}
    assert check_frame(START, frame) == []


# --- PR E review round 4 (Argon's identifier findings, each reproduced first) -----------------------------------------

def test_dates_of_birth_typed_with_and_without_leading_zeros(db, books, ours):
    """5/4/1985 and 05/04/85 are as usual as 05/04/1985, so each is replaced, with no birth word
    beside them too (the rules replace a date next to "born" whatever its form)."""
    db.add(Fact(key="jr.dob", value="1985-05-04", as_of=date(2026, 10, 1)))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    for typed in ("5/4/1985", "05/04/85", "05/04/1985"):      # "5/4/85" has 4 digits, which may leave (P5)
        assert red(f"What happened on {typed}?", idents) == "What happened on [date of birth]?", typed


def test_a_username_that_is_an_everyday_word_is_still_replaced(db, books, ours):
    """A member's username is matched like their name (Privacy: "each member's username"), so one that is a month is
    kept as an everyday name rather than dropped."""
    from steward.books.people import Person
    people = (Person(41, "august", "AJ", "manager"),)
    idents = load_identifiers(db, ours, people, books.directory, Aliases(db, ours, people), date(2026, 10, 13))
    assert "august" not in red("Show august's transactions", idents)


def test_every_spelling_of_a_payee_is_replaced_not_only_the_newest(db, books, ours):
    """Two rows with one payee key and different merchant names: both names are loaded, not only the newest row's."""
    from datetime import date as d
    from steward.db.models import CategorySource, Transaction
    acct = _plain_account(db)
    db.add(Transaction(account_id=acct.id, posted_at=d(2026, 10, 1), amount_cents=-500,
                       raw_description="ZELLE PAYMENT TO PRIYA NAIR", category="gifts",
                       category_source=CategorySource.none))
    db.add(Transaction(account_id=acct.id, posted_at=d(2026, 9, 1), amount_cents=-500,
                       raw_description="ZELLE PAYMENT TO PRIYA NAIR", merchant="Priyanka Sethi Nair", category="gifts",
                       category_source=CategorySource.none))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    assert "Sethi" not in red("What did I send to Priyanka Sethi Nair?", idents)
    assert "Priya Nair" not in red("What did I send to Priya Nair?", idents)


def test_a_payee_is_matched_whole_and_a_contact_by_its_parts(db, books, ours):
    """Argon B1, B2 and B4, checked and kept as designed: a payee, a set-aside or a nickname goes to the exact pass
    whole (its parts are often a store's words: "Acme", "Holdings", "Water"), so "Priya" alone stays for the gateway,
    which Privacy lists as a miss. A set-aside with a payee's name is still replaced, as the payee. Saved as a contact,
    the person's name is matched by its parts too, as Privacy says."""
    import json
    from datetime import date as d
    from steward.db.models import CategorySource, InventoryItem, SetAside, Transaction
    acct = _plain_account(db)
    db.add(Transaction(account_id=acct.id, posted_at=d(2026, 10, 1), amount_cents=-500,
                       raw_description="ZELLE PAYMENT TO PRIYA NAIR", category="gifts",
                       category_source=CategorySource.none))
    db.add(SetAside(name="Priya Nair", kind="one_off", amount_cents=100_00, due_year=2027, due_month=3,
                    first_month=d(2026, 11, 1)))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    assert "Priya" not in red("Did Priya Nair pay us back?", idents)
    assert red("Did I Zelle Priya?", idents) == "Did I Zelle Priya?"
    db.add(InventoryItem(kind="contact", name="Priya Nair", owner="joint", status="confirmed", details=json.dumps({})))
    db.commit()
    idents = load_identifiers(db, ours, (), books.directory, Aliases(db, ours, ()), date(2026, 10, 13))
    assert "Priya" not in red("Did I Zelle Priya?", idents)
