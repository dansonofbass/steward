import pytest

from steward_boundary.aliases import (
    ALIAS_TOKEN_RE, BRACKETS, is_alias, number_of, protected_spans,
)

CYR_E = chr(0x435)


def test_the_alias_grammar():
    for a in ("Person 1", "Person 2", "Child 3", "Account 12", "Payee 9999", "Joint", "Business", "Parent"):
        assert is_alias(a), a
    for a in ("Person 0", "Person 10000", "person 1", "Account", "Account 1a", "Robert", "Joint ", "Payee 01", 7):
        assert not is_alias(a), a


def test_number_of():
    assert number_of("Account 12") == ("Account", 12)
    assert number_of("Joint") is None and number_of("Margaret") is None


def test_alias_tokens_are_found_whole_in_text():
    text = "Account 3 and Account 123 paid Person 1, not Account 12345 or Accounts 4."
    assert [m.group(0) for m in ALIAS_TOKEN_RE.finditer(text)] == ["Account 3", "Account 123", "Person 1"]


def test_protected_spans_cover_only_what_the_nas_issued():
    text = "Did [name] pay Payee 4 from Joint, or Person 12 and [phone]?"
    got = [text[s:e] for s, e in protected_spans(text, {"[name]", "Payee 4", "Joint"})]
    assert got == ["[name]", "Payee 4", "Joint"]
    assert protected_spans(text, set()) == []


def test_a_look_alike_of_an_issued_alias_is_not_protected():
    issued = {"Person 1", "[name]"}
    assert protected_spans("P" + CYR_E + "rson 1 paid", issued) == []
    assert protected_spans("person 1 paid", issued) == []
    assert protected_spans("[Name] paid", issued) == []
    assert protected_spans("Person 1x paid", issued) == []


def test_an_issued_alias_followed_by_more_digits_is_not_protected():
    """'Account 1,234,567' must not keep its first digit as an alias and the rest as small numbers."""
    issued = {"Account 1"}
    for text in ("Account 1,234,567", "Account 1;234", "Account 1.5", "Account 1-800"):
        assert protected_spans(text, issued) == [], text
    assert protected_spans("Account 1, then", issued) == [(0, 9)]


def test_issued_tokens_must_be_aliases_or_brackets():
    with pytest.raises(ValueError):
        protected_spans("Margaret paid", {"Margaret"})


def test_brackets_are_plain_words():
    assert all(b.startswith("[") and b.endswith("]") and b == b.lower() for b in BRACKETS)
