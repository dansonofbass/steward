"""Known identifiers matched on the canonical normal form (Task 2.5): the exact pass's matcher and its post-check,
and the differential test that every layer gives the same verdict on every disguise of an identifier."""
import random

import pytest

from steward_boundary.aliases import protected_spans
from steward_boundary.fingerprint import hashes_for, scan
from steward_boundary.known import Known, find_known, known_digits, survivors
from steward_boundary.normal import normal, plain, view
from steward_boundary.spans import apply
from steward_boundary.text import is_question_safe, question_text

SALT = "1" * 32
CYR_A, CYR_E = chr(0x430), chr(0x435)
KNOWN = [
    Known("Margaret Ellis", "Parent", name=True),
    Known("Robert Ellis", "Person 2", name=True),
    Known("(714) 555-0102", "[phone]"),
    Known("dortiz@example.com", "[email]"),
    Known("Account 4029357733", "[account number]"),
    Known("900-12-3456", "[ssn]"),
]


def _redact(text: str) -> str:
    v = view(text)                         # edits from a view refer to its plain text
    return apply(v.plain, find_known(v, KNOWN))[0]


@pytest.mark.parametrize("text, want", [
    ("Is Margaret's check in?", "Is Parent's check in?"),
    ("MARGARET ELLIS and robert", "Parent and Person 2"),
    ("call (714) 555-0102 now", "call [phone] now"),
    ("write DOrtiz@Example.com", "write [email]"),
    ("ssn 900 12 3456", "ssn [ssn]"),
    ("the account 4029357733 and 4029357733", "the [account number] and [account number]"),
    ("Margarita and Ellison", "Margarita and Ellison"),
])
def test_find_known_replaces_each_identifier(text, want):
    assert _redact(text) == want


def test_the_post_check_finds_what_survived():
    assert survivors("Parent paid [phone]", KNOWN) == []
    assert survivors("M" + CYR_A + "rgaret paid", KNOWN) == [(0, 8)]
    assert survivors("Margaret\u200bpaid", KNOWN) == [(0, 8)]       # a zero-width space still parts two words
    with pytest.raises(ValueError):
        find_known("Margaret\u200bpaid", KNOWN)                     # a string must be plain; a view may be raw


def test_known_digits_are_the_long_numbers():
    assert known_digits(KNOWN) == frozenset({"7145550102", "4029357733", "900123456"})


# Every disguise the security reviews named, of a name and of a number.
NAME_VARIANTS = ["Margaret", "margaret", "MARGARET", "M" + CYR_A + "rg" + CYR_A + "r" + CYR_E + "t",
                 "Ｍａｒｇａｒｅｔ", "Mar\u200bgaret", "Margaret's", "MargaretEllis", "Margaret\u00adEllis",
                 "margaret   ellis", "Margaret\u2028Ellis", "Margarét"]
NUMBER_VARIANTS = ["(714) 555-0102", "714-555-0102", "714 555 0102", "7145550102", "714.555.0102",
                   "714\u2010555\u20110102", "\uff17\uff11\uff14\uff15\uff15\uff15\uff10\uff11\uff10\uff12", "\u0667\u0661\u0664 555 0102", "714,555,0102",
                   "7 1 4 5 5 5 0 1 0 2", "714\u2028555\u20280102"]


@pytest.mark.parametrize("variant", NAME_VARIANTS + NUMBER_VARIANTS)
def test_every_layer_gives_the_same_verdict_on_every_disguise(variant):
    text = f"Did {variant} pay?"
    hashes = hashes_for(((k.text, k.name) for k in KNOWN), SALT)
    assert scan([("$.q", text)], SALT, hashes) == "$.q"           # the gateway's fingerprints
    assert find_known(view(text), KNOWN)                           # the NAS's exact pass
    assert survivors(text, KNOWN)                                  # the exact pass's post-check
    assert survivors(_redact(text), KNOWN) == []                   # and nothing is left after it
    if any(c.isdigit() for c in variant):                          # the text rule masks every number form
        assert not is_question_safe(plain(text), known=known_digits(KNOWN))
        assert sum(c.isdigit() for c in question_text(text)) <= 4


def test_look_alike_aliases_and_brackets_from_input_are_text():
    """'Person 1' typed with a Cyrillic e, or a '[name]' the NAS didn't put there, protects nothing."""
    issued = frozenset({"Person 1234", "Person 5678"})
    assert is_question_safe("Person 1234 and Person 5678", issued=issued)
    text = "P" + CYR_E + "rson 1234 and P" + CYR_E + "rson 5678 [name]Margaret"
    assert protected_spans(text, issued) == []
    assert not is_question_safe(text, issued=issued)                   # their 8 digits count
    assert survivors(text, KNOWN)


