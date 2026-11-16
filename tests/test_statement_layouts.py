"""Remembered layouts' fingerprint (spec P24): digit-free anchors from the header cells and section titles; a match
needs every anchor's words and the header within 3% of the page width; the most anchors win, then the most recent."""
import copy
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from steward.services.statements import layouts as L
from steward_gateway.evals.statement_set import build
from steward_pdf.sandbox import read_pdf
from tests.statement_files import pages, pdf


def test_anchors_hold_no_digit_and_make_a_key():
    a = L.anchors(pdf("chase_card")[1].layout, pages("chase_card"))
    texts = [h["text"] for h in a["header"]] + a["sections"]
    assert len(texts) >= L.MIN_ANCHORS and not any(re.search(r"\d", t) for t in texts)
    assert a["header"][0]["text"] == "date of transaction"              # a two-line header cell is one anchor
    assert re.fullmatch(r"p:[0-9a-f]{64}", L.key_of(a))


def test_next_months_statement_matches_and_a_redesign_doesnt():
    truth = pdf("chase_checking")[1]
    a = L.anchors(truth.layout, pages("chase_checking"))
    april = read_pdf(build("chase_checking", end=date(2026, 4, 30))[0])["pages"]
    assert L.matches(a, truth.layout, april)
    assert not L.matches(a, truth.layout, pages("chase_checking", "redesign"))


def test_a_header_moved_more_than_three_percent_doesnt_match():
    truth = pdf("boa_checking")[1]
    a = L.anchors(truth.layout, pages("boa_checking"))
    moved = pages("boa_checking")
    for p in moved:
        for ln in p["lines"]:
            if [c["text"] for c in ln["cells"]] == ["Date", "Description", "Amount"]:
                ln["cells"][1]["x0"] += 0.04 * p["width"]
                ln["cells"][1]["x1"] += 0.04 * p["width"]
    assert not L.matches(a, truth.layout, moved)


def test_a_reordered_header_doesnt_match():
    """F6 (spec Testing): the same header words in another order are another layout."""
    truth = pdf("boa_checking")[1]
    a = L.anchors(truth.layout, pages("boa_checking"))
    swapped = pages("boa_checking")
    for p in swapped:
        for ln in p["lines"]:
            if [c["text"] for c in ln["cells"]] == ["Date", "Description", "Amount"]:
                ln["cells"][0], ln["cells"][1] = ln["cells"][1], ln["cells"][0]
    assert not L.matches(a, truth.layout, swapped)


@dataclass
class Saved:
    anchors: str
    rules: str
    last_used_at: datetime | None
    created_at: datetime
    name: str


def test_the_most_anchors_win_then_the_most_recently_used():
    truth = pdf("chase_checking")[1]
    a = L.anchors(truth.layout, pages("chase_checking"))
    fewer = copy.deepcopy(a)
    fewer["sections"] = fewer["sections"][:1]
    t0, t1 = datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    rules = json.dumps(truth.layout)
    old = Saved(json.dumps(a), rules, t0, t0, "old")
    new = Saved(json.dumps(a), rules, t1, t0, "new")
    small = Saved(json.dumps(fewer), rules, t1, t1, "small")
    assert L.best([small, old, new], pages("chase_checking")).name == "new"
    assert L.best([small], pages("chase_checking")).name == "small"
    assert L.best([], pages("chase_checking")) is None


def test_a_data_row_tight_under_the_header_is_not_folded_into_an_anchor():
    """Tight leading puts the first row within UNDER of the header: its merchant words must not become wording."""
    truth = pdf("boa_checking")[1]
    normal = L.anchors(truth.layout, pages("boa_checking"))
    tight = pages("boa_checking")
    words = set()
    for p in tight:
        for i, ln in enumerate(p["lines"]):
            if [c["text"] for c in ln["cells"]] == ["Date", "Description", "Amount"]:
                title = p["lines"][i + 1]                       # a section title, tight under the header too
                row = copy.deepcopy(next(x for x in p["lines"][i + 2:] if re.search(r"\d", L.line_text(x))))
                words = {w for c in row["cells"] for w in c["text"].lower().split() if w.isalpha()}
                title["y"], row["y"] = ln["y"] + 9, ln["y"] + 10
                p["lines"].insert(i + 1, row)
    a = L.anchors(truth.layout, tight)
    assert a == normal and L.key_of(a) == L.key_of(normal)
    assert words and not words & {w for t in L._texts(a) for w in t.split()}
    tight2 = pages("boa_checking")
    for p in tight2:
        for i, ln in enumerate(p["lines"]):
            if [c["text"] for c in ln["cells"]] == ["Date", "Description", "Amount"]:
                p["lines"][i + 1]["y"] = ln["y"] + 10
    assert L.anchors(truth.layout, tight2) == normal
