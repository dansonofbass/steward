"""The Business view's figures (spec 5, 9; rulings 7-10): shares, meals at half, the home office cap and its limit,
mileage by rate period, the range, and what is left out (Review Focus 5)."""
from datetime import date, datetime, timezone

from steward.business.report import business_report, line_rows, profit_range
from steward.business.settings import update_settings
from steward.db.models import Owner
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 13)
AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def settings(db, body, year=2026):
    update_settings(db, body, year=year, this_year=2026, periods=2 if year == 2026 else 1, user_id=1, at=AT)
    db.commit()


def lines(r):
    return {l.key: (l.spent_cents, l.counts_cents, l.count) for l in r.lines}


def books(db):
    bchk = make_account(db, "Business checking", type="business_checking", owner=Owner.business)
    card = make_account(db, "Rewards Card", type="credit")
    make_txn(db, bchk, date(2026, 3, 3), 300_000, "ACH CLIENT INV 1", category="business_income", is_business=True)
    make_txn(db, bchk, date(2026, 6, 3), 200_000, "ACH CLIENT INV 2", category="business_income", is_business=True)
    make_txn(db, card, date(2026, 4, 1), -10_000, "MOBILE ONE WIRELESS", category="utilities", business_pct=40)
    make_txn(db, card, date(2026, 4, 2), -4_501, "HARBOR GRILL", category="dining", is_business=True)
    make_txn(db, bchk, date(2026, 4, 3), -2_900, "NOTEFLOW PRO", category="subscriptions", is_business=True)
    make_txn(db, bchk, date(2026, 4, 4), 900, "NOTEFLOW PRO REFUND", category="subscriptions", is_business=True)
    make_txn(db, bchk, date(2026, 4, 5), -6_000, "PETROL STOP 88", category="transport", is_business=True)
    make_txn(db, bchk, date(2026, 4, 6), -400_000, "USTREAS IRS ESTIMATED TAX", category="taxes", is_business=True)
    make_txn(db, bchk, date(2026, 4, 7), -50_000, "OWNER DRAW", category="transfer", is_transfer=True)
    make_txn(db, card, date(2026, 4, 8), -9_000, "GREENLEAF MARKET", category="groceries")            # personal
    make_txn(db, bchk, date(2025, 12, 30), 100_000, "ACH CLIENT INV 0", category="business_income", is_business=True)
    return bchk, card


def test_a_split_counts_its_share_meals_count_half_and_refunds_lower_their_line(db):
    books(db)
    settings(db, {"type": "sole_prop", "car_method": "actual"})
    r = business_report(db, 2026, TODAY)
    got = lines(r)
    assert got["income"] == (500_000, 500_000, 2)
    assert got["utilities"] == (4_000, 4_000, 1)
    assert got["meals"] == (4_501, 2_251, 1)
    assert got["software"] == (2_000, 2_000, 2)
    assert got["car"] == (6_000, 6_000, 1)
    assert "home_office" not in got and r.left_out == 1          # the estimated tax payment
    assert (r.income_cents, r.expenses_cents) == (500_000, 4_000 + 2_251 + 2_000 + 6_000)
    assert r.profit_cents == r.income_cents - r.expenses_cents and r.through == TODAY and r.type == "sole_prop"
    meals = next(l for l in r.lines if l.key == "meals")
    assert meals.note == "Half of business meals counts (2026 rules)."


def test_standard_mileage_uses_each_periods_rate_and_ignores_car_charges(db):
    books(db)
    settings(db, {"car_method": "standard", "miles": [1000, 500]})
    car = next(l for l in business_report(db, 2026, TODAY).lines if l.key == "car")
    assert (car.spent_cents, car.counts_cents) == (6_000, 110_500)       # 1000 × 72.5¢ + 500 × 76¢
    assert car.note == "1,500 business miles at the IRS rates (2026 rules); car charges aren't counted."
    settings(db, {"miles": [0, 0]})
    car = next(l for l in business_report(db, 2026, TODAY).lines if l.key == "car")
    assert car.counts_cents == 0 and car.note == "Add business miles in Settings, Business."


def test_the_home_office_cap_holds_and_year_to_date_is_months_so_far(db):
    books(db)
    settings(db, {"car_method": "actual", "home_office": {"method": "simplified", "office_sqft": 400}})
    r = business_report(db, 2026, TODAY)
    ho = next(l for l in r.lines if l.key == "home_office")
    assert (ho.spent_cents, ho.counts_cents, ho.number) == (125_000, 125_000, "30")   # 300 × $5 × 10/12
    assert ho.note == "300 sq ft at $5 a square foot, up to 300 (2026 rules)."
    settings(db, {"home_office": {"method": "actual", "office_sqft": 150, "home_sqft": 1500,
                                  "home_costs_cents": 3_600_000}})
    ho = next(l for l in business_report(db, 2026, TODAY).lines if l.key == "home_office")
    assert ho.spent_cents == 300_000 and ho.note == "10% of the home's yearly costs."     # 360,000 × 10/12


