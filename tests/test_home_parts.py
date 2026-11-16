"""Home reads Spending's own Flexible and Bill rows (Home spec, Server): flexible_rows and watched_rows are exactly
month_view's everyday and fixed lists, so Home's signs and Spending's month never disagree."""
from datetime import date

from steward.services import spending as sp
from tests.spending_fixtures import TODAY, household


def test_flexible_and_watched_rows_are_month_views_rows(db):
    household(db)
    month = TODAY.replace(day=1)
    m = sp.month_view(db, TODAY, month)
    st = sp.settings(db)
    window, wsums = sp.window_sums(db, TODAY)
    flows = sp.category_months(db, month, date(2026, 11, 1)).get("2026-10", {})
    assert sp.flexible_rows(st, flows, sp.typicals(window, wsums), TODAY.day, 31) == m["everyday"]
    assert sp.watched_rows(db, st, month, TODAY, window, wsums, flows) == m["fixed"]     # no Giving row in this household
    assert [r["category"] for r in m["fixed"]] == ["housing", "utilities", "subscriptions"]
    assert {r["category"]: r["state"] for r in m["fixed"]}["utilities"] == "late"            # usually by the 12th; Oct 25
