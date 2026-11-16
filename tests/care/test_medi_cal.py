"""The Medi-Cal check (spec 4.3, 3.6; D9; rulings 1, 2): the limit in force each year, countable assets, the three
lines, and a scheduled change used only once confirmed."""
from dataclasses import replace
from datetime import date

from steward.care import medi_cal as M
from steward.engine.project import Assumptions, ProjectionInputs, project
from steward.engine.tax import rules

FLAT = Assumptions(inflation=0.0, real_return=0.0, care_inflation=0.0)


def row(year: int = 2026, **balances):
    base = project(ProjectionInputs(start_year=year, filing="single", state="CA", birth_years=(1944,)), FLAT, 1)[0]
    return replace(base, **balances)


def test_the_2026_limit_for_one_and_two_people():
    one, two = M.asset_limit(2026, 1), M.asset_limit(2026, 2)
    assert (one.cents, two.cents, M.asset_limit(2026, 3).cents) == (13_000_000, 19_500_000, 26_000_000)
    assert (one.rules_year, one.effective_from) == (2026, date(2026, 1, 1))
    assert one.source == "DHCS All County Welfare Directors Letter 25-14" and one.url.endswith("/25-14.pdf")
    assert M.rule_line(one) == ("Limit $130,000 for one person, from January 1, 2026 (2026 rules, DHCS All County "
                                "Welfare Directors Letter 25-14).")
    assert M.rule_line(two).startswith("Limit $195,000 for 2 people,")


def test_the_reported_2027_drop_is_never_used():
    assert rules.table("medi_cal", 2028)["scheduled"][0]["status"] == "reported_unconfirmed"
    assert M.asset_limit(2028, 1).cents == 13_000_000 and M.asset_limit(2040, 2).cents == 19_500_000


def test_a_confirmed_scheduled_change_is_used_from_its_year(monkeypatch):
    real = rules.table("medi_cal", 2026)
    fake = replace(real, data={**real.data, "scheduled": [{**real["scheduled"][0], "status": "confirmed"}]})
    monkeypatch.setattr(M.rules, "table", lambda topic, year: fake)
    assert M.asset_limit(2026, 1).cents == 13_000_000
    later = M.asset_limit(2027, 1)
    assert (later.cents, later.rules_year, later.effective_from) == (2_100_000, 2027, date(2027, 7, 1))
    assert (M.asset_limit(2027, 2).cents, M.asset_limit(2027, 3).cents) == (3_100_000, 3_255_000)


def test_countable_assets_leave_out_an_ira_that_pays_out():
    r = row(cash_cents=5_000_000, taxable_cents=6_000_000, roth_cents=1_000_000, traditional_cents=20_000_000)
    assert M.in_payout(1944, 2026) and not M.in_payout(1960, 2026)
    assert M.countable_cents(r, 1944) == 12_000_000            # 82: RMDs, so the IRA is in payout
    assert M.countable_cents(r, 1960) == 32_000_000            # 66: not yet


def test_the_three_lines_and_the_first_year_the_limit_is_met():
    under = M.check_year(row(2028, cash_cents=12_000_000), 1944, 1)
    assert (under.status, under.over_cents, M.status_line(under)) == ("eligible", 0, "Eligible")
    over = M.check_year(row(2026, cash_cents=15_000_000), 1944, 1)
    assert (over.status, over.over_cents) == ("over_limit", 2_000_000)
    assert M.status_line(over) == "Not yet: countable assets are $20,000 over the limit"
    in_care = M.check_year(row(2027, cash_cents=15_000_000, care_cents=8_400_000), 1944, 1)
    assert M.status_line(in_care) == "Eligible after spending down $20,000"
    assert M.first_eligible([over, in_care, under]) == 2028 and M.first_eligible([over]) is None


def test_the_disclaimer_and_topics():
    assert M.DISCLAIMER == "An estimate to take to an elder-law attorney, not legal advice."
    assert M.topics(30, 2026) == ["Estate recovery after a death", "Protections for a spouse who stays at home",
                                  "The 30-month look-back on gifts and transfers (2026 rules)"]