def test_a_fake_alias_next_to_an_identifier_shields_nothing():
    issued = frozenset({"Person 1", "[name]"})
    for text in ("Person 1Margaret", "Person 1 Margaret Ellis", "[name]Margaret", "Margaret[name]"):
        assert _redact(text).count("Parent") == 1, text
        assert survivors(_redact(text), KNOWN) == []
    assert protected_spans("Person 1Margaret", issued) == []          # an alias run into a word isn't one


def test_the_layers_compose_on_one_plain_text_when_widths_change():
    """Full-width letters, a ligature and a zero-width space change the text's length when it is plained; every
    layer's edits come from one view and are applied to its plain text, so they line up and leave nothing behind."""
    from steward_boundary.text import dob_edits, question_edits
    raw = "Ｍａｒｇａｒｅｔ\u200b ﬁled ﬁrst: call 714 555 0102, born 03/14/1941, Person 1"
    v = view(raw)
    assert len(v.plain) != len(raw)
    edits = [*find_known(v, KNOWN), *dob_edits(v), *question_edits(v, issued={"Person 1"})]
    out = apply(v.plain, edits)[0]
    assert out == "Parent filed first: call [phone], born [date of birth], Person 1"
    assert survivors(out, KNOWN) == [] and is_question_safe(out, issued={"Person 1"})


def test_find_known_and_scan_agree_on_random_text():
    """The differential test: the exact pass and the fingerprints share one tokeniser and one set of forms, so on
    any string they reach the same verdict."""
    hashes = hashes_for(((k.text, k.name) for k in KNOWN), SALT)
    rng = random.Random(20261024)
    pieces = ["Margaret", "Ellis", "robert", "714", "555", "0102", "4029357733", "dortiz", "@", "example", ".com",
              "900", "12", "3456", " ", "-", "\u200b", "\u2010", CYR_A, "Mar", "garet", "x", "'s", "(", ")"]
    hits = 0
    for _ in range(3000):
        s = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 10)))
        a = bool(find_known(view(s), KNOWN))
        b = scan([("$", s)], SALT, hashes) is not None
        assert a == b, repr(s)
        assert normal(s) == normal(plain(s))
        hits += a
    assert hits > 300


# Public issue #2: a 2-letter name part, a name made of everyday words kept on purpose, an address typed short.
WIDER = [Known("Li Wei", "Person 3", name=True), Known("June Roth", "Child 1", name=True, everyday=True),
         Known("1234 North Elm Street Apt 5 Springfield IL 62704", "[address]", address=True)]


@pytest.mark.parametrize("text, want", [
    ("Did Li pay?", "Did Person 3 pay?"),
    ("li and LI", "Person 3 and Person 3"),
    ("Did June Roth's fund grow?", "Did Child 1's fund grow?"),
    ("Is the Roth IRA up in June?", "Is the Roth IRA up in June?"),
    ("We live at 1234 North Elm, and 1234 north elm street", "We live at [address], and [address]"),
    ("We moved 1234 boxes north", "We moved 1234 boxes north"),
    ("Is 1234 Elm St worth more?", "Is [address] St worth more?"),       # typed without its direction
    ("Go 1234 north today", "Go 1234 north today"),                      # a number and a direction alone
    ("Is it ok to go?", "Is it ok to go?"),
])
def test_the_wider_forms_replace_what_they_should_and_nothing_more(text, want):
    v = view(text)
    assert apply(v.plain, find_known(v, WIDER))[0] == want


def test_the_wider_forms_reach_the_same_verdict_in_the_exact_pass_and_the_fingerprints():
    hashes = hashes_for(((k.text, k.name, k.everyday, k.address) for k in WIDER), SALT)
    for s in ("li wei", "june roth", "1234 North Elm", "1234 north elm street apt", "1234 Elm", "1234 north", "Roth",
              "June",
              "1234", "north elm", "Al"):
        assert bool(find_known(view(s), WIDER)) == (scan([("$", s)], SALT, hashes) is not None), s
    # A 2-letter part is replaced in the question but never fingerprinted: a tool's ticker symbol can spell it.
    assert find_known(view("Li"), WIDER) and scan([("$", "Li")], SALT, hashes) is None
