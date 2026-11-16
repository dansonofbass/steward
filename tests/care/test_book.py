"""What Care projects from (spec 4.1; rulings 11, 12, 17): balances by tax treatment, income by kind, spending from
history and the long-term care policy's terms. Fictional parent: Margaret Ellis."""
from dataclasses import replace
from datetime import date

from steward.care import book as B
from steward.engine.project import Income
from tests.care.helpers import OWNERS, SETUP, TODAY, add_account, add_item
from tests.factories import make_txn


def test_balances_by_tax_treatment(mdb):
    add_account(mdb, "Joint checking", "checking", 5_000_000)
    add_account(mdb, "12-month CD", "cd", 1_000_000)
    add_account(mdb, "Brokerage", "brokerage", 10_000_000)
    add_account(mdb, "Traditional IRA", "ira", 20_000_000)
    add_account(mdb, "Roth IRA", "ira", 3_000_000, roth=True)
    add_account(mdb, "Deferred annuity", "annuity", 4_000_000)
    add_account(mdb, "House", "property", 78_000_000)
    add_account(mdb, "Lake lot", "property", 30_000_000)
    add_account(mdb, "Citi card", "credit_card", -200_000)
    add_account(mdb, "Car loan", "loan", -500_000)
    add_account(mdb, "New savings", "savings", None)
    add_account(mdb, "Old savings", "savings", 9_999_999, status="closed")
    b = B.balances(mdb)
    assert (b.cash_cents, b.taxable_cents, b.traditional_cents, b.roth_cents) == (5_800_000, 10_000_000, 24_000_000, 3_000_000)
    assert b.home_value_cents == 78_000_000
    assert b.notes == ("1 other property isn't in the projection.", B.LOANS,
                       "1 account has no balance yet and isn't counted.")


def test_card_debt_never_makes_a_balance_negative(mdb):
    # Review Focus 4: the engine refuses negative balances
    add_account(mdb, "Joint checking", "checking", 100_000)
    add_account(mdb, "Brokerage", "brokerage", 50_000)
    add_account(mdb, "Citi card", "credit_card", -400_000)
    b = B.balances(mdb)
    assert (b.cash_cents, b.taxable_cents, b.traditional_cents, b.roth_cents) == (0, 0, 0, 0)
    assert b.notes == (B.DEBT_LEFT,)


def test_income_items_by_kind_and_growth(mdb):
    add_item(mdb, "income", "Social Security", {"source": "social_security", "amount_cents": 214_000, "frequency": "monthly"})
    add_item(mdb, "income", "County Schools pension", {"source": "pension", "amount_cents": 300_000, "frequency": "quarterly"})
    add_item(mdb, "income", "Westmark annuity", {"source": "annuity", "amount_cents": 500_000, "frequency": "yearly"})
    add_item(mdb, "income", "IRA RMD", {"source": "rmd", "amount_cents": 100_000, "frequency": "monthly"})
    add_item(mdb, "income", "Old pension", {"source": "pension", "amount_cents": 1, "frequency": "monthly"}, status="closed")
    got = [(i.kind, i.amount_cents, i.growth, i.start_year) for i in B.incomes(mdb, 2026)]
    assert got == [("social_security", 2_568_000, "prices", 2026), ("pension", 1_200_000, "fixed_dollars", 2026),
                   ("pension", 500_000, "fixed_dollars", 2026)]
    assert all(isinstance(i, Income) for i in B.incomes(mdb, 2026))


def test_spending_from_history_leaves_out_taxes_and_transfers(mdb):
    _, chk = add_account(mdb, "Joint checking", "checking", 1_000_000)
    for m in (7, 8, 9):
        make_txn(mdb, chk, date(2026, m, 1), -100_000, "STATER BROS 123", category="groceries")
        make_txn(mdb, chk, date(2026, m, 15), -50_000, "FRANCHISE TAX BD", category="taxes")
        make_txn(mdb, chk, date(2026, m, 20), -30_000, "TRANSFER TO SAVINGS", category="transfer", is_transfer=True)
        make_txn(mdb, chk, date(2026, m, 22), -40_000, "CITI CARD ONLINE PAYMENT", category="transfer")
        make_txn(mdb, chk, date(2026, m, 3), 200_000, "SSA TREAS 310", category="income")
    make_txn(mdb, chk, date(2026, 10, 2), -999_999, "THIS MONTH SO FAR", category="shopping")
    mdb.flush()
    assert B.spending_from_history(mdb, TODAY) == (1_200_000, 3)       # $1,000 a month for 3 complete months
    assert B.spending_from_history(mdb, date(2026, 7, 20)) == (0, 0)   # no complete month yet


