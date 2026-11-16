"""What the Ask page lists and replays (spec 5.2, 5.3): groups by day, counts, the turn by turn view."""
from datetime import date, datetime, timezone

from steward.advisor.history import group_of, when_long, when_short
from steward.advisor.saw import TITLES, summary
from steward_boundary import tools as T

TODAY = date(2026, 10, 19)


def test_groups_today_this_week_and_earlier():
    assert group_of(date(2026, 10, 19), TODAY) == "today"
    assert group_of(date(2026, 10, 18), TODAY) == "week" and group_of(date(2026, 10, 13), TODAY) == "week"
    assert group_of(date(2026, 10, 12), TODAY) == "earlier"


def test_time_labels_in_the_households_zone():
    morning = datetime(2026, 10, 19, 17, 2, tzinfo=timezone.utc)          # 10:02 AM in Los Angeles
    sunday = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
    assert when_short(morning, TODAY) == "10:02 AM" and when_short(sunday, TODAY) == "Sun, Oct 18"
    assert when_long(morning, TODAY) == "Today 10:02 AM" and when_long(sunday, TODAY) == "Sun, Oct 18, 1:00 PM"


def test_every_tool_has_a_title_and_a_summary():
    assert TITLES["spending_by_category"] == "Spending by category" and TITLES["merchant_detail"] == "Store names"
    assert TITLES["plan_what_if"] == "The plan with changes" and set(TITLES) == {t.name for t in T.TOOLS}
    period = {"start": "2025-10-01", "end": "2026-09-30", "total_out_cents": 1,
              "categories": [{"category": "dining", "out_cents": 918420, "count": 212}]}
    assert summary("spending_by_category", {"period": period, "previous": period}, False) == (
        "October 1, 2025 to September 30, 2026: 1 category, each with a total and a count, against the period "
        "before. No store names.")
    assert summary("merchant_detail", {"rows": [{}] * 9, "payees": [], "more": False}, False, "JR") == \
        "9 store rows, approved by JR for this conversation."
    assert summary("merchant_detail", {"rows": [], "payees": [], "more": False}, False) == \
        "No store rows matched, so there was nothing to approve."
    assert summary("merchant_detail", {"error": T.DECLINED}, True) == "Not sent: you chose Don't send."
    assert summary("accounts", {"error": "This couldn't be looked up just now."}, True) == \
        "Couldn't be looked up: This couldn't be looked up just now."
