"""Solo 401(k) or SEP (spec 7.2; rulings 2, 12-14), against the real engine. Fictional household."""
import re
from datetime import date

import pytest

from steward.business.settings import update_settings
from steward.taxes.household import NotReady
from steward.taxes.plans import NO_BUSINESS, SCORP_PLANS, deadline_text, deadlines, plans, plans_out, plans_year
from tests.factories import add_fact, login
from tests.taxes.helpers import AT, household

TODAY = date(2026, 10, 13)


def test_a_sole_proprietor_only(db):
    household(db, business="none")
    with pytest.raises(NotReady, match=re.escape(NO_BUSINESS)):
        plans(db, TODAY)
    household(db, business="s_corp")
    with pytest.raises(NotReady, match="For an S-corp"):
        plans(db, TODAY)
    assert SCORP_PLANS.startswith("For an S-corp")


def test_profit_so_far_side_by_side(db):
    household(db, profit_cents=10_000_000)                    # $100,000 so far, no range, no wages
    p = plans(db, TODAY)
    assert p.year == 2026 and [x.label for x in p.points] == ["so_far"] and p.default == "so_far"
    pt = p.points[0]
    assert (pt.room.sep_cents, pt.room.solo_total_cents) == (1_858_700, 4_308_700)   # Task 3's hand-worked case
    assert 0 < pt.sep_saves_cents < pt.solo_saves_cents
    assert pt.line == "A Solo 401(k) allows $24,500 more at this profit: your own part isn't limited to 20% of earnings."


def test_the_range_adds_low_and_high_and_opens_on_low(db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    p = plans(db, TODAY)
    assert [(x.label, x.profit_cents) for x in p.points] == [("so_far", 4_000_000), ("low", 6_000_000), ("high", 10_000_000)]
    assert p.default == "low"
    assert p.points[0].room.solo_total_cents < p.points[1].room.solo_total_cents < p.points[2].room.solo_total_cents


def test_paychecks_using_the_limit_say_so(db):
    household(db, profit_cents=10_000_000, salary="30000000", k401="1000")     # 10% of $300,000 is over $24,500
    pt = plans(db, TODAY).points[0]
    assert pt.room.solo_own_cents == 0 and pt.room.solo_total_cents == pt.room.sep_cents
    assert pt.line == "Both allow the same at this profit: your paychecks already use this year's $24,500 for your own part."


def test_no_profit_no_room(db):
    household(db, profit_cents=-50_000)
    pt = plans(db, TODAY).points[0]
    assert pt.room.solo_total_cents == 0 and pt.line == "No room yet: the business needs a profit first."
    assert pt.solo_saves_cents == 0 and pt.sep_saves_cents == 0


def test_deadlines_in_plain_words():
    solo, sep = deadlines(2026)
    assert [deadline_text(d, TODAY) for d in solo] == [
        "Set up by December 31, 2026",
        "Or open a new plan after the year ends, and pay in your own part, by April 15, 2027",
        "Pay in the business's part by April 15, 2027, or October 15, 2027 with an extension"]
    assert [deadline_text(d, TODAY) for d in sep] == ["Set up and pay in by April 15, 2027, or October 15, 2027 with an extension"]
    assert deadline_text(solo[0], date(2027, 2, 1)) == "Set up by December 31, 2026 (passed)"


def test_last_year_until_its_return_is_due(db):
    assert plans_year(date(2027, 4, 15)) == 2026 and plans_year(date(2027, 4, 16)) == 2027 and plans_year(TODAY) == 2026
    household(db, profit_cents=10_000_000)
    p = plans(db, date(2027, 2, 1))
    assert p.year == 2026 and [x.label for x in p.points] == ["full_year"]
    out = plans_out(p, date(2027, 2, 1))
    assert out["points"][0]["label_text"] == "Full year" and out["deadlines"]["solo"][0].endswith("(passed)")


def test_the_route(frozen, signed_in, db):
    household(db, profit_cents=10_000_000)
    r = signed_in.get("/api/b/ours/taxes/plans").json()
    assert r["available"] is True and r["year"] == 2026 and r["default_point"] == "so_far"
    pt = r["points"][0]
    assert pt["solo"]["total_cents"] == 4_308_700 and pt["sep"]["total_cents"] == 1_858_700
    assert set(pt["solo"]) == {"own_cents", "business_cents", "catch_up_cents", "total_cents", "saves_cents"}
    assert r["rules_note"] == "2026 federal and 2025 California rules" and r["never"] == "Steward never pays or files anything."


def test_a_spouse_run_business_uses_no_paycheck_deferrals_of_jr(db):
    # JR's paychecks use the whole limit, but the spouse runs the business: JR's deferrals aren't the spouse's.
    household(db, profit_cents=10_000_000, salary="30000000", k401="1000")
    update_settings(db, {"owner": "spouse"}, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    db.commit()
    spouse = plans(db, TODAY).points[0].room
    assert spouse.used_elsewhere_cents == 0 and spouse.solo_own_cents == 2_450_000
    update_settings(db, {"owner": "jr"}, year=2026, this_year=2026, periods=2, user_id=1, at=AT)
    db.commit()
    jr = plans(db, TODAY).points[0].room
    assert jr.used_elsewhere_cents == 2_450_000 and jr.solo_own_cents == 0


def test_payroll_k401_fact_counts_as_deferrals_in_its_own_year_only(db):
    household(db, profit_cents=10_000_000)                       # no salary on file
    add_fact(db, "jr.payroll_k401_cents", "1000000", as_of=date(2026, 9, 30))        # $10,000 through payroll
    assert plans(db, TODAY).points[0].room.used_elsewhere_cents == 1_000_000
    add_fact(db, "jr.payroll_k401_cents", "2000000", as_of=date(2025, 12, 31))       # older, another year: ignored
    assert plans(db, TODAY).points[0].room.used_elsewhere_cents == 1_000_000


def test_parent_books_have_no_plans(frozen, client, margaret):
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/taxes/plans").status_code == 404
