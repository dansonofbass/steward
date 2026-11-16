"""The quarterly card (spec 7.1; rulings 2-10), against the real engine. Fictional household."""
from datetime import date, timedelta

from steward.engine.tax import annual_tax
from steward.taxes import store
from steward.taxes.household import household_tax
from steward.taxes.quarterly import (
    NO_WITHHOLDING, full_year_withholding, method_line, notice, notice_line, quarterly, rules_note,
)
from steward.engine.tax.estimates import Due
from steward.taxes.quarterly import _status, quarterly_out
from steward.taxes.store import Withholding
from tests.factories import make_account, make_txn
from tests.taxes.helpers import AT, household

TODAY = date(2026, 10, 13)


def test_withholding_scales_to_the_full_year():
    assert full_year_withholding(None, 2026) == (0, 0)
    # 273 days through September 30, 2026; 365 in the year
    assert full_year_withholding(Withholding(1_200_000, 400_000, date(2026, 9, 30)), 2026) == (
        round(1_200_000 * 365 / 273), round(400_000 * 365 / 273))
    # the last day of the year is the whole year (a later pay date is refused when it is entered)
    assert full_year_withholding(Withholding(1_500_000, 500_000, date(2026, 12, 31)), 2026) == (1_500_000, 500_000)


def test_a_sole_proprietor_with_no_wages(db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    q = quarterly(db, TODAY)
    high = annual_tax(household_tax(db, 2026, TODAY).facts, 2026, marginal=False)
    assert q.year == 2026 and q.federal.current_tax_cents == high.federal_total_cents
    assert q.state_plan is not None and q.state_plan.current_tax_cents == high.state.tax_cents
    assert q.federal.method == "current_year" and q.needs_withholding is False
    assert q.low_tax_cents is not None and q.low_tax_cents < high.federal_total_cents + high.state.tax_cents
    # nothing paid yet, so the next date (January 15, 2027) carries every date's share
    assert q.next_due.due == date(2027, 1, 15)
    assert q.next_due.federal_cents == q.federal.balance_cents and q.next_due.state_cents == q.state_plan.balance_cents
    assert q.rules_note == "2026 federal and 2025 California rules"


def test_last_years_return_and_payments_lower_what_is_due(db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    store.write_return(db, 2025, {"federal_tax_cents": 400_000, "federal_agi_cents": 6_000_000,
                                  "state_tax_cents": 50_000, "state_agi_cents": 6_000_000}, 1, AT)
    make_txn(db, make_account(db, "Checking"), date(2026, 6, 10), -100_000, "IRS USATAXPYMT")
    db.commit()
    q = quarterly(db, TODAY)
    assert q.federal.method == "prior_year" and q.federal.required_cents == 400_000      # 100%: AGI under $150,000
    assert [d.still_due_cents for d in q.federal.dues] == [100_000, 100_000, 200_000, 300_000]
    assert q.next_due.federal_cents == 300_000
    assert method_line(q.federal, 2026).startswith("100% of 2025's tax, $4,000: less than 90% of this year's")


def test_the_line_names_the_missing_figure_from_last_years_return(db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    q = quarterly(db, TODAY)
    assert method_line(q.federal, 2026, q.prior, q.state).endswith("Add 2025's tax to compare with the safe harbor.")
    store.write_return(db, 2025, {"federal_tax_cents": 400_000, "federal_agi_cents": None,
                                  "state_tax_cents": 50_000, "state_agi_cents": None}, 1, AT)
    db.commit()
    q = quarterly(db, TODAY)
    assert method_line(q.federal, 2026, q.prior, q.state).endswith(
        "Add 2025's adjusted gross income to compare with the safe harbor.")
    assert method_line(q.state_plan, 2026, q.prior, q.state).endswith(
        "Add 2025's California adjusted gross income to compare with the safe harbor.")


def test_the_withholding_note_names_the_cards_year(db):
    household(db, profit_cents=4_000_000, salary="16500000")
    q = quarterly(db, date(2027, 1, 5))                      # the card shows 2026 until January 15
    assert "Add what your 2026 paychecks withheld; until then none of it is counted." in q.notes


def test_wages_without_withholding_say_so_and_hold_the_notice(db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000, salary="16500000", k401="800")
    q = quarterly(db, date(2027, 1, 5))                      # inside the window for January 15
    assert q.needs_withholding is True and NO_WITHHOLDING.format(year=2026) in q.notes
    assert notice(q, date(2027, 1, 5)) is None
    store.write_withholding(db, 2026, {"federal_ytd_cents": 2_000_000, "state_ytd_cents": 900_000,
                                       "as_of": "2026-12-31"}, today=date(2027, 1, 5), user_id=1, at=AT)
    db.commit()
    q = quarterly(db, date(2027, 1, 5))
    assert q.needs_withholding is False and q.federal.withholding_cents == 2_000_000
    # in early January the card is last year's, so the line names its year rather than "this year"
    assert quarterly_out(q, date(2027, 1, 5), False)["agencies"][0]["withholding_line"] == "Less $20,000 withheld from 2026 pay."


def test_the_notice_shows_two_weeks_before_while_something_is_due(db):
    # Viewed from January 2027, 2026's profit is the year's own ($150,000): both agencies are owed something.
    household(db, profit_cents=15_000_000)
    due = date(2027, 1, 15)
    assert notice(quarterly(db, due - timedelta(days=15)), due - timedelta(days=15)) is None
    n = notice(quarterly(db, due - timedelta(days=14)), due - timedelta(days=14))
    assert n is not None and n.due == due
    q = quarterly(db, due)
    assert notice(q, due) == q.next_due
    assert notice_line(q.next_due, "CA") == (f"Quarterly taxes due January 15: ${round(q.next_due.federal_cents / 100):,} "
                                             f"federal and ${round(q.next_due.state_cents / 100):,} California")


def test_early_january_still_shows_last_year(db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    assert quarterly(db, date(2027, 1, 15)).year == 2026
    assert quarterly(db, date(2027, 1, 16)).year == 2027


def test_a_state_without_estimates_shows_federal_only(db):
    household(db, profit_cents=4_000_000, state="TX")
    q = quarterly(db, TODAY)
    assert q.state_plan is None and q.next_due.state_cents == 0
    household(db, state="NY")
    q = quarterly(db, TODAY)
    assert q.state_plan is None and "State tax isn't calculated for New York yet." in q.notes


def test_the_rules_note():
    assert rules_note(2026, 2026, 2025, "CA") == "2026 federal and 2025 California rules"
    assert rules_note(2026, 2026, 2026, "CA") == "2026 tax rules"
    assert rules_note(2026, 2026, None, "TX") == "2026 tax rules"
    assert rules_note(2027, 2026, None, "TX") == "Using 2026 rules"


def test_a_date_with_no_installment_reads_nothing_due_even_after_a_short_payment():
    # California's September date carries no share of the year; June's shortfall belongs to June's row (final review m6)
    sep = date(2026, 9, 15)
    assert _status(Due(sep, 0.0, 0, 400_000, 300_000, 100_000), date(2026, 9, 1)) == "nothing"
    assert _status(Due(sep, 0.0, 0, 400_000, 300_000, 100_000), date(2026, 10, 1)) == "nothing"
    assert _status(Due(sep, 0.0, 0, 400_000, 400_000, 0), date(2026, 10, 1)) == "nothing"
    assert _status(Due(sep, 0.3, 120_000, 400_000, 300_000, 100_000), date(2026, 9, 1)) == "upcoming"
    assert _status(Due(sep, 0.3, 120_000, 400_000, 300_000, 100_000), date(2026, 10, 1)) == "short"
