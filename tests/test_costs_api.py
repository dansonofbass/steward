"""PUT /expense-ratios (investment views spec, "cost unknown · Add"): household books only."""
from datetime import date

from sqlalchemy import select

from steward.db.models import ExpenseRatioOverride, Holding
from tests.factories import make_account

RULE = "Enter the fund's expense ratio as a percent, like 0.04."


def test_put_saves_an_override_and_fills_the_holdings(frozen, signed_in, db):
    a = make_account(db, "401(k)", type="k401", owner="jr")
    db.add(Holding(account_id=a.id, as_of=date(2026, 10, 1), symbol="ACMEX", name="Stable Value", shares_milli=1, market_value_cents=100))
    db.commit()
    r = signed_in.put("/api/b/ours/expense-ratios", json={"symbol": "acmex", "ratio_pct": "0.45"})
    assert r.status_code == 200 and r.json() == {"symbol": "ACMEX", "ratio_pct": "0.45"}
    db.rollback()
    assert db.scalar(select(Holding.expense_ratio_bp)) == 45
    r = signed_in.put("/api/b/ours/expense-ratios", json={"symbol": "ACMEX", "ratio_pct": None})
    assert r.json() == {"symbol": "ACMEX", "ratio_pct": None}
    db.rollback()
    assert db.get(ExpenseRatioOverride, "ACMEX") is None


def test_put_checks_its_values(frozen, signed_in):
    for body, msg in (({"symbol": "VTI", "ratio_pct": "0.0001"}, RULE), ({"symbol": "VTI"}, RULE),
                      ({"symbol": "VTI", "ratio_pct": 0.04}, RULE), ({"symbol": "", "ratio_pct": "0.04"}, "Enter the fund's ticker symbol."),
                      ({"symbol": 5, "ratio_pct": "0.04"}, "Enter the fund's ticker symbol.")):
        r = signed_in.put("/api/b/ours/expense-ratios", json=body)
        assert r.status_code == 422 and r.json() == {"error": msg}, body


def test_a_parent_book_has_no_expense_ratios(frozen, client, margaret):
    from tests.factories import login
    login(client, "jr")
    assert client.put("/api/b/margaret-ellis/expense-ratios", json={"symbol": "VTI", "ratio_pct": "0.04"}).status_code == 404
