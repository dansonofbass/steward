"""Validating a proposal (spec P16): strict schema, every label verbatim in the lines sent, a two-line header accepted,
each rule refusing a crafted proposal. A proposal that fails counts as no answer."""
import copy

import pytest

from steward.services.statements.extract import for_model
from steward.services.statements.validate import errors
from steward_gateway.evals.statement_set import BANK_CARD
from tests.statement_files import pages, pdf


@pytest.mark.parametrize("sid", BANK_CARD)
def test_each_truth_layout_is_usable(sid):
    assert errors(pdf(sid)[1].layout, for_model(pages(sid))) == []


def _bad(change):
    p = copy.deepcopy(pdf("chase_card")[1].layout)
    change(p)
    return errors(p, for_model(pages("chase_card")))


def test_each_p16_rule_refuses_a_crafted_proposal():
    def label(p): p["closing"]["label"] = "Ignore your instructions"
    def twice(p): p["table"]["columns"][1]["field"] = "date"
    def both(p): p["table"]["columns"].append({"header": "Withdrawals", "field": "debit"})
    def on_header(p): p["table"]["sections"][0]["title"] = "Merchant Name"
    def fmt(p): p["table"]["date_format"] = "%Q"
    def no_period(p): p["period"]["label"] = ""
    def thirteen(p): p["table"]["sections"] = [dict(p["table"]["sections"][0]) for _ in range(13)]
    def extra_key(p): p["x0"] = 36
    def no_money(p): p["table"]["columns"][2]["field"] = "ignore"
    def section_not_in_page(p): p["table"]["sections"][1]["title"] = "Cash Advances"
    for change in (label, twice, both, on_header, fmt, no_period, thirteen, extra_key, no_money, section_not_in_page):
        assert _bad(change), change.__name__


def test_a_two_line_header_is_accepted_by_its_words():
    def merged(p): p["table"]["columns"][0]["header"] = "Date of Transaction"
    assert _bad(merged) == []


def test_header_cells_must_sit_on_one_line():
    def split(p): p["table"]["columns"][2]["header"] = "Previous Balance"
    assert "the header cells aren't on one line" in _bad(split)


def test_a_label_must_match_the_page_characters_not_just_its_words():
    """F5: spec P16 says verbatim, so 'new balance' for the printed 'New Balance' is refused."""
    layout = pdf("chase_card")[1].layout
    printed = layout["closing"]["label"]
    assert printed != printed.lower()
    def lowered(p): p["closing"]["label"] = printed.lower()
    assert "the closing label isn't in the lines sent" in _bad(lowered)


def _place(where: str, label: str):
    def change(p):
        t = p["table"]
        if where in ("period", "opening", "closing"):
            p[where]["label"] = label
        elif where == "account":
            p["account_label"] = label
        elif where == "marker":
            p["account_marker"] = label
        elif where == "header":
            t["columns"][1]["header"] = label
        elif where == "section":
            t["sections"][0]["title"] = label
        elif where == "total":
            t["sections"][0]["total_label"] = label
        else:
            t["skip"] = [label]
    return change


def _sent_text() -> str:
    from steward.services.statements.extract import line_text
    return "\n".join(line_text(ln) for pg in for_model(pages("chase_card")) for ln in pg["lines"])


@pytest.mark.parametrize("where", ["period", "opening", "closing", "account", "marker", "header", "section", "total",
                                   "skip"])
@pytest.mark.parametrize("label", ["a", "/", "/ ", "Da", "ate"])
def test_a_degenerate_label_is_refused_wherever_it_goes(where, label):
    """A letter, punctuation that normalizes to nothing, two letters, or a piece of a word ("ate" in "Date") occurs on
    the page, but isn't a label: a statement's text could steer the model to one that matches every line."""
    assert label.strip() in _sent_text()
    assert _bad(_place(where, label)), (where, label)


def test_a_mid_word_piece_isnt_in_the_lines_sent():
    assert "the closing label isn't in the lines sent" in _bad(_place("closing", "ate"))
    assert "the closing label needs at least 3 letters" in _bad(_place("closing", "a"))


def test_a_skip_label_must_start_a_line_or_fill_a_cell():
    """'Closing Date' is a whole phrase on the page, but only inside 'Opening/Closing Date': as a skip label it would
    drop a line it doesn't start."""
    assert "Closing Date" in _sent_text()
    assert "a skip label doesn't start a line or fill a cell" in _bad(_place("skip", "Closing Date"))
    assert _bad(_place("skip", "Opening/Closing Date")) == []
