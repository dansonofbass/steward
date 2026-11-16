from datetime import date

from steward.services.cashflow import cashflow
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 13)


def _fixture(db):
    chk = make_account(db, "Checking", type="checking")
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    for d, cents, raw, cat in ((date(2026, 8, 1), 500_000, "PAYROLL", "income"), (date(2026, 8, 10), -120_000, "GROCER", "groceries"),
                               (date(2026, 8, 11), -30_000, "DINER", "dining"), (date(2026, 9, 1), 500_000, "PAYROLL", "income"),
                               (date(2026, 9, 15), -200_000, "AIRLINE", "travel"), (date(2026, 9, 20), 10_000, "GIFT", "gifts"),
                               (date(2026, 9, 28), -50_000, "IRS", "taxes"), (date(2026, 10, 2), -40_000, "GROCER", "groceries"),
                               (date(2026, 7, 31), -1, "BEFORE", "shopping")):
        make_txn(db, chk, d, cents, raw, category=cat)
    make_txn(db, chk, date(2026, 9, 3), -100_000, "TO SAVINGS", category="transfer", is_transfer=True)
    make_txn(db, chk, date(2026, 9, 4), -5_000, "CLIENT LUNCH", category="dining", is_business=True)
    make_txn(db, biz, date(2026, 9, 5), 300_000, "CLIENT", category="business_income", is_business=True)


def test_monthly_totals_match_a_hand_sum(db):
    _fixture(db)
    months = cashflow(db, TODAY, 3)
    assert [m["month"] for m in months] == ["2026-08", "2026-09", "2026-10"]
    aug, sep, oct_ = months
    assert (aug["in_cents"], aug["out_cents"], aug["net_cents"]) == (500_000, 150_000, 350_000)
    assert [c["category"] for c in aug["categories"]] == ["groceries", "dining", "income"]
    assert (sep["in_cents"], sep["out_cents"], sep["net_cents"]) == (510_000, 250_000, 260_000)
    assert [c["category"] for c in sep["categories"]] == ["travel", "taxes", "income", "gifts"]
    assert sep["categories"][0] == {"category": "travel", "in_cents": 0, "out_cents": 200_000}
    assert (oct_["in_cents"], oct_["out_cents"], oct_["net_cents"]) == (0, 40_000, -40_000)


def test_empty_months_are_still_listed(db):
    months = cashflow(db, TODAY, 2)
    assert months == [{"month": "2026-09", "in_cents": 0, "out_cents": 0, "net_cents": 0, "categories": []},
                      {"month": "2026-10", "in_cents": 0, "out_cents": 0, "net_cents": 0, "categories": []}]


def test_cashflow_api(frozen, signed_in, db):
    _fixture(db)
    body = signed_in.get("/api/b/ours/cashflow").json()
    assert body["as_of"] == "2026-10-13" and len(body["months"]) == 12
    assert body["months"][0]["month"] == "2025-11" and body["months"][-1]["month"] == "2026-10"
    assert signed_in.get("/api/b/ours/cashflow?months=3").json()["months"][1]["out_cents"] == 250_000
    for bad_value in ("0", "61", "abc", "-1", "²"):
        r = signed_in.get(f"/api/b/ours/cashflow?months={bad_value}")
        assert r.status_code == 422 and r.json() == {"error": "Choose between 1 and 60 months."}


def test_cashflow_needs_sign_in(client):
    assert client.get("/api/b/ours/cashflow").status_code == 401


def test_investment_account_rows_are_not_cash_flow(db):
    _fixture(db)
    before = cashflow(db, TODAY, 3)
    k401 = make_account(db, "401(k)", type="k401", owner="jr")
    brk = make_account(db, "Brokerage", type="brokerage_taxable")
    make_txn(db, k401, date(2026, 9, 15), 150_000, "PAYROLL CONTRIBUTION", category="income")
    make_txn(db, brk, date(2026, 9, 20), 40_000, "DIVIDEND", category="income")
    make_txn(db, brk, date(2026, 9, 21), -40_000, "REINVEST", category="shopping")
    assert cashflow(db, TODAY, 3) == before


def test_a_split_row_counts_its_personal_share(db):
    from steward.services.cashflow import cashflow
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 9, 4), -10_000, "MOBILE ONE WIRELESS", category="utilities", business_pct=40)
    make_txn(db, chk, date(2026, 9, 5), -1_001, "HALF CAFE", category="dining", business_pct=50)
    make_txn(db, chk, date(2026, 9, 6), -5_000, "ALL BUSINESS", category="dining", is_business=True)
    sept = next(m for m in cashflow(db, date(2026, 10, 13), 2) if m["month"] == "2026-09")
    assert sept["out_cents"] == 6_000 + 500                  # 1,001 less its 501 business share
