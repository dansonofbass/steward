"""A positions CSV (investment views spec, From a positions CSV): columns guessed from their names, totals and pending
rows dropped, rows without a value skipped, the balance check, the remembered mapping, and replace for the date."""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import Holding, PositionsImport, PositionsMapping
from steward.services import positions as P
from steward.services.accounts import record_balance
from tests.factories import make_account

NOW = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)
SIMPLE = ("Symbol,Description,Quantity,Market Value,Cost Basis\n"
          "VTI,Vanguard Total Stock Market ETF,400,\"$108,000.00\",\"$90,000.00\"\n"
          "VXUS,Vanguard Total International Stock ETF,700,\"$45,000.00\",\n"
          "Account Total,,,\"$153,000.00\",\n")
M = {"symbol": "Symbol", "name": "Description", "shares": "Quantity", "value": "Market Value", "cost_basis": "Cost Basis"}


def test_the_columns_are_guessed_from_their_names():
    assert P.guess_mapping(["Symbol", "Description", "Quantity", "Market Value ($)", "Cost Basis Total"]) == {
        "symbol": "Symbol", "name": "Description", "shares": "Quantity", "value": "Market Value ($)", "cost_basis": "Cost Basis Total"}
    assert P.guess_mapping(["Ticker", "Name", "Shares", "Current Value"]) == {
        "symbol": "Ticker", "name": "Name", "shares": "Shares", "value": "Current Value", "cost_basis": None}
    assert P.guess_mapping(["Fund", "Balance"])["value"] is None


def test_a_broker_export_with_a_title_line_marks_pending_totals_and_a_footer_reads_cleanly():
    """Review Focus 1."""
    text = ('"Positions for account Brokerage ...123 as of 10/28/2026"\n'
            ",\n"
            "Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Total\n"
            'SPAXX**,HELD IN MONEY MARKET,,,"$1,200.50",\n'
            ' vti ,VANGUARD TOTAL STOCK MARKET ETF,400.1234,$270.00,"$108,033.32","$90,000.00"\n'
            'VXUS,VANGUARD TOTAL INTL STOCK ETF,700,$64.29,"$45,003.00",\n'
            'Pending Activity,,,,"$500.00",\n'
            ',Vanguard Total Bond Market Index Fund,10,,"1,000.004",\n'
            'Account Total,,,,"$154,736.82",\n'
            '"The data and information in this spreadsheet is provided to you solely for your use."\n'
            '"Brokerage services are provided by a made-up broker."\n')
    body = P.from_header(text)
    m = P.guess_mapping(P.read_rows(body)[0])
    assert m == {"symbol": "Symbol", "name": "Description", "shares": "Quantity", "value": "Current Value", "cost_basis": "Cost Basis Total"}
    got, skipped = P.parse_positions(body, m)
    assert [(p.symbol, p.name, p.shares_milli, p.value_cents, p.cost_basis_cents) for p in got] == [
        ("SPAXX", "HELD IN MONEY MARKET", 0, 1_200_50, None),
        ("VTI", "VANGUARD TOTAL STOCK MARKET ETF", 400_123, 108_033_32, 90_000_00),
        ("VXUS", "VANGUARD TOTAL INTL STOCK ETF", 700_000, 45_003_00, None),
        (None, "Vanguard Total Bond Market Index Fund", 10_000, 1_000_00, None)]
    assert skipped == 4


def test_amounts_in_parentheses_are_negative_and_blanks_or_dashes_are_no_value():
    text = "Symbol,Value\nAAA,(12.00)\nBBB,--\nCCC,\nDDD,n/a\n"
    got, skipped = P.parse_positions(text, {"symbol": "Symbol", "name": None, "shares": None, "value": "Value", "cost_basis": None})
    assert [(p.symbol, p.value_cents) for p in got] == [("AAA", -12_00)] and skipped == 3


def test_odd_signs_and_huge_figures_never_break_a_parse():
    text = "Symbol,Qty,Value\nAAA,--5,1.00\nBBB,+5,2.00\nCCC,-5,3.00\nDDD,1,%s\nEEE,%s,4.00\n" % ("9" * 30, "9" * 30)
    m = {"symbol": "Symbol", "name": None, "shares": "Qty", "value": "Value", "cost_basis": None}
    got, skipped = P.parse_positions(text, m)
    assert [(p.symbol, p.shares_milli, p.value_cents) for p in got] == [
        ("AAA", 0, 100), ("BBB", 5000, 200), ("CCC", -5000, 300), ("EEE", 0, 400)]
    assert skipped == 1


def test_more_than_2000_rows_is_refused():
    text = "Symbol,Value\n" + "".join(f"S{i},1.00\n" for i in range(P.MAX_POSITIONS + 1))
    with pytest.raises(ValueError, match="more than 2,000 rows"):
        P.parse_positions(text, {"symbol": "Symbol", "name": None, "shares": None, "value": "Value", "cost_basis": None})


