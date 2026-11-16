"""One label matcher (spec P16, P18): validation and reading compare a layout's labels against the same text (the
child's masked cells, whitespace collapsed, case kept) with the same boundaries, so a label validated under one rule is
never applied under a looser one."""
import copy
from dataclasses import replace
from datetime import date

import pytest

from steward.services.statements import check, labels, layouts, rules, validate
from steward.services.statements.extract import for_model, line_text
from steward_pdf.sandbox import read_pdf
from steward_gateway.evals.statement_set import BANK_CARD, SPECS, _draw
from tests.statement_files import pages, pdf

TODAY = date(2026, 10, 30)


def _line(*texts: str, y: float = 900.0) -> dict:
    return {"y": y, "cells": [{"x0": 40.0 + 200 * k, "x1": 180.0 + 200 * k, "text": t} for k, t in enumerate(texts)]}


def _sent_with(line: dict, label: str) -> list[dict]:
    """chase_card's lines without any that hold the label's words (so only the line under test can match), plus it."""
    words = set(label.lower().split())
    sent = for_model(pages("chase_card"))
    for pg in sent:
        pg["lines"] = [ln for ln in pg["lines"] if not words & set(line_text(ln).lower().split())]
    sent[0]["lines"].append(line)
    return sent


def _layout(**change) -> dict:
    p = copy.deepcopy(pdf("chase_card")[1].layout)
    for where, label in change.items():
        if where == "closing":
            p["closing"]["label"] = label
        elif where == "skip":
            p["table"]["skip"] = [label]
        elif where == "title":
            p["table"]["sections"][0]["title"] = label
    return p


# (label, the line's cells, found by both): the closing label's lookup
FACTS = [
    ("Total", ("Subtotal", "12.00"), False),
    ("Total", ("Total", "12.00"), True),
    ("Total", ("TOTAL", "12.00"), False),                        # case kept (F5)
    ("Closing Balance", ("Your Closing Balance is", "5.00"), True),   # anywhere on a line, as a whole phrase
    ("Closing Balance", ("Closing Balances", "5.00"), False),
    ("ate", ("Date", "1.00"), False),
    ("a", ("a", "1.00"), False),
    ("/", ("Opening/Closing", "1.00"), False),
    ("Acct ••6789", ("Acct ••6789", "XXXX7890"), True),
]


@pytest.mark.parametrize("label, cells, found", FACTS)
def test_validation_and_reading_agree_on_a_fact_label(label, cells, found):
    line = _line(*cells)
    sent = _sent_with(line, label)
    validated = not any(e.startswith("the closing label") for e in validate.errors(_layout(closing=label), sent))
    read = rules._fact_line([line], label) is not None
    assert (validated, read) == (found, found)


# (skip label, the line's cells, skipped by both)
SKIPS = [
    ("Total", ("Subtotal of purchases", "12.00"), False),
    ("Total", ("Total of purchases", "12.00"), True),
    ("Rewards Summary", ("Rewards Summary",), True),
    ("Rewards Summary", ("03/14", "Rewards Summary", "1.00"), True),           # a whole cell
    ("Rewards Summary", ("03/14", "Your Rewards Summary", "1.00"), False),     # inside a cell, mid-line
]


@pytest.mark.parametrize("label, cells, skipped", SKIPS)
def test_validation_and_reading_agree_on_a_skip_label(label, cells, skipped):
    line = _line(*cells)
    errs = validate.errors(_layout(skip=label), _sent_with(line, label))
    validated = not any(e.startswith("a skip label") for e in errs)
    assert (validated, rules._skips(line, [label])) == (skipped, skipped)


def test_a_section_title_only_mid_line_neither_validates_nor_opens():
    line = _line("Your Standard Purchases this month")
    errs = validate.errors(_layout(title="Standard Purchases this month"), _sent_with(line, "Standard Purchases"))
    assert "a section title doesn't start a line" in errs
    assert labels.starts("Standard Purchases this month", line_text(line)) is False
    assert rules._opens(line, "Your Standard Purchases this month") is True


@pytest.mark.parametrize("sid", BANK_CARD)
def test_every_synthetic_layout_still_validates_reads_and_balances(sid):
    truth = pdf(sid)[1]
    assert validate.errors(truth.layout, for_model(pages(sid))) == []
    for k, part in enumerate(truth.parts or (truth,)):
        got = rules.apply(truth.layout, pages(sid), TODAY, part=k)
        assert got.error is None and got.unreadable == []
        assert (got.last4, got.opening, got.closing) == (part.last4, part.opening_cents, part.closing_cents)
        assert check.gap(truth.kind, got.opening, got.closing, [r.amount_cents for r in got.rows]) == 0


def test_a_label_holding_a_long_number_validates_reads_and_fingerprints_the_same():
    """The model saw the masked label, and validation, reading and the fingerprint all read the same masked text: an
    account label printed with a 9-digit number validates as masked, reads, and fingerprints alike each time."""
    spec = replace(SPECS["chase_checking"], account_label="Acct 123456789")
    data, truth = _draw(spec, spec.end)
    first, second = read_pdf(data)["pages"], read_pdf(data)["pages"]
    texts = [line_text(ln) for p in first for ln in p["lines"]]
    assert not any("123456789" in t for t in texts)
    # the label's number and the account cell beside it are one run across cells: the label is masked to "Acct ••"
    assert [c["text"] for c in first[0]["lines"][1]["cells"]] == ["Jane Doe", "Acct ••", "••7890"]
    layout = {**copy.deepcopy(truth.layout), "account_label": "Acct ••"}
    assert validate.errors(layout, for_model(first)) == []
    assert validate.errors(truth.layout, for_model(first)) == ["the account label isn't in the lines sent"]
    got = rules.apply(layout, first, TODAY)
    assert got.error is None and got.unreadable == [] and got.last4 == truth.last4
    assert check.gap(truth.kind, got.opening, got.closing, [r.amount_cents for r in got.rows]) == 0
    assert layouts.key_of(layouts.anchors(layout, first)) == layouts.key_of(layouts.anchors(layout, second))


@pytest.mark.parametrize("label, short", [("a", True), ("/", True), ("Da", True), ("ééé", True), ("Date", False),
                                          ("$ Amount", False), ("Acct ••6789", False)])
def test_a_label_needs_three_letters_and_something_left_after_normalizing(label, short):
    assert labels.short(label) is short
