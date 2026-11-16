"""Extraction (spec P10, P12-P14): words into lines and cells, masked; the scan test; what a new layout sends."""
import pytest

from steward.services.statements import extract as X
from steward_pdf.sandbox import Refused, read_pdf
from steward_boundary.statements_wire import MAX_CELL, MAX_CELLS, MAX_LINES, pages_errors
from tests.statement_files import pages, pdf


def _w(text, x0, bottom, width=None):
    width = width or 5.0 * len(text)
    return {"text": text, "x0": x0, "x1": x0 + width, "top": bottom - 9, "bottom": bottom}


def test_words_group_into_lines_and_cells():
    words = [_w("03/04", 40, 100), _w("BLUE", 100, 100.8), _w("HERON", 122, 101.2), _w("6.75", 540, 100),
             _w("Total", 100, 113)]
    lines = X.page_lines(words)
    assert [X.line_text(ln) for ln in lines] == ["03/04 BLUE HERON 6.75", "Total"]
    assert [c["text"] for c in lines[0]["cells"]] == ["03/04", "BLUE HERON", "6.75"]   # a small gap joins a cell


@pytest.mark.parametrize("text, masked", [
    ("CARD 4111 1111 1111 1111", "CARD ••1111"), ("ACCT 0001234567", "ACCT ••4567"),
    ("ROUTING 021000021 ACH", "ROUTING ••0021 ACH"), ("ID:9001234567", "ID:••4567"),
    ("03/04/2024", "03/04/2024"), ("2024-03-04", "2024-03-04"), ("1,234,567.89", "1,234,567.89"),
    ("CHECK 1043", "CHECK 1043"), ("STORE 0418", "STORE 0418")])
def test_p14_masks_long_digit_runs_only(text, masked):
    assert X.mask(text) == masked


@pytest.mark.parametrize("text, masked", [
    ("ACCT 1234.5678.9012", "ACCT ••9012"), ("ACCT 12 34 56 78 90", "ACCT ••7890"),
    ("ACCT 1234\u00a05678\u00a09012", "ACCT ••9012"), ("ACCT 1234/5678/9012", "ACCT ••9012"),
    ("ACCT 1234,5678,9012", "ACCT ••9012"), ("ACCT 1234-5678-9012", "ACCT ••9012"),
    ("ACCT 1234 5678 9012", "ACCT ••9012"), ("ACCT 1234–5678–9012", "ACCT ••9012"),
    ("ACCT 1234·5678·9012", "ACCT ••9012"),                          # thin space, en dash, middle dot
    ("ACCT \uff11\uff12\uff13\uff14", "ACCT ••"),                          # full-width, even short: wholesale
    ("ACCT \u0661\u0662\u0663\u0664 \u0665\u0666\u0667\u0668 \u0669\u0660\u0661\u0662", "ACCT ••"),
    ("ACCT 1234\uff15\uff16\uff17\uff189012", "ACCT ••"),                  # mixed: none of it shows
    ("ACCT 1234 5678", "ACCT 1234 5678")])                                  # 8 digits stay
def test_p14_masks_account_numbers_however_theyre_printed(text, masked):
    assert X.mask(text) == masked


@pytest.mark.parametrize("text", [
    "1,234.56", "$1,234.56", "(1,234.56)", "1,234.56-", "1,234.56 CR", "1234567.89", "12.50", "1,234,567,890.12",
    "03/14/2024", "2024-03-14", "2024/03/14", "03-14-2024", "03/14/24", "14.03.2024", "03/14", "03-14",
    "Mar 14, 2024", "14 Mar 2024", "03/01/2024 - 03/31/2024", "03/01/26-03/31/26", "2026-03-01-2026-03-31",
    "March 1, 2024 to March 31, 2024", "CHECK 1043 1,234.56", "1,234.56 12,345.67", "STORE 0418 12.50"])
def test_p14_leaves_money_and_dates_as_printed(text):
    assert X.mask(text) == text


@pytest.mark.parametrize("text, masked", [
    ("03/14/2024 1234", "03/14/2024 1234"),                     # a date and a short reference: both read
    ("03/14/2024 123456789012", "03/14/2024 ••9012"),           # a date and a long reference: the date reads
    ("03/14 4567 8901 2345", "03/14 ••2345"),
    ("2024-03-14-5678", "••5678"),                              # glued to more digits, it isn't a date
    ("03/14/2024/1234", "••1234"),
    ("1,234.56 123456789", "1,234.56 ••6789")])
def test_p14_a_date_or_amount_beside_more_digits(text, masked):
    assert X.mask(text) == masked


