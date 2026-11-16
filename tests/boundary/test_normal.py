"""The one canonical normaliser (Task 2.5, the Task 5 security review): plain, then fold, then casefold, then
collapsed separators, with a map back to the plain text so every layer computes and applies edits on one string."""
import random

import pytest

from steward_boundary.normal import fold, normal, plain, view

CYR_A, CYR_E, CYR_O = chr(0x430), chr(0x435), chr(0x41E)


def test_the_stages_in_order():
    assert plain("Mar\u200bgaret\u00a0 Ｅllis") == "Margaret  Ellis"        # NFKC, invisible format characters dropped
    assert fold("M" + CYR_A + "rg" + CYR_A + "r" + CYR_E + "t " + CYR_O + "rtiz") == "Margaret Ortiz"
    assert normal("  MARGARET\t\n Ellis  ") == "margaret ellis"            # casefold, separators collapsed, ends cut
    assert normal("Straße") == "strasse"                                   # casefold can lengthen a word
    assert normal("José Zoë") == "jose zoe"                                # accents go with the case


def test_fold_keeps_one_character_for_one():
    s = "M" + CYR_A + "rg\u2010\u2013\u2212\u0663\u0967x"
    assert fold(s) == "Marg---31x"                  # Arabic-Indic three, Devanagari one
    assert len(fold(s)) == len(s)


@pytest.mark.parametrize("variant", [
    "Margaret Ellis", "MARGARET ELLIS", "margaret   ellis", "Mar\u200bgaret Ellis", "M" + CYR_A + "rgaret Ellis",
    "Ｍａｒｇａｒｅｔ Ｅｌｌｉｓ", "Margaret\u2028Ellis", "Margaret\u00a0Ellis", " Margaret Ellis ",
])
def test_every_disguise_of_a_name_has_one_normal_form(variant):
    assert normal(variant) == "margaret ellis"


@pytest.mark.parametrize("variant", ["714-555-0102", "714\u2010555\u2011" + "0102", "\uff17\uff11\uff14-\uff15\uff15\uff15-\uff10\uff11\uff10\uff12",
                                     "\u0667\u0661\u0664-555-0102"])
def test_every_disguise_of_a_number_has_one_normal_form(variant):
    assert normal(variant) == "714-555-0102"


def test_offsets_map_back_to_the_plain_text():
    import re
    v = view("  Hi\u200b  Straße ﬁx ")
    assert v.plain == "  Hi  Straße fix " and v.norm == "hi strasse fix"
    for m in re.finditer(r"\S+(?: \S+)*", v.norm):
        ps, pe = v.to_plain(m.start(), m.end())
        assert normal(v.plain[ps:pe]) == m.group()
    assert v.plain[slice(*v.to_plain(3, 10))] == "Straße"
    assert v.to_norm(*v.to_plain(3, 10)) == (3, 10)


def test_the_split_view_breaks_camel_case_and_letters_against_digits():
    assert view("MargaretEllis Acct123456", split=True).norm == "margaret ellis acct 123456"
    assert view("MargaretEllis Acct123456").norm == "margaretellis acct123456"


def test_the_ascii_fast_path_agrees_with_the_full_path():
    """The view has a fast path for ASCII text; random strings must give the same view either way."""
    from steward_boundary import normal as N
    rng = random.Random(25)
    alphabet = "aZ09 \t\n-_.,$%•#@" + "é\u200bＡ" + CYR_A + "\u2028ß"
    for _ in range(3000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
        if plain(s).isascii():
            assert N._view_ascii(plain(s)) == N._view_full(plain(s), split=False), repr(s)
        v = view(s)
        assert len(v.src) == len(v.norm) + 1 and list(v.src) == sorted(v.src)
        assert all(0 <= i <= len(v.plain) for i in v.src)
