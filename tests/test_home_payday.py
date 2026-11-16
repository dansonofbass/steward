"""Usual payday (Home spec P8, P9): income rows of at least a fifth of their month, in clusters of days within 4 of
each other, seen in at least 4 of the 6 window months; the next one that hasn't come yet this month, until 4 days
after it."""
from datetime import date

from steward.services import home as hm

WINDOW = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
MONTHS = (4, 5, 6, 7, 8, 9)
PAY = 500_000


def monthly(day: int, months=MONTHS, cents: int = PAY) -> list[tuple[date, int]]:
    return [(date(2026, m, day), cents) for m in months]


def test_monthly_on_the_15th_is_pending_on_the_14th_and_the_15th_and_goes_once_pay_lands():
    days = hm.usual_paydays(WINDOW, monthly(15))
    assert days == [15]
    assert hm.pending_payday(days, [], PAY, date(2026, 10, 14)) == 15
    assert hm.pending_payday(days, [], PAY, date(2026, 10, 15)) == 15
    assert hm.pending_payday(days, [(date(2026, 10, 15), PAY)], PAY, date(2026, 10, 15)) is None


def test_four_days_after_the_usual_day_with_nothing_the_line_goes_quietly():
    assert hm.pending_payday([15], [], PAY, date(2026, 10, 19)) == 15
    assert hm.pending_payday([15], [], PAY, date(2026, 10, 20)) is None


def test_the_1st_and_the_15th_name_the_15th_on_the_10th():
    days = hm.usual_paydays(WINDOW, monthly(1, cents=250_000) + monthly(15, cents=250_000))
    assert days == [1, 15]
    assert hm.pending_payday(days, [(date(2026, 10, 1), 250_000)], 500_000, date(2026, 10, 10)) == 15
    assert hm.pending_payday(days, [], 500_000, date(2026, 10, 3)) == 1


def test_three_of_six_months_is_no_payday_and_four_is():
    assert hm.usual_paydays(WINDOW, monthly(15, months=(4, 6, 8)) + monthly(2, months=(5, 7, 9))) == []
    assert hm.usual_paydays(WINDOW, monthly(15, months=(4, 5, 6, 8)) + monthly(2, months=(7, 9))) == [15]


def test_a_bonus_under_a_fifth_of_its_month_is_ignored():
    rows = monthly(15) + [(date(2026, m, 3), 90_000) for m in MONTHS]       # 90,000 of 590,000: about 15%
    assert hm.usual_paydays(WINDOW, rows) == [15]


def test_days_close_together_are_one_payday_on_their_median():
    rows = [(date(2026, m, d), PAY) for m, d in zip(MONTHS, (14, 15, 16, 15, 13, 17))]
    assert hm.usual_paydays(WINDOW, rows) == [15]


def test_pay_a_few_days_early_has_come_and_earlier_than_that_hasnt():
    assert hm.pending_payday([15], [(date(2026, 10, 12), PAY)], PAY, date(2026, 10, 14)) is None
    assert hm.pending_payday([15], [(date(2026, 10, 10), PAY)], PAY, date(2026, 10, 14)) == 15


def test_a_small_deposit_is_not_the_pay_and_a_future_dated_one_hasnt_come():
    assert hm.pending_payday([15], [(date(2026, 10, 15), 20_000)], PAY, date(2026, 10, 15)) == 15
    assert hm.pending_payday([15], [(date(2026, 10, 16), PAY)], PAY, date(2026, 10, 15)) == 15


def test_a_payday_past_the_months_last_day_reads_as_its_last_day():
    assert hm.pending_payday([31], [], PAY, date(2026, 11, 28)) == 30


def test_no_typical_income_counts_any_income_row_as_the_pay():
    assert hm.pending_payday([15], [(date(2026, 10, 15), 20_000)], None, date(2026, 10, 15)) is None


def _flow(nets: list[int]) -> list[dict]:
    """Months as flow_view gives them; a month with net 0 here had nothing in or out."""
    return [{"month": f"m{i}", "in_cents": 0 if n == 0 else 100_000 + max(n, 0),
             "out_cents": 0 if n == 0 else 100_000 + max(-n, 0), "net_cents": n} for i, n in enumerate(nets)]


EARLIER = [0] * 5 + [10_000, -20_000, 30_000, 5_000, 40_000, 12_000]      # 11 months, 6 of them with money


def test_the_best_month_in_a_year_from_day_21():
    assert hm.best_month(_flow(EARLIER + [40_001]), 21) is True
    assert hm.best_month(_flow(EARLIER + [40_001]), 20) is False
    assert hm.best_month(_flow(EARLIER + [40_000]), 25) is False                    # equal is not above each
    assert hm.best_month(_flow([0] * 6 + [10_000, 20_000, 30_000, 5_000, 1_000] + [50_000]), 25) is False   # 5 months
    assert hm.best_month(_flow([0] * 12), 25) is False


from datetime import datetime, timezone

from steward.services.home_since import Look

AFTER = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)      # imported the evening of the 15th
LOOK = Look(datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc), False)


def test_the_usual_pay_that_reached_steward_since_the_last_look_has_landed():
    assert hm.landed_payday([15], [(date(2026, 10, 15), PAY, AFTER)], PAY, date(2026, 10, 16), LOOK) == 15


def test_pay_already_there_at_the_last_look_hasnt_landed_since():
    seen = Look(datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc), False)
    assert hm.landed_payday([15], [(date(2026, 10, 15), PAY, AFTER)], PAY, date(2026, 10, 16), seen) is None


def test_a_first_visit_has_no_last_look_so_nothing_has_landed_since_it():
    assert hm.landed_payday([15], [(date(2026, 10, 15), PAY, AFTER)], PAY, date(2026, 10, 16), None) is None


def test_a_small_deposit_or_one_posted_long_before_the_look_is_not_payday():
    assert hm.landed_payday([15], [(date(2026, 10, 15), 20_000, AFTER)], PAY, date(2026, 10, 16), LOOK) is None
    late_look = Look(datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc), False)
    history = [(date(2026, 10, 15), PAY, datetime(2026, 10, 31, 1, 0, tzinfo=timezone.utc))]
    assert hm.landed_payday([15], history, PAY, date(2026, 10, 31), late_look) is None   # posted 15 days before the look


def test_no_usual_payday_means_no_payday_moment():
    assert hm.landed_payday([], [(date(2026, 10, 15), PAY, AFTER)], PAY, date(2026, 10, 16), LOOK) is None
