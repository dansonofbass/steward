"""GET /accounts/{id}/investment (investment views spec, The investment account page)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from steward.services import costs
from steward.services.accounts import record_balance
from steward.services.holdings import Position, replace_holdings
from tests.factories import make_account, make_txn


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(costs, "table", lambda: {"VTI": costs.Fund("VTI", "x", Decimal("0.03"), "https://x.test", date(2026, 10, 28))})


def test_a_brokerage_page_has_its_figures_holdings_and_costs_and_no_contributions(frozen, signed_in, db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    a.advisory_fee_bp = 25
    record_balance(db, a.id, date(2025, 12, 31), 170_000_00)
    record_balance(db, a.id, date(2026, 10, 13), 180_000_00)
    replace_holdings(db, a.id, date(2026, 10, 13), [Position("VTI", "Vanguard Total Stock Market ETF", 400_000, 108_000_00),
                                                     Position("ACMEX", "Acme Stable Value", 0, 72_000_00)])
    db.commit()
    body = signed_in.get(f"/api/b/ours/accounts/{a.id}/investment").json()
    assert (body["manual"], body["sends"], body["institution"], body["contributions"]) == (True, None, "Betterment", None)
    assert (body["year"]["change_cents"], body["year"]["change_pct"], body["year"]["from_jan1"]) == (10_000_00, 5.9, True)
    h = body["holdings"]
    assert [(r["symbol"], r["ratio_pct"], r["ratio_from"], r["cost_cents"]) for r in h["rows"]] == [
        ("VTI", "0.03", "table", 32_40), ("ACMEX", None, None, None)]
    assert (h["source"], h["filename"], h["as_of"], h["total_cents"], h["unknown"]) == ("feed", None, "2026-10-13", 180_000_00, 1)
    assert h["mix"] == [{"class": "us_stock", "cents": 108_000_00}, {"class": "other", "cents": 72_000_00}]
    assert body["advisory"] == {"fee_bp": 25, "cost_cents": 450_00}
    assert body["all_in"] == {"cents": 482_40, "pct": "0.27"}   # (32.40 + 450.00) / 180,000


def test_a_row_written_before_this_phase_keeps_its_stored_ratio(frozen, signed_in, db):
    from steward.db.models import Holding
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    db.add(Holding(account_id=a.id, as_of=date(2026, 10, 1), symbol="ZZFUNDX", name="Plan Fund", shares_milli=1,
                   market_value_cents=10_000_00, expense_ratio_bp=20))
    db.commit()
    [row] = signed_in.get(f"/api/b/ours/accounts/{a.id}/investment").json()["holdings"]["rows"]
    assert (row["ratio_pct"], row["ratio_from"], row["cost_cents"]) == ("0.2", "stored", 20_00)


def test_a_connected_401ks_page_says_what_the_bank_sends_and_has_its_contributions(frozen, signed_in, db):
    k = make_account(db, "401(k)", type="k401", owner="jr", source="simplefin", institution_name="Workplace")
    k.transactions_seen_at = datetime(2026, 10, 12, 13, tzinfo=timezone.utc)
    record_balance(db, k.id, date(2026, 10, 13), 50_000_00)
    make_txn(db, k, date(2026, 9, 1), 1_000_00, "EMPLOYEE DEFERRAL")
    make_txn(db, k, date(2026, 9, 1), 500_00, "EMPLOYER MATCH")
    db.commit()
    body = signed_in.get(f"/api/b/ours/accounts/{k.id}/investment").json()
    assert body["sends"] == {"holdings": False, "transactions": True} and body["institution"] == "Workplace"
    assert body["holdings"] is None and body["all_in"] is None and body["advisory"] is None
    c = body["contributions"]
    assert c["this_year"] == {"you_cents": 1_000_00, "you_from": "deposits", "match_cents": 500_00,
                              "match_from": "deposits", "rollover_cents": 0, "out_cents": 0}
    assert c["missing"] is False and (c["line"]["kind"], c["line"]["in_cents"], c["line"]["limit_cents"]) == ("k401", 1_000_00, 2_450_000)
    assert body["since"] == "2026-10-13" and len(body["series"]) == 1 and body["year"]["from_jan1"] is False


def test_an_advisory_fee_without_holdings_is_figured_on_the_balance(frozen, signed_in, db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    a.advisory_fee_bp = 25
    record_balance(db, a.id, date(2026, 10, 13), 84_210_00)
    db.commit()
    body = signed_in.get(f"/api/b/ours/accounts/{a.id}/investment").json()
    assert body["holdings"] is None and body["advisory"] == {"fee_bp": 25, "cost_cents": 210_53} and body["all_in"] is None


def test_only_an_investment_account_has_this_page(frozen, signed_in, db):
    chk = make_account(db, "Checking")
    assert signed_in.get(f"/api/b/ours/accounts/{chk.id}/investment").status_code == 409
    assert signed_in.get("/api/b/ours/accounts/999/investment").status_code == 404


def test_a_parent_book_has_no_investment_pages(frozen, client, margaret):
    from tests.factories import login
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/accounts/1/investment").status_code == 404
