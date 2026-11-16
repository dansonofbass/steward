"""tests/personal_strings.py, the public scanner, on made-up terms only."""
import hashlib
import random
import re

import pytest

from tests import personal_strings as ps
from tests.personal_strings import load_terms, made_up, private_matcher


def _h(term):
    return hashlib.sha256(term.encode()).hexdigest()


def _terms_file(folder, *lines):
    path = folder / "terms.txt"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_tokens_find_a_term_in_words_emails_and_domains():
    m = made_up(term=("zorblax", None), domain=("zorblax.example", None), local=("pat.zorblax", None))
    assert m("Paid by Zorblax's card") == {"term"}
    assert m("zorblax_total = 1") == {"term"}
    assert m("const zorblaxTotal = cardZorblax") == {"term"}   # camelCase humps
    assert m("<Pat.Zorblax+a@Mail.Example>") == {"local", "term"}
    assert m("https://steward.zorblax.example/reset") == {"domain", "term"}
    assert m('"Steward" <noreply@zorblax.example>') == {"domain", "term"}
    assert not m("zorblaxes and unzorblax")                   # a whole-word term isn't found inside words
    assert m("zorblax.example.org") == {"term"}                # domain suffixes, not prefixes


def test_a_term_with_a_length_is_found_glued_to_other_text():
    m = made_up(glued=("zorblax", 7), whole=("quux", None))
    for text in ("TheZorblaxFamily", "jzorblax", "/home/zorblaxes/", "pzorblax2026", "ZORBLAX_KEY"):
        assert m(text) == {"glued"}, text
    assert not m("zorbla x") and not m("quuxes") and m("myQuux") == {"whole"}


# The single regex the dotted names were found with before: it took square time on a long run with no dot.
OLD_DOTTED = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")


def _names(text):
    return [name for chain in ps.CHAIN.findall(text) for name in ps._dotted(chain)]


def test_dotted_names_are_the_ones_the_old_regex_found():
    rng = random.Random(20261110)
    cases = ["a.b", "-a.b", "a-.b", "a.-b", "a.b-", "a.b-.c", "a..b.c", "a.b.", ".a.b", "x-a.b--c.d", "a.b c.d",
             "a-b.c-d.e--", "--a--.b", "a.b.-c.d", "1.2.3", "a@b.c", "a.b..c.d-.e.f"]
    cases += ["".join(rng.choice("ab-.  9") for _ in range(rng.randint(0, 30))) for _ in range(20000)]
    for text in cases:
        assert _names(text) == OLD_DOTTED.findall(text), text


@pytest.mark.parametrize("run", ["x" * 300_000, ("ab-" * 100_000), "x" * 299_998 + "-.y", "-" * 300_000])
def test_a_long_run_with_no_dot_is_read_whole(run):
    """No clock here (tests/perf/test_scanner_budgets.py holds the budget): read in linear time this takes a few
    hundredths of a second; the square-time regex took minutes on such a run, past the suite's two-minute ceiling."""
    assert not made_up(glued=("zorblax", 7), whole=("quux", None), host=("y.example", None))(run)


def test_whole_words_finds_a_glued_term_only_as_a_word():
    m = made_up(glued=("zorblax", 7), whole=("quux", None))
    words = m.whole_words()
    assert m("xzorblaxy") == {"glued"} and not words("xzorblaxy")
    assert words("a zorblax b") == {"glued"} and words("getZorblaxName") == {"glued"} and words("myQuux") == {"whole"}
    assert words("zorblax2026") == words("v2_zorblax") == {"glued"} and not words("zorblaxes2026")  # digits end a word
    assert not m.whole_words()("xzorblax2") and words is m.whole_words()


def test_whole_words_split_where_letters_turn_into_digits_not_back():
    """JR's ruling, Nov 10: a random key such as lucide's SVG path keys ("5" and four letters) is one word, so its
    letters never count as a term; a term followed by digits, an underscore or a hyphen still does."""
    words = made_up(whole=("abcd", None)).whole_words()
    assert not words('key:"5abcd"') and not words("v2abcd") and not words("x5abcd")
    assert words('key:"abcd2026"') == words("abcd_x") == words("abcd-x") == words("x5_abcd") == {"whole"}
    assert words("x9abcd2026") == set() and words("x9-abcd2026") == {"whole"}


def test_a_terms_file_gives_names_hashes_and_lengths(tmp_path):
    path = _terms_file(tmp_path, "# made-up terms", "", f"glued {_h('zorblax')} 7", f"whole {_h('quux')} -")
    assert load_terms(path) == {"glued": (_h("zorblax"), 7), "whole": (_h("quux"), None)}


@pytest.mark.parametrize("line", [
    "glued zorblax 7",                       # not a hash
    f"glued {_h('zorblax')}",                # no length
    f"glued {_h('zorblax')} 0",              # a length of 0
    f"glued {_h('zorblax').upper()} 7",      # upper-case hex
    f"glued {_h('zorblax')} seven",
])
def test_a_malformed_line_is_refused_with_its_line_number(tmp_path, line):
    with pytest.raises(ValueError, match=r"terms\.txt:2"):
        load_terms(_terms_file(tmp_path, "# header", line))


def test_a_name_listed_twice_or_a_file_with_no_terms_is_refused(tmp_path):
    with pytest.raises(ValueError, match="twice"):
        load_terms(_terms_file(tmp_path, f"a {_h('x')} -", f"a {_h('y')} -"))
    with pytest.raises(ValueError, match="no terms"):
        load_terms(_terms_file(tmp_path, "# nothing yet"))


def test_with_no_terms_file_the_private_matcher_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv(ps.TERMS_ENV, raising=False)
    monkeypatch.setattr(ps, "DEFAULT_TERMS", tmp_path / "absent.txt")
    assert private_matcher() is None


def test_the_variable_names_the_terms_file(monkeypatch, tmp_path):
    monkeypatch.setenv(ps.TERMS_ENV, str(_terms_file(tmp_path, f"glued {_h('zorblax')} 7")))
    assert private_matcher()("TheZorblaxFamily") == {"glued"}


def test_a_variable_naming_a_missing_file_fails_instead_of_skipping(monkeypatch, tmp_path):
    monkeypatch.setenv(ps.TERMS_ENV, str(tmp_path / "absent.txt"))
    with pytest.raises(FileNotFoundError, match=ps.TERMS_ENV):
        private_matcher()


def test_decode_text_tells_text_from_binary():
    assert ps.decode_text("héllo\n".encode()) == "héllo\n"
    assert ps.decode_text(b"\x89PNG\r\n\x1a\n\0\0") is None
    assert ps.decode_text(b"\xff\xfe not utf-8") is None
