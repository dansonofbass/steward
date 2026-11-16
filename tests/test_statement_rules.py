"""Applying a layout (spec P18-P20, P44): each synthetic statement, with its truth layout, reads its truth rows and
facts exactly; bands, wrapped lines, never-rows, signs, years and the check."""
import copy
from datetime import date

import pytest

from steward.services.statements import check, rules
from steward.services.statements.rules import Band, apply, assign, bands
from steward_gateway.evals.statement_set import BANK_CARD
from tests.statement_files import pages, pdf

TODAY = date(2026, 10, 30)


def _rows(reading):
    return [{"date": r.date.isoformat(), "description": r.description, "amount_cents": r.amount_cents,
             "section": r.section, "page": r.page} for r in reading.rows]


@pytest.mark.parametrize("sid", BANK_CARD)
def test_each_statement_reads_its_truth_exactly(sid):
    truth = pdf(sid)[1]
    for k, part in enumerate(truth.parts or (truth,)):
        got = apply(truth.layout, pages(sid), TODAY, part=k)
        assert got.error is None and got.unreadable == []
        assert got.period == truth.period
        assert (got.last4, got.opening, got.closing) == (part.last4, part.opening_cents, part.closing_cents)
        assert _rows(got) == list(part.rows)
        assert check.gap(truth.kind, got.opening, got.closing, [r.amount_cents for r in got.rows]) == 0


def test_wrapped_descriptions_always_join():
    got = apply(pdf("wells_checking")[1].layout, pages("wells_checking"), TODAY)
    assert got.rows[0].description == "DEPOSIT PAYROLL BRIGHTWATER MFG DIRECT DEP"
    assert got.rows[1].description == "ACH DEBIT PRAIRIE ENERGY COOP WEB ID ••4567"


def test_a_skip_section_and_the_built_in_never_rows_are_left_out():
    chase = apply(pdf("chase_checking")[1].layout, pages("chase_checking"), TODAY)
    assert "DAILY ENDING BALANCE" not in {r.section for r in chase.rows}
    card = apply(pdf("chase_card")[1].layout, pages("chase_card"), TODAY)
    assert not any("TOTAL" in r.description for r in card.rows)


def test_the_off_statement_misses_by_the_misprint_and_names_its_section():
    truth = pdf("chase_checking", "off")[1]
    got = apply(truth.layout, pages("chase_checking", "off"), TODAY)
    assert check.gap("bank", got.opening, got.closing, [r.amount_cents for r in got.rows]) == 1240
    assert check.off_sections(check.section_report(got)) == [("ELECTRONIC WITHDRAWALS", 1240)]


def test_card_sections_carry_their_way_and_cr_credits_read():
    got = apply(pdf("amex_card")[1].layout, pages("amex_card"), TODAY)
    payment = next(r for r in got.rows if r.description.startswith("PAYMENT RECEIVED"))
    refund = next(r for r in got.rows if r.description.endswith("RETURN"))
    assert payment.amount_cents == 184207 and refund.amount_cents == 2500
    assert all(r.amount_cents < 0 for r in got.rows if r not in (payment, refund))


def test_dec_jan_rows_take_the_right_year():
    got = apply(pdf("amex_card")[1].layout, pages("amex_card"), TODAY)
    days = {r.description: r.date for r in got.rows}
    assert days["DUNMORE DELI"] == date(2025, 12, 19) and days["BLUE HERON COFFEE"] == date(2026, 1, 15)


def test_the_post_date_is_used_when_there_are_two():
    truth = pdf("citi_card")[1]
    got = apply(truth.layout, pages("citi_card"), TODAY)
    assert [r.date.isoformat() for r in got.rows] == [r["date"] for r in truth.rows]


def _page(lines, n=1):
    return {"n": n, "width": 612.0, "height": 792.0, "scan": False,
            "lines": [{"y": y, "cells": [{"x0": x0, "x1": x1, "text": t} for x0, x1, t in cells]} for y, cells in lines]}


LAYOUT = {"kind": "bank", "institution": "Test Bank", "account_label": "Account", "account_marker": None,
          "period": {"label": "Statement Period", "date_format": "%m/%d/%Y"},
          "opening": {"label": "Beginning Balance"}, "closing": {"label": "Ending Balance"},
          "table": {"columns": [{"header": "Date", "field": "date"}, {"header": "Description", "field": "description"},
                                {"header": "Amount", "field": "amount"}],
                    "date_format": "%m/%d", "negative": "minus",
                    "sections": [{"title": "Activity", "way": "signed", "total_label": None}], "skip": []},
          "holdings": None}


