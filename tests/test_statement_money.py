"""Statement amounts and dates (spec P18, P19; plan Engineering choice 2)."""
from datetime import date

import pytest

from steward.services.statements import dates as D
from steward.services.statements.money import amounts, parse_amount
from steward_boundary import statements_wire as W


@pytest.mark.parametrize("text, cents", [
    ("1,234.56", 123456), ("$1,234.56", 123456), ("-1,234.56", -123456), ("-$1,234.56", -123456),
    ("$-12.40", -1240), ("(12.40)", -1240), ("($12.40)", -1240), ("12.40-", -1240), ("12.40 CR", -1240),
    ("12.40CR", -1240), ("12.40 cr", -1240), ("12.40 DR", 1240), ("+$95.00", 9500), ("0.00", 0)])
def test_every_printed_style_reads(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "12.4", "1,23.45", "12", "abc", "03/04/2026", "$", "12.40.00",
                                  "99,999,999,999,999.00"])
def test_what_isnt_an_amount(text):
    assert parse_amount(text) is None


def test_amounts_finds_each_token_in_a_line():
    assert amounts("Beginning balance on March 1, 2026 $5,320.77") == [532077]
    assert amounts("Total withdrawals and other subtractions 1,204.10- Page 2") == [-120410]
    assert amounts("03/01/2026 - 03/31/2026") == []
    assert amounts("Payment, Credits -$1,200.00   Purchases +$412.18") == [-120000, 41218]


def test_period_dates_any_format_hint_first_and_month_first_before_day_first():
    assert D.period_dates("Statement Period 03/01/2026 - 03/31/2026", "%m/%d/%Y") == (date(2026, 3, 1), date(2026, 3, 31))
    assert D.period_dates("Statement Period 03/01/2026 - 03/31/2026", "%B %d, %Y") == (date(2026, 3, 1), date(2026, 3, 31))
    assert D.period_dates("March 1, 2026 through March 31, 2026", None) == (date(2026, 3, 1), date(2026, 3, 31))
    assert D.period_dates("Opening/Closing Date 12/18/25 - 01/17/26", "%m/%d/%Y") == (date(2025, 12, 18), date(2026, 1, 17))
    assert D.period_dates("03/04/2026 - 04/03/2026", None) == (date(2026, 3, 4), date(2026, 4, 3))   # never 3 April
    assert D.period_dates("Billing Cycle Mar 01, 2026 - Mar 31, 2026", "%b %d, %Y") == (date(2026, 3, 1), date(2026, 3, 31))
    assert D.period_dates("Payment Due Date 04/25/26", None) is None


def test_period_dates_refuse_a_span_over_100_days_or_backwards():
    assert D.period_dates("01/01/2026 - 06/30/2026", None) is None
    assert D.period_dates("03/31/2026 - 03/01/2026", None) is None


def test_dec_jan_year_inference_p19():
    end = date(2026, 1, 17)
    assert D.infer_year(12, 20, end) == date(2025, 12, 20)
    assert D.infer_year(1, 5, end) == date(2026, 1, 5)
    assert D.infer_year(1, 24, end) == date(2026, 1, 24)          # 7 days after: still this year
    assert D.infer_year(1, 25, end) == date(2025, 1, 25)          # 8 days after: the year before
    assert D.infer_year(2, 30, end) is None


def test_row_dates_hint_first_then_the_others():
    end = date(2026, 3, 31)
    assert D.row_date("03/04", "%m/%d", end) == date(2026, 3, 4)
    assert D.row_date("Mar 04", "%m/%d", end) == date(2026, 3, 4)            # the hint is only a hint
    assert D.row_date("March 4", "%b %d", end) == date(2026, 3, 4)           # %b and %B read alike
    assert D.row_date("03/04/26", None, end) == date(2026, 3, 4)
    assert D.row_date("PAYROLL", "%m/%d", end) is None
    assert D.row_date("13/45", "%m/%d", end) is None


def test_the_wire_formats_are_the_import_candidates_trimmed_plus_four():
    from steward.services.importers.dates import CANDIDATES, ISO_DATETIME
    assert set(W.DATE_FORMATS) == (set(CANDIDATES) - {"%Y%m%d", ISO_DATETIME}) | {"%m/%d", "%m-%d", "%b %d", "%d %b"}
    assert W.DATE_FORMATS.index("%m/%d/%Y") < W.DATE_FORMATS.index("%d/%m/%Y")