def test_a_mapping_names_a_value_and_a_symbol_or_name_that_the_file_has():
    header = ["Symbol", "Value"]
    assert P.usable({**dict.fromkeys(P.FIELDS), "symbol": "Symbol", "value": "Value"}, header)
    assert not P.usable({**dict.fromkeys(P.FIELDS), "symbol": "Symbol"}, header)
    assert not P.usable({**dict.fromkeys(P.FIELDS), "value": "Value"}, header)
    assert not P.usable({**dict.fromkeys(P.FIELDS), "symbol": "Ticker", "value": "Value"}, header)
    for bad in ("[1]", '{"value": 3}', '{"color": "Value"}', "not json"):
        with pytest.raises(ValueError, match="column mapping"):
            P.mapping_from(bad)
    assert P.mapping_from('{"value": "Value", "symbol": ""}') == {**dict.fromkeys(P.FIELDS), "value": "Value"}


def test_the_first_preview_asks_to_confirm_the_guess(db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    p = P.preview(db, a, SIMPLE, None)
    assert p["needs_mapping"] and not p["remembered"]
    assert p["mapping"] == M and p["headers"] == ["Symbol", "Description", "Quantity", "Market Value", "Cost Basis"]
    assert p["sample"][0] == ["VTI", "Vanguard Total Stock Market ETF", "400", "$108,000.00", "$90,000.00"]


def test_a_preview_with_a_mapping_totals_the_positions_against_the_balance(db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    record_balance(db, a.id, date(2026, 10, 12), 153_290_00)
    p = P.preview(db, a, SIMPLE, M)
    assert (p["needs_mapping"], p["count"], p["total_cents"], p["skipped"]) == (False, 2, 153_000_00, 1)
    assert (p["balance_cents"], p["balance_as_of"], p["difference_cents"]) == (153_290_00, "2026-10-12", -290_00)
    assert [r["symbol"] for r in p["positions"]] == ["VTI", "VXUS"]


def test_saving_replaces_that_days_holdings_records_the_import_and_remembers_the_columns(db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    P.commit(db, a, SIMPLE, "betterment.csv", M, date(2026, 10, 13), 1, NOW)
    out = P.commit(db, a, SIMPLE.replace("$45,000.00", "$46,000.00"), "C:\\Users\\jr\\betterment.csv", M, date(2026, 10, 13), 1, NOW)
    db.commit()
    assert out == {"count": 2, "total_cents": 154_000_00, "as_of": "2026-10-13", "first": False}
    rows = db.scalars(select(Holding).where(Holding.account_id == a.id)).all()
    assert sorted((h.symbol, h.market_value_cents) for h in rows) == [("VTI", 108_000_00), ("VXUS", 46_000_00)]
    imports = db.scalars(select(PositionsImport).order_by(PositionsImport.id)).all()
    assert [(i.filename, i.row_count, i.as_of) for i in imports] == [("betterment.csv", 2, date(2026, 10, 13))] * 2
    assert {h.import_id for h in rows} == {imports[1].id}
    assert json.loads(db.get(PositionsMapping, f"acct:{a.id}").mapping) == M
    p = P.preview(db, a, SIMPLE, None)
    assert p["remembered"] and not p["needs_mapping"] and p["count"] == 2


def test_the_first_import_into_an_account_without_holdings_says_so(db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    assert P.commit(db, a, SIMPLE, "b.csv", M, date(2026, 10, 13), 1, NOW)["first"] is True


def test_a_connected_accounts_columns_are_remembered_for_its_institution_and_a_manual_ones_for_itself(db):
    x = make_account(db, "Brokerage", type="brokerage_taxable", source="simplefin", institution_name="Robo Invest")
    y = make_account(db, "Roth IRA", type="roth_ira", owner="jr", source="simplefin", institution_name="Robo Invest")
    m1 = make_account(db, "Betterment", type="brokerage_taxable")
    m2 = make_account(db, "Old 401(k)", type="k401", owner="jr")
    assert P.mapping_key(x) == P.mapping_key(y) == f"inst:{x.institution_id}"
    assert P.mapping_key(m1) != P.mapping_key(m2)
    P.commit(db, x, SIMPLE, "x.csv", M, date(2026, 10, 13), 1, NOW)
    assert P.preview(db, y, SIMPLE, None)["remembered"] is True
    assert P.preview(db, m1, SIMPLE, None)["remembered"] is False


def test_a_remembered_mapping_is_set_aside_when_the_new_file_lacks_its_columns(db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    P.commit(db, a, SIMPLE, "b.csv", M, date(2026, 10, 13), 1, NOW)
    p = P.preview(db, a, "Ticker,Name,Current Value\nVTI,Total,1.00\n", None)
    assert p["needs_mapping"] and p["mapping"]["symbol"] == "Ticker"


def test_a_file_with_nothing_of_value_is_refused(db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    with pytest.raises(ValueError, match="No positions with a value"):
        P.preview(db, a, "Symbol,Market Value\nVTI,\n", {**dict.fromkeys(P.FIELDS), "symbol": "Symbol", "value": "Market Value"})
