"""A new layout's proposal and its one retry (spec P16, P17, P21): ask, validate, read, check; when it doesn't add up,
ask once more with the gap, the sections and the failing lines, and keep the better of the two."""
import copy
from datetime import date

from steward.services.statements.propose import propose
from tests.statement_files import pages, pdf

TODAY = date(2026, 10, 30)


class Asker:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, sent, hint):
        self.calls.append(hint)
        return self.answers.pop(0) if self.answers else None


def test_a_good_first_proposal_is_one_request():
    truth = pdf("chase_card")[1]
    ask = Asker(truth.layout)
    got = propose(ask, pages("chase_card"), TODAY)
    assert (got.layout, got.gap, got.asked, got.failed) == (truth.layout, 0, 1, 0) and ask.calls == [None]


def test_a_retry_keeps_the_better_proposal_and_carries_the_gap():
    truth = pdf("chase_checking")[1]
    wrong = copy.deepcopy(truth.layout)
    wrong["table"]["sections"] = wrong["table"]["sections"][:1] + wrong["table"]["sections"][2:]   # misses a section
    ask = Asker(wrong, truth.layout)
    got = propose(ask, pages("chase_checking"), TODAY)
    assert got.layout == truth.layout and got.gap == 0 and got.asked == 2
    hint = ask.calls[1]
    assert hint["previous"] == wrong and hint["gap_cents"] != 0
    worse = Asker(wrong, copy.deepcopy(wrong) | {"institution": "Elsewhere"})
    kept = propose(worse, pages("chase_checking"), TODAY)
    assert kept.layout == wrong and kept.gap != 0


def test_no_usable_answer_is_a_failure_and_a_bad_retry_keeps_the_first():
    assert propose(Asker(None), pages("chase_card"), TODAY).layout is None
    bad = copy.deepcopy(pdf("chase_card")[1].layout)
    bad["closing"]["label"] = "Not On The Page"
    got = propose(Asker(bad), pages("chase_card"), TODAY)
    assert (got.layout, got.failed) == (None, 1)
    off = copy.deepcopy(pdf("chase_checking")[1].layout)
    off["table"]["sections"] = off["table"]["sections"][:1]
    kept = propose(Asker(off, None), pages("chase_checking"), TODAY)
    assert kept.layout == off and kept.retry_failed is True


def test_a_learned_layout_that_drifted_asks_once_with_it_as_the_first():
    truth = pdf("chase_checking", "drifted")[1]
    learned = pdf("chase_checking")[1].layout
    ask = Asker(truth.layout)
    got = propose(ask, pages("chase_checking", "drifted"), TODAY, first=learned)
    assert got.gap == 0 and got.layout == truth.layout and ask.calls[0]["previous"] == learned
