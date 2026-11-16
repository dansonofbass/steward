import pytest

from steward_boundary.fingerprint import canon, digest, hashes_for, identifier_forms, scan, tokens

SALT = "0" * 32


def test_tokens_are_plain_casefolded_words_and_numbers():
    assert tokens("Margaret's  CVS #04411 (714) 555-0102 jr_age") == [
        "margaret", "s", "cvs", "04411", "714", "555", "0102", "jr", "age"]
    assert tokens("Mar\u200bgaret") == ["margaret"]
    assert tokens("M" + chr(0x430) + "rgaret") == ["margaret"]
    assert tokens("MargaretEllis Acct123456", split=True) == ["margaret", "ellis", "acct", "123456"]


def test_numbers_join_their_digits():
    assert canon(["714", "555", "0102"]) == "7145550102"
    assert canon(["way2save", "savings"]) == "way2save savings"


def test_identifier_forms():
    assert identifier_forms("Margaret Ellis", name=True) == {"margaret ellis", "margaret", "ellis"}
    assert identifier_forms("Robert (husband)", name=True) == {"robert husband", "robert"}
    assert identifier_forms("(714) 555-0102", name=False) == {"7145550102"}
    assert identifier_forms("Joint checking", name=False) == set()          # generic words only (ruling 4)
    assert identifier_forms("Bank of America", name=False) == {"bank of america"}
    assert identifier_forms("4417", name=False) == set()                     # 4 digits are allowed to leave
    long = identifier_forms("1428 Elm Street Apt 4B Brea", name=False)
    assert {"1428 elm street apt 4b", "elm street apt 4b brea"} <= long     # split forms ("4 b") join them
    assert "account 123456789" in identifier_forms("Account 123456789", name=False)
    assert "123456789" in identifier_forms("Account 123456789", name=False)  # the number alone too


def test_scan_finds_any_window_of_a_known_identifier():
    hashes = hashes_for([("Margaret Ellis", True), ("(714) 555-0102", False), ("dortiz@example.com", False)], SALT)
    assert scan([("$.a", "How is Person 1 doing?")], SALT, hashes) is None
    assert scan([("$.a", "fine"), ("$.b", "Is margaret's check in?")], SALT, hashes) == "$.b"
    assert scan([("$.c", "call 714-555-0102")], SALT, hashes) == "$.c"
    assert scan([("$.d", "write to DOrtiz@Example.com")], SALT, hashes) == "$.d"
    assert scan([("$.e", "Bank of the West")], SALT, hashes) is None


def test_scan_sees_through_the_disguises_the_reviews_named():
    hashes = hashes_for([("Margaret Ellis", True), ("(714) 555-0102", False), ("Account 123456789", False)], SALT)
    for text in ("MargaretEllis paid", "Margaret\u200bEllis", "MARGARET", "M" + chr(0x430) + "rg" + chr(0x430) + "ret",
                 "Ｍａｒｇａｒｅｔ", "7 1 4 5 5 5 0 1 0 2", "714\u2010555\u20110102", "\u0667\u0661\u0664 555 0102",
                 "the number 123456789", "acct#123456789"):
        assert scan([("$.q", text)], SALT, hashes) == "$.q", text
    assert scan([("$.q", "Margarita and Ellison")], SALT, hashes) is None


def test_the_salt_changes_every_hash():
    assert digest("a" * 32, "margaret") != digest("b" * 32, "margaret")


def test_a_known_number_spelled_out_in_words_is_found():
    hashes = hashes_for([("900-12-3456", False)], SALT)
    assert scan([("$.q", "my SSN is nine zero zero one two three four five six ok")], SALT, hashes) == "$.q"
    assert scan([("$.q", "Use Nine-Zero-Zero, one two three four five six")], SALT, hashes) == "$.q"
    assert scan([("$.q", "nine zero zero one two")], SALT, hashes) is None


@pytest.mark.parametrize("text", [
    # The scan reads a spelled number the way the text rule does (final review F2, F6): any separator or a spoken
    # joining word between the words, and a number half in words and half in digits.
    "nine zero zero / one two / three four five six",
    "nine zero zero and one two three four five six",
    "nine.zero.zero.one.two.three.four.five.six",
    "nine zero zero 12 3456",
    "SSN 900 one two three-four 56",
])
def test_a_known_number_spelled_with_any_separator_is_found(text):
    hashes = hashes_for([("900-12-3456", False)], SALT)
    assert scan([("$.q", text)], SALT, hashes) == "$.q"