def _statement(rows, layout=LAYOUT, period="03/01/2026 - 03/31/2026"):
    head = [(60, [(40, 80, "Account"), (100, 140, "••1234")]), (72, [(40, 120, "Statement Period"), (130, 260, period)]),
            (90, [(40, 120, "Beginning Balance"), (260, 300, "$100.00")]), (102, [(40, 110, "Ending Balance"), (260, 300, "$90.00")]),
            (200, [(40, 58, "Date"), (100, 150, "Description"), (530, 560, "Amount")]), (218, [(40, 80, "Activity")])]
    body = [(231 + 13 * k, [(40, 64, d), (100, 200, desc), (525, 560, amt)]) for k, (d, desc, amt) in enumerate(rows)]
    return [_page(head + body)]


@pytest.mark.parametrize("printed", ["-10.00", "(10.00)", "10.00-", "10.00 CR"])
def test_the_four_negative_styles(printed):
    got = apply(LAYOUT, _statement([("03/04", "SHOP", printed)]), TODAY)
    assert [r.amount_cents for r in got.rows] == [-1000]
    assert check.gap("bank", got.opening, got.closing, [-1000]) == 0


def test_a_row_eight_days_outside_is_unreadable():
    got = apply(LAYOUT, _statement([("03/04", "SHOP", "-5.00"), ("04/08", "LATE", "-5.00"), ("04/07", "EDGE", "0.00")]),
                TODAY)
    assert [r.description for r in got.rows] == ["SHOP", "EDGE"]
    assert got.unreadable == [(1, "04/08 LATE -5.00")]


def test_a_date_that_fits_no_format_is_unreadable():
    got = apply(LAYOUT, _statement([("3rd Mar", "SHOP", "-5.00")]), TODAY)
    assert got.rows == [] and got.unreadable == [(1, "3rd Mar SHOP -5.00")]


def test_a_period_in_another_format_old_or_future():
    assert apply(LAYOUT, _statement([], period="March 1, 2026 - March 31, 2026"), TODAY).period == \
        (date(2026, 3, 1), date(2026, 3, 31))
    assert apply(LAYOUT, _statement([], period="03/01/2023 - 03/31/2023"), TODAY).error == "no_period"
    assert apply(LAYOUT, _statement([], period="11/01/2026 - 11/30/2026"), TODAY).error == "no_period"


def test_bands_from_the_header_positions_alone():
    cols = [{"header": "Date", "field": "date"}, {"header": "Description", "field": "description"},
            {"header": "Deposits", "field": "credit"}, {"header": "Withdrawals", "field": "debit"}]
    found = [{"x0": 40, "x1": 58}, {"x0": 110, "x1": 158}, {"x0": 404, "x1": 440}, {"x0": 462, "x1": 510}]
    assert bands(cols, found, 612) == [Band("date", 35, 104), Band("description", 105, 333),
                                      Band("credit", 334, 444), Band("debit", 445, 515)]


def test_a_cell_goes_to_the_larger_overlap_else_the_nearest_within_15():
    bs = [Band("description", 100, 300), Band("amount", 301, 450)]
    assert assign([{"x0": 280, "x1": 340, "text": "a"}], bs) == {"amount": ["a"]}
    assert assign([{"x0": 290, "x1": 305, "text": "b"}], bs) == {"description": ["b"]}
    assert assign([{"x0": 460, "x1": 470, "text": "c"}], bs) == {"amount": ["c"]}
    assert assign([{"x0": 470, "x1": 480, "text": "d"}], bs) == {}


def test_owed_and_asset_sense():
    assert check.gap("bank", 10000, 9000, [-1000]) == 0
    assert check.gap("card", 10000, 11000, [-1000]) == 0
    assert check.gap("card", 10000, 11000, [1000]) == 2000
    assert check.gap("bank", None, 9000, [-1000]) is None


def test_a_combined_statement_reads_each_part_and_without_a_marker_doesnt_split():
    truth = pdf("cu_savings")[1]
    assert rules.part_count(pages("cu_savings"), "Share Account") == 2
    flat = copy.deepcopy(truth.layout)
    flat["account_marker"] = None
    got = apply(flat, pages("cu_savings"), TODAY)
    assert check.gap("bank", got.opening, got.closing, [r.amount_cents for r in got.rows]) != 0


def test_a_skip_section_total_is_not_recorded_so_the_check_never_calls_it_off():
    layout = copy.deepcopy(pdf("chase_checking")[1].layout)
    for s in layout["table"]["sections"]:
        if s["way"] == "skip":
            s["total_label"] = "Total Daily Balance"
    pg = pages("chase_checking")
    last = pg[-1]["lines"][-1]
    extra = copy.deepcopy(last)
    extra["cells"] = [dict(last["cells"][0], text="Total Daily Balance"), dict(last["cells"][-1], text="1,234.56")]
    pg[-1]["lines"].append(extra)
    got = apply(layout, pg, TODAY)
    assert got.error is None and "DAILY ENDING BALANCE" not in got.totals
    assert check.off_sections(check.section_report(got)) == []
