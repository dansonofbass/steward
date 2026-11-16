from datetime import date

import pytest

from steward.db.models import AccountType, AssetClass, Holding
from steward.engine import Mix
from steward.services import asset_classes as ac
from tests.factories import make_account


def H(symbol, value, er=None, name="Fund"):
    return Holding(account_id=0, as_of=date(2026, 10, 1), symbol=symbol, name=name, shares_milli=1,
                   market_value_cents=value, expense_ratio_bp=er)


def test_builtin_classes_and_overrides():
    assert ac.resolve("vti", {}, 2026) == (Mix(1, 0, 0), "builtin")
    assert ac.resolve("BND", {}, 2026)[0] == Mix(0, 1, 0)
    assert ac.resolve("VMFXX", {}, 2026)[0] == Mix(0, 0, 1)
    assert ac.resolve("VXUS", {}, 2026)[0] == Mix(1, 0, 0)
    assert ac.resolve("ZZFUNDX", {}, 2026) == (None, "default")
    assert ac.resolve(None, {}, 2026) == (None, "default")
    assert ac.resolve("VTI", {"VTI": "bond"}, 2026) == (Mix(0, 1, 0), "override")


def test_target_date_funds_follow_the_glide_path():
    assert ac.glide_stock_share(2060, 2026) == pytest.approx(0.90)
    assert ac.glide_stock_share(2050, 2026) == pytest.approx(0.884)
    assert ac.glide_stock_share(2026, 2026) == pytest.approx(0.50)
    assert ac.glide_stock_share(2020, 2026) == pytest.approx(0.30 + 0.20 / 7)
    assert ac.glide_stock_share(2010, 2026) == pytest.approx(0.30)
    m, source = ac.resolve("VFIFX", {}, 2026)
    assert source == "builtin" and m.stock == pytest.approx(0.884) and m.bond == pytest.approx(0.116) and m.cash == 0
    assert ac.resolve("VTINX", {}, 2026)[0].stock == pytest.approx(0.30)


def test_account_mix_weights_holdings_and_fees():
    am = ac.account_mix([H("VTI", 6_000, 3), H("BND", 3_000, 5), H("ZZFUNDX", 1_000, 50)],
                        AccountType.brokerage_taxable, {}, 2026)
    assert am.mix.stock == pytest.approx(0.66) and am.mix.bond == pytest.approx(0.34) and am.mix.cash == pytest.approx(0)
    assert am.mix.fee_bp == 8                       # 0.6 x 3 + 0.3 x 5 + 0.1 x 50 = 8.3
    assert am.unknown == ("ZZFUNDX",) and not am.no_holdings


def test_cash_accounts_are_cash_and_empty_accounts_use_the_default():
    assert ac.account_mix([H("VTI", 5_000)], AccountType.checking, {}, 2026).mix == ac.CASH_MIX
    empty = ac.account_mix([], AccountType.k401, {}, 2026)
    assert empty.mix == ac.RETIREMENT_DEFAULT and empty.no_holdings
    assert ac.account_mix([H("VTI", 0)], AccountType.k401, {}, 2026).no_holdings
    assert ac.account_mix([H(None, 1_000, name="Stable Value")], AccountType.roth_ira, {}, 2026).unknown == ("Stable Value",)
    assert ac.default_mix(AccountType.brokerage_taxable) == ac.TAXABLE_DEFAULT
    assert ac.default_mix(AccountType.hsa) == ac.RETIREMENT_DEFAULT
    assert ac.default_mix(AccountType.savings) == ac.CASH_MIX


def test_blend_weights_by_balance():
    m = ac.blend([(3_000, Mix(1, 0, 0, 10)), (1_000, Mix(0, 1, 0, 2)), (-500, Mix(0, 0, 1))], ac.CASH_MIX)
    assert m.stock == pytest.approx(0.75) and m.bond == pytest.approx(0.25) and m.fee_bp == 8
    assert ac.blend([], ac.TAXABLE_DEFAULT) == ac.TAXABLE_DEFAULT


def test_latest_holdings_and_overrides(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    db.add_all([Holding(account_id=a.id, as_of=date(2026, 9, 1), symbol="OLD", name="Old", shares_milli=1, market_value_cents=1),
                Holding(account_id=a.id, as_of=date(2026, 10, 1), symbol="VTI", name="Total", shares_milli=1, market_value_cents=2)])
    db.add(AssetClass(symbol="ZZFUNDX", asset_class="bond"))
    db.commit()
    assert [h.symbol for h in ac.latest_holdings(db)[a.id]] == ["VTI"]
    assert ac.overrides(db) == {"ZZFUNDX": "bond"}
