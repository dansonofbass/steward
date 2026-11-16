from datetime import date
import pytest

from steward.services.importers.money import parse_cents, parse_date


@pytest.mark.parametrize("text,cents", [
    ("-12.34", -1234), ("12.34", 1234), ("$1,234.56", 123456), ("-$1,234.56", -123456),
    ("(12.34)", -1234), ("($0.99)", -99), (" 5 ", 500), ("0", 0), ("-0.01", -1), ("1234", 123400),
])
def test_parse_cents(text, cents):
    assert parse_cents(text) == cents


@pytest.mark.parametrize("bad", ["12.345", "abc", "", "1,2,3", "12.3.4", "--5"])
def test_parse_cents_rejects(bad):
    with pytest.raises(ValueError):
        parse_cents(bad)


def test_parse_date_formats():
    fmts = ("%m/%d/%Y", "%Y-%m-%d")
    assert parse_date("10/03/2026", fmts) == date(2026, 10, 3)
    assert parse_date("2026-10-03", fmts) == date(2026, 10, 3)
    with pytest.raises(ValueError):
        parse_date("03-10-2026", fmts)


@pytest.mark.parametrize("text,cents", [("+5", 500), ("-.50", -50), (".5", 50), ("+$1,000.00", 100000)])
def test_parse_cents_plus_and_bare_decimals(text, cents):
    assert parse_cents(text) == cents


@pytest.mark.parametrize("bad", ["1$2", "5$", "(-12.34)", "٣.٠٠", "$$5", "(12.34", "+-5"])
def test_parse_cents_rejects_more(bad):
    with pytest.raises(ValueError):
        parse_cents(bad)
