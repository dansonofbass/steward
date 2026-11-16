"""Fund costs (investment views spec, Costs): the override, then the table, then nothing; ratios kept exact as
percents; a holding's basis points rounded for the Plan; an override refills every holding of that symbol."""
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from steward.db.models import ExpenseRatioOverride, Holding
from steward.services import costs
from tests.factories import make_account

NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)
TABLE = {"VTI": costs.Fund("VTI", "Vanguard Total Stock Market ETF", Decimal("0.03"), "https://x.test", date(2026, 10, 28)),
         "FXAIX": costs.Fund("FXAIX", "Fidelity 500 Index Fund", Decimal("0.015"), "https://y.test", date(2026, 10, 28))}
EXPECTED = {"VTI", "VOO", "VXUS", "BND", "VEA", "VWO", "VTSAX", "VFIAX", "VBTLX", "VTTVX", "VTHRX", "VTTHX", "VFORX",
            "VTIVX", "VFIFX", "FXAIX", "FZROX", "FTIHX", "FSKAX", "SWTSX", "SCHB", "SCHD", "SWPPX", "IVV", "AGG", "IEFA",
            "IEMG", "ITOT"}


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(costs, "table", lambda: TABLE)


def test_the_lookup_order_is_the_override_then_the_table_then_nothing(table):
    ovr = {"VTI": Decimal("0.05")}
    assert costs.lookup(" vti ", ovr) == (Decimal("0.05"), "override")
    assert costs.lookup("FXAIX", ovr) == (Decimal("0.015"), "table")
    assert costs.lookup("ZZFUNDX", ovr) == (None, None)
    assert costs.lookup(None, ovr) == (None, None)


def test_symbols_lose_spaces_case_and_marks():
    assert costs.clean_symbol(" spaxx** ") == "SPAXX"
    assert costs.clean_symbol("brk.b") == "BRK.B"
    assert costs.clean_symbol("**") is None and costs.clean_symbol("") is None and costs.clean_symbol(None) is None
    assert costs.clean_symbol("A" * 21) is None


def test_a_years_cost_is_the_value_times_the_ratio_rounded_half_up():
    assert costs.yearly_cost_cents(108_000_00, Decimal("0.03")) == 32_40
    assert costs.yearly_cost_cents(100_00, Decimal("0.015")) == 2          # 1.5 cents rounds up
    assert costs.to_bp(Decimal("0.015")) == 2 and costs.to_bp(Decimal("0.03")) == 3 and costs.to_bp(Decimal("0")) == 0
    assert costs.pct_text(Decimal("0.040")) == "0.04" and costs.pct_text(Decimal("0")) == "0"


def test_a_ratio_is_a_plain_percent_of_at_most_5():
    for text, want in (("0.04", Decimal("0.04")), ("0", Decimal("0")), (" 1.25 ", Decimal("1.25")), ("5", Decimal("5"))):
        assert costs.parse_ratio(text) == want
    for bad in ("4%", "-0.1", "0.0001", "5.01", "abc", "", 0.04, None):
        with pytest.raises(ValueError, match=re.escape(costs.RATIO_RULE)):
            costs.parse_ratio(bad)


def test_filling_takes_the_override_then_the_table_then_leaves_it_empty(db, table):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    rows = [Holding(account_id=a.id, as_of=date(2026, 10, 1), symbol=s, name=s or "Cash", shares_milli=1, market_value_cents=100)
            for s in ("VTI", "FXAIX", "ZZFUNDX", None)]
    db.add_all(rows)
    db.add(ExpenseRatioOverride(symbol="VTI", ratio_pct="0.05", updated_at=NOW, updated_by=1))
    db.flush()
    costs.fill_ratios(db, rows)
    assert [h.expense_ratio_bp for h in rows] == [5, 2, None, None]


def test_an_override_refills_every_holding_of_its_symbol_and_clearing_it_goes_back_to_the_table(db, table):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    b = make_account(db, "Roth IRA", type="roth_ira", owner="jr")
    for acct, day in ((a, date(2026, 10, 1)), (b, date(2026, 10, 2)), (a, date(2026, 9, 1))):
        db.add(Holding(account_id=acct.id, as_of=day, symbol="VTI", name="Total Stock", shares_milli=1, market_value_cents=100))
    db.add(Holding(account_id=a.id, as_of=date(2026, 10, 1), symbol="ACMEX", name="Stable Value", shares_milli=1, market_value_cents=100))
    db.commit()
    assert costs.set_override(db, " acmex ", "0.45", 1, NOW) == "ACMEX"
    assert costs.set_override(db, "VTI", "0.040", 1, NOW) == "VTI"
    db.commit()
    assert {h.expense_ratio_bp for h in db.scalars(select(Holding).where(Holding.symbol == "VTI"))} == {4}
    assert db.scalar(select(Holding.expense_ratio_bp).where(Holding.symbol == "ACMEX")) == 45
    assert db.get(ExpenseRatioOverride, "VTI").ratio_pct == "0.04"
    costs.set_override(db, "VTI", None, 1, NOW)
    db.commit()
    assert {h.expense_ratio_bp for h in db.scalars(select(Holding).where(Holding.symbol == "VTI"))} == {3}
    assert db.get(ExpenseRatioOverride, "VTI") is None


def test_an_override_needs_a_symbol_and_a_ratio(db, table):
    with pytest.raises(ValueError, match=re.escape(costs.SYMBOL_RULE)):
        costs.set_override(db, "**", "0.1", 1, NOW)
    with pytest.raises(ValueError, match=re.escape(costs.RATIO_RULE)):
        costs.set_override(db, "VTI", "lots", 1, NOW)


def test_the_fund_table_lists_each_fund_once_with_its_source():
    raw = json.loads(costs.DATA.read_text())
    symbols = [f["symbol"] for f in raw["funds"]]
    assert len(symbols) == len(set(symbols)) and set(symbols) == EXPECTED
    for f in raw["funds"]:
        assert f["symbol"] == costs.clean_symbol(f["symbol"]) and f["name"].strip()
        costs.parse_ratio(f["ratio_pct"])
        assert f["source"].startswith("https://")
        assert f["checked"] is None or date(2026, 10, 1) <= date.fromisoformat(f["checked"]) <= date(2027, 12, 31)
    costs.table.cache_clear()
    assert set(costs.table()) == {f["symbol"] for f in raw["funds"] if f["checked"] is not None}


def test_every_fund_in_the_shipped_table_is_checked_so_the_table_knows_them_all():
    costs.table.cache_clear()
    t = costs.table()
    assert set(t) == EXPECTED   # an unchecked entry drops out; a re-check that can't confirm one must change this pin
    assert all(f.checked == date(2026, 10, 28) for f in t.values())
    assert {s: costs.pct_text(t[s].ratio_pct) for s in ("VTI", "VWO", "VFIFX", "FXAIX", "FZROX", "SCHD")} == {
        "VTI": "0.03", "VWO": "0.06", "VFIFX": "0.08", "FXAIX": "0.015", "FZROX": "0", "SCHD": "0.06"}
