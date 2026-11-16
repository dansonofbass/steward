import json
import re

from steward.inventory.suggester import DATA, patterns, payer

RAW = json.loads(DATA.read_text())
LISTS = ("noise", "insurers", "insurer_words", "premium_words", "bank_words", "institutions", "brokerages",
         "interest_words", "dividend_words", "transfer_words", "acronyms", "generic")


def test_every_list_is_uppercase_without_repeats():
    for name in LISTS:
        words = RAW[name]
        assert words, name
        assert all(w == w.upper() and w.strip() == w for w in words), name
        assert len(set(words)) == len(words), name
    for source, words in RAW["income_words"].items():
        assert source in ("pension", "annuity", "rmd") and words
    assert {t["type"] for t in RAW["insurance_types"]} <= {"medicare", "supplement", "part_d", "long_term_care",
                                                           "life", "home", "auto"}


def test_the_patterns_compile_and_each_abbreviation_expands():
    p = patterns()
    for sp in RAW["special_payers"]:
        re.compile(sp["pattern"])
    for short, long in RAW["abbreviations"].items():
        got = payer(f"ACME {short} 0001")
        assert got is None or long.split()[0] in got[0] or long.split()[0] in p.noise, short


def test_brokerages_are_institutions():
    assert set(RAW["brokerages"]) <= set(RAW["institutions"])
