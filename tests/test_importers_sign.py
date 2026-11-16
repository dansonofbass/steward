"""The sign question (spec P10, P11): the format, split columns and a Type column say it; else a running balance (90%
of the computable pairs, either file order); else payment or deposit words (3 rows, all one sign, and 80% of the rest
the other way); otherwise ask. The lean is the share of positive amounts."""
from datetime import date

import pytest

from steward.services.importers.decode import decode
from steward.services.importers.layouts import identify, layout_key, parse, read_table, remembered
from steward.services.importers.sign import by_balance, by_words, file_sign, lean
from tests.bank_files import read

TODAY = date(2026, 10, 30)


def _sign(name, mine=None):
    t = read_table(decode(read(name)))
    lay = identify(t, layout_key(t), mine)
    return file_sign(lay, parse(t, lay, TODAY))


@pytest.mark.parametrize("name,credit,bank", [
    ("amex-basic.csv", ("negate", "positive"), (None, "positive")),
    ("card-ambiguous.csv", (None, "positive"), (None, "positive")),
    ("boa-checking.csv", ("negate", "negative"), ("as_is", "negative")),
    ("wise-dmy.csv", ("negate", "negative"), ("as_is", "negative")),
    ("wells-fargo.csv", (None, "negative"), (None, "negative")),
    ("chase-card.csv", ("as_is", None), ("as_is", None)),
    ("discover.csv", ("negate", None), ("negate", None)),
    ("first-cu.csv", ("as_is", None), ("as_is", None)),
])
def test_each_fixtures_evidence(name, credit, bank):
    s = _sign(name)
    assert ((s["credit"]["verdict"], s["credit"]["lean"]), (s["bank"]["verdict"], s["bank"]["lean"])) == (credit, bank)


def test_a_card_month_with_no_payment_rows_is_asked():
    """Review focus 2: purchases positive with no payment to tell by: nothing is pre-selected."""
    assert by_words([650, 8412, 1549, 2280], ["COFFEE", "GROCERY", "STREAMFLIX", "PHARMACY"], card=True) is None


def test_two_payment_rows_arent_enough_and_three_are():
    others = [100 + i for i in range(8)]
    assert by_words([-500, -600] + others, ["AUTOPAY PAYMENT"] * 2 + ["SHOP"] * 8, card=True) is None
    assert by_words([-500, -600, -700] + others, ["AUTOPAY PAYMENT"] * 3 + ["SHOP"] * 8, card=True) == "negate"
    assert by_words([500, 600, 700] + [-o for o in others], ["PAYMENT THANK YOU"] * 3 + ["SHOP"] * 8, card=True) == "as_is"


def test_79_percent_of_the_rest_isnt_enough_and_80_is():
    def rest(pos):
        return [100] * pos + [-100] * (100 - pos)
    words = ["ONLINE PMT"] * 3 + ["SHOP"] * 100
    assert by_words([-1, -2, -3] + rest(80), words, card=True) == "negate"
    assert by_words([-1, -2, -3] + rest(79), words, card=True) is None


def test_payments_of_both_signs_are_no_evidence():
    assert by_words([-1, 2, -3] + [100] * 10, ["EPAY"] * 3 + ["SHOP"] * 10, card=True) is None


def test_a_bank_reads_deposit_words():
    assert by_words([210000, 210000, 125] + [-100] * 9, ["NORTHWIND PAYROLL"] * 2 + ["INTEREST PAID"] + ["SHOP"] * 9,
                    card=False) == "as_is"


def _ledger(n: int, broken: int, newest_first: bool = False):
    raw, bal, b = [], [], 100_000
    for i in range(n):
        a = 1000 + i if i % 2 else -(500 + i)
        b += a
        raw.append(a)
        bal.append(b)
    for i in range(1, broken + 1):
        raw[i] += 1                          # the pair ending at row i no longer adds up
    if newest_first:
        raw.reverse()
        bal.reverse()
    return raw, bal


@pytest.mark.parametrize("newest_first", [False, True])
def test_90_percent_of_balance_pairs_decide_and_89_dont(newest_first):
    assert by_balance(*_ledger(101, 10, newest_first), card=False) == "as_is"
    assert by_balance(*_ledger(101, 11, newest_first), card=False) is None
    assert by_balance(*_ledger(101, 10, newest_first), card=True) == "negate"


def test_a_balance_that_falls_with_the_amounts_means_the_other_way():
    raw, bal = _ledger(20, 0)
    assert by_balance([-a for a in raw], bal, card=False) == "negate"


def test_fewer_than_two_pairs_or_no_balance_is_no_evidence():
    assert by_balance([100, 200], [1100, 1300], card=False) is None
    assert by_balance([100, 200, 300], [], card=False) is None
    assert by_balance([100, 200, 300], [None, 1300, None], card=False) is None


def test_the_lean():
    assert (lean([1, 2, -3]), lean([1, -2, -3]), lean([1, -1]), lean([0, 0]), lean([])) == \
        ("positive", "negative", None, None, None)


def test_evidence_against_a_remembered_sign_is_clear():
    """Review focus 5: a layout remembered as 'as is' for a positive-purchases card file. The web shows the question
    again with "This file's signs look the other way from last time." when the verdict is clear and opposite."""
    t = read_table(decode(read("amex-basic.csv")))
    mine = remembered(layout_key(t), t.header, 9, "Other Bank", {"date": 0, "description": 1, "amount": 2}, False, "%m/%d/%Y")
    s = _sign("amex-basic.csv", mine)
    assert s["credit"]["verdict"] == "negate"
