from steward_boundary.vocab import generic


def test_no_tokens_is_not_generic():
    assert generic([]) is False


def test_generic_words_and_short_numbers_are_generic():
    assert generic(["checking", "account", "1234"]) is True
    assert generic(["checking", "margaret"]) is False
    assert generic(["12345"]) is False