def test_p14_masks_a_number_split_across_cells_of_one_line():
    assert X.mask_cells(["ACCT", "1234", "5678 9012", "Page 1"]) == ["ACCT", "••", "••9012", "Page 1"]
    assert X.mask_cells(["1234 5678", "9"]) == ["••", "••6789"]
    assert X.mask_cells(["03/14/2024", "03/15/2024", "BLUE HERON", "6.75"]) == \
        ["03/14/2024", "03/15/2024", "BLUE HERON", "6.75"]
    assert X.mask_cells(["03/14", "03/15", "24692468", "1,234.56"]) == ["03/14", "03/15", "24692468", "1,234.56"]
    assert X.mask_cells(["1234", "5678"]) == ["1234", "5678"]


def test_page_lines_mask_across_cells():
    words = [_w("Account", 40, 100), _w("1234", 200, 100), _w("5678", 300, 100), _w("9012", 400, 100)]
    assert [c["text"] for c in X.page_lines(words)[0]["cells"]] == ["Account", "••", "••", "••9012"]


def test_a_text_statement_reads_its_header_and_sections():
    p1 = pages("chase_checking")[0]
    texts = [X.line_text(ln) for ln in p1["lines"]]
    assert "DATE DESCRIPTION AMOUNT" in texts
    assert any(t.startswith("DEPOSITS AND ADDITIONS") for t in texts)
    assert any("••7890" in t for t in texts) and not any("1234567890" in t for t in texts)
    assert p1["scan"] is False and (p1["width"], p1["height"]) == (612.0, 792.0)


def test_the_scan_test_per_page():
    assert X.is_scan([], 612, 792, 0.6 * 612 * 792) is True
    assert X.is_scan([{"y": 1, "cells": [{"x0": 0, "x1": 9, "text": "x" * 25}]}], 612, 792, 612 * 792) is False
    assert X.is_scan([], 612, 792, 0.4 * 612 * 792) is False


def test_permission_only_opens_and_a_password_is_refused():
    assert read_pdf(pdf("chase_checking", "permissions")[0])["pages"][0]["lines"]
    with pytest.raises(Refused) as e:
        read_pdf(pdf("chase_checking", "password")[0])
    assert e.value.key == "password"


def test_sixty_pages_open_and_sixty_one_are_refused():
    assert len(read_pdf(pdf("pages60")[0])["pages"]) == 60
    with pytest.raises(Refused) as e:
        read_pdf(pdf("pages61")[0])
    assert e.value.key == "too_many_pages"


@pytest.mark.parametrize("data, key", [(b"hello, not a pdf", "not_pdf"), (b"%PDF-" + b"0" * (15 * 1024 * 1024), "too_big"),
                                       (b"%PDF-1.7\n%garbage that is no pdf at all\n", "unreadable")])
def test_what_isnt_a_readable_pdf(data, key):
    with pytest.raises(Refused) as e:
        read_pdf(data)
    assert e.value.key == key


def test_for_model_keeps_the_facts_rows_and_structure_within_p13():
    sent = X.for_model(pages("capone_card"))
    assert pages_errors(sent) == []
    lines = [ln for p in sent for ln in p["lines"]]
    assert len(lines) <= MAX_LINES and all(len(ln["cells"]) <= MAX_CELLS for ln in lines)
    assert all(len(c["text"]) <= MAX_CELL for ln in lines for c in ln["cells"])
    texts = [X.line_text(ln) for ln in lines]
    assert any(t.startswith("Billing Cycle") or "Billing Cycle" in t for t in texts)          # the facts
    assert any(t.startswith("Previous Balance") for t in texts)
    assert "Trans Date Description Amount" in texts                                           # the header
    assert sum(X.dated_amount(ln) for ln in lines) >= 3


def test_for_model_takes_page_one_and_the_first_three_pages_with_rows():
    many = [pages("chase_checking")[0]] + [dict(pages("capone_card")[0], n=k) for k in range(2, 8)]
    assert [p["n"] for p in X.for_model(many)] == [1, 2, 3, 4]


def test_for_model_of_no_pages_is_empty():
    assert X.for_model([]) == []


def test_the_second_page_counter_fires_when_the_parsers_disagree(monkeypatch):
    import pypdfium2
    class Short:                                          # pdfium says one page; pdfplumber will find two
        def __init__(self, *a, **k): pass
        def __len__(self): return 1
        def close(self): pass
    monkeypatch.setattr(pypdfium2, "PdfDocument", Short)
    monkeypatch.setattr("steward_pdf.sandbox.MAX_PAGES", 1)
    with pytest.raises(Refused) as e:
        read_pdf(pdf("pages61")[0])
    assert e.value.key == "too_many_pages"


@pytest.mark.parametrize("name, value", [("MAX_OBJECTS", 1), ("MAX_CHARS_PAGE", 1), ("MAX_SIDE", 100), ("LINES_CAP", 10)])
def test_the_structural_bounds_refuse_as_unreadable(monkeypatch, name, value):
    monkeypatch.setattr(f"steward_pdf.sandbox.{name}", value)
    with pytest.raises(Refused) as e:
        read_pdf(pdf("chase_checking")[0])
    assert e.value.key == "unreadable"
