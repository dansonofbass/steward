"""Investment and loan statements (spec P15, P16, P39, "Investment statements"): the proposal's holdings validated
against the page, the holdings read by bands from their header with the cash sweep marked, the total within $1, a
second table after the total left alone, and a loan's principal."""
import copy
from datetime import date

import pytest

from steward.services.statements import check
from steward.services.statements.extract import for_model
from steward.services.statements.holdings import apply_holdings, apply_loan, shares_milli
from steward.services.statements.propose import read_all
from steward.services.statements.validate import errors
from steward_boundary.statements_wire import shape_errors
from steward_gateway.evals.statement_set import HOLDINGS, LOANS, build
from tests.statement_files import pages, pdf

TODAY = date(2026, 10, 30)


@pytest.mark.parametrize("sid", HOLDINGS)
def test_each_investment_statement_reads_its_truth(sid):
    truth = pdf(sid)[1]
    got = apply_holdings(truth.layout, pages(sid), TODAY)
    assert got.error is None and got.period == truth.period and got.last4 == truth.last4
    assert (got.ending, got.total) == (truth.closing_cents, truth.total_cents)
    assert [(h.symbol, h.name, h.shares_milli, h.value_cents, h.cash) for h in got.holdings] == \
        [(h["symbol"], h["name"], h["shares_milli"], h["value_cents"], h["cash"]) for h in truth.holdings]
    assert check.holdings_gap(got.total, [h.value_cents for h in got.holdings]) == 0
    assert errors(truth.layout, for_model(pages(sid))) == []


def test_the_holdings_check_is_within_a_dollar():
    assert check.holdings_gap(10_000, [9_900]) == 0
    assert check.holdings_gap(10_000, [9_899]) == 101
    assert check.holdings_gap(10_000, [10_101]) == -101
    assert check.holdings_gap(None, [1]) is None


def test_the_off_brokerage_misses_by_more_than_a_dollar():
    truth = pdf("fidelity_brokerage", "off")[1]
    got = apply_holdings(truth.layout, pages("fidelity_brokerage", "off"), TODAY)
    assert check.holdings_gap(got.total, [h.value_cents for h in got.holdings]) == 287          # $2.50 plus the 37¢


def test_the_balance_by_source_table_is_never_holdings():
    got = apply_holdings(pdf("empower_401k")[1].layout, pages("empower_401k"), TODAY)
    assert not any("Employer" in h.name or h.name == "Total" for h in got.holdings) and len(got.holdings) == 5


@pytest.mark.parametrize("sid", LOANS)
def test_a_loan_reads_its_principal(sid):
    truth = pdf(sid)[1]
    got = apply_loan(truth.layout, pages(sid), TODAY)
    assert (got.error, got.ending, got.period, got.holdings) == (None, truth.closing_cents, truth.period, [])
    assert errors(truth.layout, for_model(pages(sid))) == []
    readings, gap = read_all(truth.layout, pages(sid), TODAY)
    assert gap == 0 and readings[0].ending == truth.closing_cents


def _bad(change, sid="fidelity_brokerage"):
    p = copy.deepcopy(pdf(sid)[1].layout)
    change(p)
    return errors(p, for_model(pages(sid)))


def test_investment_proposals_are_held_to_the_page():
    def no_value(p): p["holdings"]["columns"][4]["field"] = "ignore"
    def no_name(p):
        p["holdings"]["columns"][0]["field"] = "ignore"
        p["holdings"]["columns"][1]["field"] = "ignore"
    def total_elsewhere(p): p["holdings"]["total_label"] = "Grand Total Of Everything"
    def four_cash(p): p["holdings"]["cash_labels"] = ["Cash", "Sweep", "Money Market", "Core"]
    def cash_not_on_page(p): p["holdings"]["cash_labels"] = ["Core Position"]
    def twice(p): p["holdings"]["columns"][2]["field"] = "value"
    def none(p): p["holdings"] = None
    for change in (no_value, no_name, total_elsewhere, four_cash, cash_not_on_page, twice, none):
        assert _bad(change), change.__name__
    def loan_with_table(p): p["table"] = copy.deepcopy(pdf("chase_card")[1].layout["table"])
    assert _bad(loan_with_table, "auto_loan")


def test_shares_read_as_milli_shares():
    assert [shares_milli(x) for x in ("412.118", "1,204.5531", "88.2140", "", None, "n/a", "NaN", "Infinity", "1e9")] == \
        [412118, 1204553, 88214, 0, 0, 0, 0, 0, 0]


def test_a_scanned_brokerage_assembles_its_holdings():
    from steward.services.statements.scan import assemble
    from tests.statement_helpers import truth_answers
    truth = pdf("fidelity_brokerage")[1]
    answers = [{"n": k, **a} for k, a in enumerate(truth_answers(truth), 1)]
    reading, facts = assemble(answers, "investment", TODAY)
    assert facts["total_cents"] == truth.total_cents
    assert [(h["name"], h["value_cents"], h["cash"]) for h in facts["holdings"]] == \
        [(h["name"], h["value_cents"], False) for h in truth.holdings]


@pytest.mark.parametrize("sid", HOLDINGS + LOANS)
def test_the_truth_layouts_pass_the_wire_shape(sid):
    assert shape_errors(build(sid)[1].layout) == []


def test_a_scan_with_no_period_still_assembles_and_holdings_are_bounded():
    from steward.services.statements.scan import assemble
    reading, facts = assemble([{"n": 1, "page_kind": "holdings", "institution": None, "account_last4": None,
                                "period": None, "opening": None, "closing": None, "rows": [], "holdings": [],
                                "total": None}], "investment", TODAY)
    assert reading.error == "no_period" and facts["holdings"] == [] and facts["total_cents"] is None
    one = {"symbol": "ABC", "name": "Abc Fund", "shares": "1", "value": "1.00"}
    many = [{"n": k, "page_kind": "holdings", "institution": None, "account_last4": None,
             "period": {"start": "October 1, 2026", "end": "October 28, 2026"} if k == 1 else None, "opening": None,
             "closing": None, "rows": [], "holdings": [one] * 40, "total": None} for k in range(1, 7)]
    reading, facts = assemble(many, "investment", TODAY)
    assert reading.error == "too_many_holdings" and len(facts["holdings"]) <= 200


def test_labels_are_applied_as_validated_cash_is_a_whole_word():
    truth = pdf("fidelity_brokerage")[1]
    layout = copy.deepcopy(truth.layout)
    layout["holdings"]["cash_labels"] = ["Cash"]
    got = apply_holdings(layout, pages("fidelity_brokerage"), TODAY)
    assert [h.name for h in got.holdings if h.cash] == [h["name"] for h in truth.holdings if h["cash"]]


def test_the_wrong_block_for_a_kind_is_refused():
    def bank_with_holdings(p): p["holdings"] = copy.deepcopy(pdf("fidelity_brokerage")[1].layout["holdings"])
    assert _bad(bank_with_holdings, "chase_card")
    def total_midline(p): p["holdings"]["total_label"] = "Stock Index"
    assert _bad(total_midline)
