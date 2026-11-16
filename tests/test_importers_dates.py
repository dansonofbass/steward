"""Dates (spec P13): keep the formats that read 98% of the column; a day over 12 decides day versus month; then the
file's order; otherwise ask, with the first cell whose day and month differ."""
from datetime import date

import pytest

from steward.services.importers.dates import ISO_DATETIME, DateChoice, choose, day_label, parse_day, reading


def test_iso_datetime_uses_the_date_part():
    for s in ("2024-10-03T14:22:05", "2024-10-03 14:22", "2024-10-03T14:22:05.123Z", "2024-10-03T14:22:05-07:00"):
        assert parse_day(s, ISO_DATETIME) == date(2024, 10, 3)
    with pytest.raises(ValueError):
        parse_day("2024-10-03", ISO_DATETIME)


def test_words_and_compact_iso():
    assert parse_day("Oct 3, 2024", "%b %d, %Y") == date(2024, 10, 3)
    assert parse_day("3 Oct 2024", "%d %b %Y") == date(2024, 10, 3)
    assert parse_day("20241003", "%Y%m%d") == date(2024, 10, 3)
    with pytest.raises(ValueError):
        parse_day("2024103", "%Y%m%d")


def test_two_digit_years_use_pythons_pivot():
    assert parse_day("10/03/69", "%m/%d/%y") == date(1969, 10, 3)
    assert parse_day("10/03/68", "%m/%d/%y") == date(2068, 10, 3)


def test_a_day_of_13_first_means_day_first_and_second_means_month_first():
    assert choose(["03/04/2024", "13/04/2024"]) == DateChoice("%d/%m/%Y")
    assert choose(["03/04/2024", "04/13/2024"]) == DateChoice("%m/%d/%Y")


def test_the_files_order_breaks_the_tie_both_ways():
    assert choose(["10/02/2024", "10/04/2024", "11/03/2024", "12/12/2024"]) == DateChoice("%m/%d/%Y")
    assert choose(["02/10/2024", "04/10/2024", "03/11/2024", "12/12/2024"]) == DateChoice("%d/%m/%Y")


def test_an_ambiguous_file_asks_with_its_first_differing_cell():
    assert choose(["05/05/2024", "03/04/2024", "05/02/2024", "01/03/2024"]) == \
        DateChoice(None, "03/04/2024", ("%m/%d/%Y", "%d/%m/%Y"))
    assert choose(["03-04-2024", "05-02-2024", "01-03-2024"]) == DateChoice(None, "03-04-2024", ("%m-%d-%Y", "%d-%m-%Y"))


def test_98_percent_readable_passes_and_97_doesnt():
    good = [f"2024-10-{(i % 28) + 1:02d}" for i in range(100)]
    assert choose(good[:98] + ["nope", "nope"]).format == "%Y-%m-%d"
    assert choose(good[:97] + ["nope", "nope", "nope"]).format is None


def test_iso_dates_and_datetimes_are_never_asked():
    assert choose(["2024-10-02", "2024-10-01"]) == DateChoice("%Y-%m-%d")
    assert choose(["2024-10-03T14:22:05", "2024-10-08T09:01:44"]) == DateChoice(ISO_DATETIME)
    assert choose(["15.10.2024", "01.10.2024"]) == DateChoice("%d.%m.%Y")
    assert choose([]) == DateChoice(None)


def test_readings_and_labels():
    assert [reading(f) for f in ("%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d", ISO_DATETIME, "%d %b %Y", "%b %d, %Y")] == \
        ["month/day/year", "day/month/year", "year-month-day", "year-month-day", "day/month/year", "month/day/year"]
    assert (day_label(date(2024, 3, 4)), day_label(date(2024, 4, 3))) == ("March 4", "April 3")
