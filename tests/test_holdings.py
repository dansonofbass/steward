"""Holdings (investment views spec): saving a day replaces that day's rows for the account and keeps other days; the
mix bar follows asset_classes, with a target-date fund split by its glide path."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from steward.db.models import Holding
from steward.services import asset_classes as ac
from steward.services import costs
from steward.services.holdings import TARGET_DATE_US_SHARE, Position, bar_parts, mix_bar, newest, replace_holdings
from tests.factories import make_account


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(costs, "table", lambda: {"VTI": costs.Fund("VTI", "Total Stock", Decimal("0.03"), "https://x.test", date(2026, 10, 28))})


def test_replacing_a_day_keeps_the_other_days_and_fills_the_ratios(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    replace_holdings(db, a.id, date(2026, 10, 1), [Position("VTI", "Total Stock", 1_000, 50_000)])
    replace_holdings(db, a.id, date(2026, 10, 2), [Position(" vti ", "Total Stock", 1_000, 51_000), Position(None, "Cash", 0, 1_000)])
    replace_holdings(db, a.id, date(2026, 10, 2), [Position("VTI", "Total Stock", 1_000, 52_000)])
    db.commit()
    rows = db.scalars(select(Holding).where(Holding.account_id == a.id).order_by(Holding.as_of)).all()
    assert [(h.as_of, h.symbol, h.market_value_cents, h.expense_ratio_bp) for h in rows] == [
        (date(2026, 10, 1), "VTI", 50_000, 3), (date(2026, 10, 2), "VTI", 52_000, 3)]
    assert [h.market_value_cents for h in newest(db, a.id)] == [52_000]


def test_a_position_without_a_name_takes_its_symbol(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    [h] = replace_holdings(db, a.id, date(2026, 10, 1), [Position("VXUS", "", 1_000, 10_000)])
    assert (h.symbol, h.name) == ("VXUS", "VXUS")


def test_newest_is_empty_without_holdings(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    assert newest(db, a.id) == []


def test_the_mix_bar_uses_overrides_then_the_builtins_and_unknown_is_other():
    hs = [Holding(symbol="VTI", market_value_cents=6_000), Holding(symbol="VXUS", market_value_cents=2_000),
          Holding(symbol="ZZZ", market_value_cents=1_000), Holding(symbol="QQQQ", market_value_cents=500),
          Holding(symbol=None, market_value_cents=500), Holding(symbol="BND", market_value_cents=0)]
    assert mix_bar(hs, {"ZZZ": "bond"}, 2026) == [
        {"class": "us_stock", "cents": 6_000}, {"class": "intl_stock", "cents": 2_000},
        {"class": "bond", "cents": 1_000}, {"class": "other", "cents": 1_000}]


def test_a_target_date_fund_splits_by_its_glide_path():
    stock = ac.glide_stock_share(2050, 2026)
    parts = dict(bar_parts("VFIFX", {}, 2026))
    assert parts["us_stock"] == pytest.approx(stock * TARGET_DATE_US_SHARE)
    assert parts["intl_stock"] == pytest.approx(stock * (1 - TARGET_DATE_US_SHARE))
    assert parts["bond"] == pytest.approx(1 - stock)