def test_policies_need_their_terms_and_say_what_is_missing(mdb):
    # Review Focus 3
    good = add_item(mdb, "insurance", "Long-term care", {"type": "long_term_care", "benefit_cents": 15_000,
                                                         "benefit_per": "day", "waiting_days": 90, "benefit_years": 3,
                                                         "rider_bp": 300})
    add_item(mdb, "insurance", "Second policy", {"type": "long_term_care", "benefit_cents": 300_000, "benefit_per": "month"})
    add_item(mdb, "insurance", "Third policy", {"type": "long_term_care"})
    monthly = add_item(mdb, "insurance", "Fourth policy", {"type": "long_term_care", "benefit_cents": 450_000,
                                                           "benefit_per": "month", "pool_cents": 16_200_000})
    blank = add_item(mdb, "insurance", "Form policy", {"type": "long_term_care", "benefit_cents": 10_000, "benefit_per": None,
                                                      "waiting_days": 30, "pool_cents": None, "benefit_years": 2,
                                                      "rider_bp": None})
    add_item(mdb, "insurance", "Medicare supplement", {"type": "supplement", "benefit_cents": 1})
    add_item(mdb, "insurance", "Lapsed", {"type": "long_term_care", "benefit_cents": 1, "benefit_per": "day",
                                          "benefit_years": 1}, status="closed")
    terms, notes = B.policies(mdb, "margaret", OWNERS)
    assert terms == (B.PolicyTerms(good.id, 15_000, None, 90, None, 3, 0.03),
                     B.PolicyTerms(monthly.id, None, 450_000, 90, 16_200_000, None, 0.0),
                     B.PolicyTerms(blank.id, 10_000, None, 30, None, 2, 0.0))
    assert notes == (B.NO_POOL, B.NO_BENEFIT, B.NO_WAIT)


def test_only_the_setup_persons_policies_count(mdb):
    # I1: a policy that belongs to the other parent, or to both, never pays toward this parent's care
    mine = add_item(mdb, "insurance", "Evergreen", {"type": "long_term_care", "benefit_cents": 15_000,
                                                    "benefit_per": "day", "waiting_days": 90, "benefit_years": 3})
    other = add_item(mdb, "insurance", "Robert's policy", {"type": "long_term_care", "benefit_cents": 20_000,
                                                           "benefit_per": "day", "waiting_days": 90, "benefit_years": 4})
    other.owner = "robert-husband"
    both = add_item(mdb, "insurance", "Shared policy", {"type": "long_term_care"})
    both.owner = "joint"
    mdb.flush()
    terms, notes = B.policies(mdb, "margaret", OWNERS)
    assert [t.item_id for t in terms] == [mine.id]
    assert notes == ("A long-term care policy (Robert's policy) isn't counted: it covers Robert.",
                     "A long-term care policy (Shared policy) isn't counted: it covers both, and only Margaret's own "
                     "policies count.")
    terms, notes = B.policies(mdb, "robert-husband", OWNERS)
    assert [t.item_id for t in terms] == [other.id]
    assert notes[0] == "A long-term care policy (Evergreen) isn't counted: it covers Margaret."
    b = B.load_book(mdb, replace(SETUP, person="robert-husband"), OWNERS, TODAY)
    assert [t.item_id for t in b.policies] == [other.id] and notes[0] in b.notes


def test_a_policy_premium_counts_unless_an_income_pays_it(mdb):
    # M5: the premium is what the waiver of premium stops while the policy pays; one taken out of an income before it
    # lands was never in spending
    ss = add_item(mdb, "income", "Social Security", {"source": "social_security", "amount_cents": 214_000,
                                                     "frequency": "monthly"})
    terms = {"type": "long_term_care", "benefit_cents": 15_000, "benefit_per": "day", "benefit_years": 3,
             "waiting_days": 90, "amount_cents": 21_200, "frequency": "monthly"}
    add_item(mdb, "insurance", "Evergreen", terms)
    add_item(mdb, "insurance", "Quarterly", {**terms, "amount_cents": 60_000, "frequency": "quarterly"})
    add_item(mdb, "insurance", "From income", {**terms, "paid_from_id": ss.id})
    add_item(mdb, "insurance", "No premium", {k: v for k, v in terms.items() if k != "amount_cents"})
    got, _ = B.policies(mdb, "margaret", OWNERS)
    assert [t.premium_yearly_cents for t in got] == [254_400, 240_000, 0, 0]


def test_load_book_with_typed_spending(mdb):
    add_account(mdb, "Joint checking", "checking", 5_000_000)
    b = B.load_book(mdb, replace(SETUP, spending_monthly_cents=400_000), OWNERS, TODAY)
    assert (b.spending_yearly_cents, b.spending_months, b.spending_typed) == (4_800_000, 0, True)
    assert (b.person_label, b.age, b.cash_cents, b.state, b.care_inflation) == ("Margaret", 82, 5_000_000, "CA", 0.04)
    from_history = B.load_book(mdb, SETUP, OWNERS, TODAY)
    assert (from_history.spending_yearly_cents, from_history.spending_typed) == (0, False)
