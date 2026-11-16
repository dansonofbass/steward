"""The synthetic set (spec, Testing; P53): byte-stable PDFs whose truth adds up, and the variants."""
from steward_boundary.statements_wire import shape_errors
from steward_gateway.evals.statement_set import BANK_CARD, VARIANTS, build


def test_each_statement_builds_the_same_bytes_twice_and_its_truth_adds_up():
    for sid in BANK_CARD:
        a, truth = build(sid)
        b, _ = build(sid)
        assert a == b and a.startswith(b"%PDF-")
        for part in truth.parts or (truth,):
            moved = sum(r["amount_cents"] for r in part.rows)
            want = part.closing_cents - part.opening_cents
            assert (-moved if truth.kind == "card" else moved) == want, sid
        assert truth.rows and all(r["page"] >= 1 for r in truth.rows)


def test_each_truth_layout_passes_the_wire_shape():
    for sid in BANK_CARD:
        assert shape_errors(build(sid)[1].layout) == [], sid


def test_the_variants():
    assert set(VARIANTS) == {"password", "permissions", "redesign", "off", "drifted", "scan", "mixed"}
    assert build("chase_checking", variant="off")[1].misprint_cents == 1240
    assert build("chase_checking", variant="redesign")[1].layout["table"]["columns"][1]["header"] == "TRANSACTION DETAIL"
    drifted = build("chase_checking", variant="drifted")[1]
    assert [s["title"] for s in drifted.layout["table"]["sections"]][-2] == "OTHER WITHDRAWALS"
    pw, _ = build("chase_checking", variant="password")
    assert pw.startswith(b"%PDF-") and pw != build("chase_checking")[0]
    pages, truth = build("pages61")
    assert truth.pages == 61 and pages.startswith(b"%PDF-")
    assert build("receipt")[1].kind == "receipt"


def test_amex_spans_december_and_january():
    truth = build("amex_card")[1]
    assert (truth.period[0].month, truth.period[1].month) == (12, 1)
    assert {r["date"][:7] for r in truth.rows} == {"2025-12", "2026-01"}


def test_the_investment_and_loan_layouts():
    from steward_gateway.evals.statement_set import HOLDINGS, LOANS
    for sid in HOLDINGS:
        data, truth = build(sid)
        assert data == build(sid)[0] and truth.holdings and truth.layout["holdings"]["columns"]
        assert abs(truth.total_cents - sum(h["value_cents"] for h in truth.holdings)) <= 100
        assert truth.closing_cents == truth.total_cents
    assert any(h["cash"] for h in build("fidelity_brokerage")[1].holdings)
    for sid in LOANS:
        truth = build(sid)[1]
        assert truth.kind == "loan" and truth.layout["table"] is None and truth.layout["holdings"] is None
        assert truth.closing_cents > 0
    off = build("fidelity_brokerage", variant="off")[1]
    assert off.total_cents - sum(h["value_cents"] for h in off.holdings) > 100