def test_a_loss_year_has_no_home_office_and_a_later_year_says_which_rules(db):
    card = make_account(db, "Rewards Card", type="credit")
    make_txn(db, card, date(2026, 2, 1), 10_000, "ACH CLIENT INV 1", category="business_income", is_business=True)
    make_txn(db, card, date(2026, 2, 2), -90_000, "COWORK SPACE LLC", category="business_expense", is_business=True)
    settings(db, {"car_method": "actual", "home_office": {"method": "simplified", "office_sqft": 200}})
    r = business_report(db, 2026, TODAY)
    ho = next(l for l in r.lines if l.key == "home_office")
    assert ho.counts_cents == 0 and r.home_office_limited is True and r.profit_cents == -80_000
    assert ho.note.endswith("Limited to profit before the home office.")
    assert business_report(db, 2027, date(2027, 3, 1)).using_note == "Using 2026 rules"
    assert r.using_note is None


def test_the_range_is_year_to_date_plus_the_rest_of_the_year(db):
    books(db)
    settings(db, {"car_method": "actual", "home_office": {"method": "simplified", "office_sqft": 300}})
    plain = profit_range(db, 2026, TODAY)
    assert plain.low_cents == plain.high_cents == plain.ytd_cents and plain.entered is False
    settings(db, {"expect": {"low_cents": 100_000, "high_cents": 300_000}})
    r = business_report(db, 2026, TODAY)
    before_ho = r.income_cents - (r.expenses_cents - 125_000)
    assert r.range.entered is True and r.range.ytd_cents == r.profit_cents
    assert r.range.low_cents == before_ho + 100_000 - 150_000 and r.range.high_cents == before_ho + 300_000 - 150_000
    assert r.range.mid_cents == (r.range.low_cents + r.range.high_cents) // 2


def test_a_past_year_runs_to_its_end_and_has_no_range(db):
    books(db)
    settings(db, {"car_method": "actual"})
    r = business_report(db, 2025, TODAY)
    assert r.through == date(2025, 12, 31) and r.income_cents == 100_000
    assert r.range.low_cents == r.range.high_cents == r.profit_cents and r.range.entered is False


def test_line_rows_open_a_lines_transactions_with_their_shares(db):
    books(db)
    rows = line_rows(db, 2026, "utilities", TODAY)
    assert [(t.raw_description, name, s) for t, name, s in rows] == [("MOBILE ONE WIRELESS", "Rewards Card", -4_000)]
    assert [t.raw_description for t, _, _ in line_rows(db, 2026, "software", TODAY)] == [
        "NOTEFLOW PRO REFUND", "NOTEFLOW PRO"]
    assert line_rows(db, 2026, "home_office", TODAY) == []


def test_this_years_settings_never_change_last_years_report(db):
    """Final review ruling I2: in February JR files last year while changing this year's car and home office."""
    books(db)
    feb = date(2027, 2, 10)

    def put(body, year):
        update_settings(db, body, year=year, this_year=2027, periods=2 if year == 2026 else 1, user_id=1, at=AT)
        db.commit()
    put({"type": "sole_prop", "car_method": "actual", "home_office": {"method": "simplified", "office_sqft": 300}}, 2026)
    before = business_report(db, 2026, feb)
    put({"car_method": "standard", "miles": [400], "home_office": {"method": "none"}}, 2027)
    assert business_report(db, 2026, feb) == before
    assert "home_office" not in lines(business_report(db, 2027, feb))


def test_the_plan_gets_cash_profit_before_the_home_office_and_mileage(db):
    """Final review ruling I3: the home office and mileage only lower tax; the plan counts cash."""
    books(db)
    settings(db, {"type": "sole_prop", "car_method": "standard", "miles": [1000, 500],
                  "home_office": {"method": "simplified", "office_sqft": 300}})
    r = business_report(db, 2026, TODAY)
    cash = 500_000 - (4_000 + 4_501 + 2_000 + 6_000)       # meals in full and car charges; no home office or miles
    assert r.profit_cents < cash
    assert r.range.cash_ytd_cents == r.range.cash_low_cents == r.range.cash_high_cents == cash
    settings(db, {"expect": {"low_cents": 100_000, "high_cents": 300_000}})
    rng = profit_range(db, 2026, TODAY)
    assert (rng.cash_low_cents, rng.cash_high_cents) == (cash + 100_000, cash + 300_000)
    assert rng.cash_mid_cents == cash + 200_000


def test_in_january_the_plan_asks_for_the_rest_of_the_year(db):
    """Final review M1: until the range is entered, January's year to date is only weeks of profit."""
    books(db)
    settings(db, {"type": "sole_prop"})
    assert business_report(db, 2026, date(2026, 1, 20)).range.ask_expect is True
    assert business_report(db, 2026, TODAY).range.ask_expect is False
    settings(db, {"expect": {"low_cents": 100_000, "high_cents": 300_000}})
    assert business_report(db, 2026, date(2026, 1, 20)).range.ask_expect is False


def test_a_chargeback_lowers_income(db):
    bchk, _ = books(db)
    make_txn(db, bchk, date(2026, 6, 9), -50_000, "ACH CLIENT RETURN", category="business_income", is_business=True)
    settings(db, {"car_method": "actual"})
    assert lines(business_report(db, 2026, TODAY))["income"] == (450_000, 450_000, 3)
