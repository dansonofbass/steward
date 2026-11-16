"""GET /business and GET /business/lines/{line} (spec 5: every line opens its transactions)."""
from datetime import date

from steward.db.models import Owner
from tests.factories import login, make_account, make_txn


def test_the_report_and_a_lines_transactions(frozen, signed_in, db):
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.business)
    make_txn(db, bchk, date(2026, 3, 3), 300_000, "ACH CLIENT INV 1", category="business_income", is_business=True)
    t = make_txn(db, bchk, date(2026, 4, 3), -2_900, "NOTEFLOW PRO", category="subscriptions", business_pct=50)
    r = signed_in.get("/api/b/ours/business").json()
    assert set(r) == {"year", "this_year", "through", "type", "income_cents", "expenses_cents", "profit_cents",
                      "lines", "range", "left_out", "using_note", "home_office_limited"}
    assert r["this_year"] == 2026
    assert (r["year"], r["through"], r["income_cents"], r["profit_cents"]) == (2026, "2026-10-13", 300_000, 298_550)
    assert [l["key"] for l in r["lines"]] == ["income", "software"]
    assert r["range"] == {"year": 2026, "ytd_cents": 298_550, "low_cents": 298_550, "high_cents": 298_550,
                          "mid_cents": 298_550, "entered": False, "cash_ytd_cents": 298_550,
                          "cash_low_cents": 298_550, "cash_high_cents": 298_550, "cash_mid_cents": 298_550,
                          "ask_expect": False}
    body = signed_in.get("/api/b/ours/business/lines/software").json()
    assert body["line"] == {"key": "software", "number": "27b", "label": "Software"}
    assert [(x["id"], x["share_cents"], x["business_pct"]) for x in body["transactions"]] == [(t.id, -1_450, 50)]
    r = signed_in.get("/api/b/ours/business/lines/yacht")
    assert r.status_code == 404 and r.json() == {"error": "No such line."}
    last = signed_in.get("/api/b/ours/business?year=2025").json()
    assert (last["through"], last["year"], last["this_year"]) == ("2025-12-31", 2025, 2026)   # M6: the household's year
    assert signed_in.get("/api/b/ours/business?year=2024").status_code == 422


def test_parent_books_have_no_business_view(frozen, client, margaret):
    login(client, "jr")
    for path in ("/business", "/business/lines/income"):
        r = client.get("/api/b/margaret-ellis" + path)
        assert r.status_code == 404 and r.json() == {"error": "This book doesn't have that."}
