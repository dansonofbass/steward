"""Steward's Social Security estimate (profile spec P24): an earnings record from today's salary."""
from steward.engine import datafiles
from steward.engine.social_security import estimated_record


def test_years_from_22_to_last_year_scaled_by_the_wage_index():
    rec = dict(estimated_record(1982, 16_000_000, 2026))
    assert min(rec) == 2004 and max(rec) == 2025
    awi = datafiles.awi()
    latest = max(awi)
    assert rec[2010] == round(16_000_000 * awi[2010] / awi[latest])
    assert rec[2025] == min(16_000_000, datafiles.taxable_max()[2025] * 100)   # past the AWI file: today's salary


def test_each_year_is_capped_at_its_taxable_maximum():
    rec = dict(estimated_record(1982, 100_000_000, 2026))                    # $1M a year
    cap = datafiles.taxable_max()
    assert all(cents == cap[y] * 100 for y, cents in rec.items())


def test_years_before_the_wage_index_starts_are_left_out():
    rec = dict(estimated_record(1925, 5_000_000, 2026))                      # 22 in 1947; the AWI file starts in 1951
    assert min(rec) == min(datafiles.awi())


def test_nobody_22_yet_has_no_years():
    assert estimated_record(2008, 5_000_000, 2026) == ()
