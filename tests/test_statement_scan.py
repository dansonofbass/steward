"""Reading a scanned page (spec P25, "Reading a scanned page"): the NAS parses every value; the facts from the first page
that has each; rows in page order; the way sets the sign; a value that doesn't parse is listed; the same check."""
import base64
import json
from datetime import date

import httpx2
import pytest

from steward.db.models import AccountType
from steward.services.statements import check
from steward.services.statements.client import HttpStatementClient
from steward.services.statements.scan import assemble, kind_for, mask_answer
from tests.gateway.test_statements_page import ANSWER, png
from tests.statement_files import pdf
from tests.statement_helpers import truth_answers

TODAY = date(2026, 10, 30)
ONE_ACCOUNT = ("chase_checking", "boa_checking", "wells_checking", "chase_card", "amex_card", "citi_card", "capone_card")


def _numbered(answers):
    return [{"n": k, **a} for k, a in enumerate(answers, 1)]


@pytest.mark.parametrize("sid", ONE_ACCOUNT)
def test_a_perfect_reading_assembles_the_truth_and_adds_up(sid):
    truth = pdf(sid)[1]
    reading, facts = assemble(_numbered(truth_answers(truth)), truth.kind, TODAY)
    assert reading.error is None and reading.unreadable == []
    assert [(r.date.isoformat(), r.amount_cents, r.description, r.page) for r in reading.rows] == \
        [(r["date"], r["amount_cents"], r["description"], r["page"]) for r in truth.rows]
    assert check.gap(truth.kind, reading.opening, reading.closing, [r.amount_cents for r in reading.rows]) == 0
    assert (facts["scan"], facts["last4"], facts["institution"]) == (True, truth.last4, truth.institution)


def test_a_slipped_digit_fails_the_check_by_the_slip():
    truth = pdf("boa_checking")[1]
    reading, _ = assemble(_numbered(truth_answers(truth, slip_cents=900)), "bank", TODAY)
    assert check.gap("bank", reading.opening, reading.closing, [r.amount_cents for r in reading.rows]) == -900


def test_an_unknown_way_takes_the_printed_sign_for_the_kind():
    page = {**ANSWER, "rows": [{"date": "03/04/26", "description": "SHOP", "amount": "12.00", "way": "unknown", "section": None},
                               {"date": "03/05/26", "description": "REFUND", "amount": "(3.00)", "way": "unknown", "section": None}]}
    bank, _ = assemble([{"n": 1, **page}], "bank", TODAY)
    card, _ = assemble([{"n": 1, **page}], "card", TODAY)
    assert [r.amount_cents for r in bank.rows] == [1200, -300] and [r.amount_cents for r in card.rows] == [-1200, 300]


def test_values_that_dont_parse_are_listed_in_the_import_rounds_words():
    page = {**ANSWER, "rows": [{"date": "03/04/26", "description": "SHOP", "amount": "12.O0", "way": "out", "section": None},
                               {"date": "the 4th", "description": "SHOP", "amount": "12.00", "way": "out", "section": None}]}
    reading, facts = assemble([{"n": 2, **page}], "bank", TODAY)
    assert reading.rows == []
    assert reading.unreadable == [(2, 'the amount "12.O0" isn\'t a dollar amount.'), (2, 'the date "the 4th" isn\'t a date.')]
    assert facts["unreadable"] == [{"page": 2, "text": 'the amount "12.O0" isn\'t a dollar amount.'},
                                   {"page": 2, "text": 'the date "the 4th" isn\'t a date.'}]


def test_the_facts_come_from_the_first_page_that_has_each():
    p1 = {**ANSWER, "period": None, "opening": None, "account_last4": None, "rows": []}
    p2 = {**ANSWER, "rows": []}
    reading, facts = assemble([{"n": 1, **p1}, {"n": 2, **p2}], "bank", TODAY)
    assert reading.period == (date(2026, 3, 1), date(2026, 3, 31)) and reading.opening == 532077 and facts["last4"] == "3456"


def test_no_period_is_an_error_and_an_old_one_too():
    assert assemble([{"n": 1, **{**ANSWER, "period": None}}], "bank", TODAY)[0].error == "no_period"
    old = {**ANSWER, "period": {"start": "March 1, 2022", "end": "March 31, 2022"}}
    assert assemble([{"n": 1, **old}], "bank", TODAY)[0].error == "no_period"


def test_what_the_model_reads_back_is_masked():
    got = mask_answer({**ANSWER, "rows": [{**ANSWER["rows"][0], "description": "TRANSFER TO 000123456789"}]})
    assert got["rows"][0]["description"] == "TRANSFER TO ••6789"


def test_every_string_the_model_reads_back_is_masked_not_just_descriptions():
    acct = "000123456789"
    got = mask_answer({**ANSWER, "institution": f"Bank {acct}", "opening": f"{acct}",
                       "period": {"start": f"March 1, 2026 {acct}", "end": "March 31, 2026"},
                       "rows": [{**ANSWER["rows"][0], "section": f"Acct {acct}"}],
                       "holdings": [{"symbol": "VTI", "name": f"Fund {acct}", "shares": None, "value": "1.00"}]})
    assert acct not in json.dumps(got)
    reading, _ = assemble([{"n": 1, **{**ANSWER, "rows": [{**ANSWER["rows"][0], "section": f"Acct {acct}"}]}}], "bank", TODAY)
    assert reading.rows[0].section == "Acct ••6789"


def test_kinds_by_account_type():
    assert [kind_for(t) for t in (AccountType.credit, AccountType.loan, AccountType.checking, None)] == ["card", "loan", "bank", "bank"]


def test_the_page_request_goes_with_the_token_and_comes_back_checked():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json={"page": ANSWER, "model": "gemma4:12b-it-qat"})
    c = HttpStatementClient("https://gateway.tail1234.ts.net:8430", "t" * 64, transport=httpx2.MockTransport(handler))
    image = png()
    assert c.page(image, 1, 2, 1700, 2200) == ANSWER and c.last_model == "gemma4:12b-it-qat"
    assert seen[0] == {"page": 1, "of": 2, "image": base64.b64encode(image).decode(), "width_px": 1700, "height_px": 2200,
                       "want": "rows"}
    bad = HttpStatementClient("https://x", "t", transport=httpx2.MockTransport(
        lambda r: httpx2.Response(200, json={"page": {**ANSWER, "x": 1}})))
    assert bad.page(image, 1, 2, 1700, 2200) is None and bad.last_error
