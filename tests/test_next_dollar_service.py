"""Next dollar's inputs from the vault (cash-flow and tax spec section 6), on the made-up ready household."""
from datetime import date, datetime, timezone

from steward.db.models import BalanceSnapshot, BusinessState
from steward.services.next_dollar import build_next_dollar
from steward.services.plan_inputs import build_inputs
from tests.factories import add_fact, make_account, make_ready_household, make_txn, make_user

TODAY = date(2026, 10, 13)


def ready(db):
    make_user(db)
    make_user(db, "sam", "sam@x.com", "Sam")
    return make_ready_household(db)


def nd_for(db):
    return build_next_dollar(db, TODAY, build_inputs(db, TODAY))


def balance(db, account, cents):
    db.add(BalanceSnapshot(account_id=account.id, as_of=date(2026, 10, 1), balance_cents=cents))
    db.commit()


def test_the_household_and_this_years_tax_facts(db):
    ready(db)
    nd = nd_for(db)
    assert (nd.year, nd.month, nd.owners, nd.ages) == (2026, 10, ("JR", "Sam"), (44, 42))
    assert (nd.cash_cents, nd.cash_months, nd.has_business, nd.business_profit_low_cents) == (4_000_000, 3, False, 0)
    assert (nd.salary_cents, nd.k401_pct_bp, nd.match_rate_bp, nd.match_cap_bp) == (16_000_000, 1_000, 5_000, 600)
    assert nd.spending_basis_cents == 7_200_000 and nd.debt_rate_bp == 700 and nd.hsa_plan is None
    assert nd.hsa_family and not nd.has_hsa_account and nd.hsa_in_cents is None
    assert (nd.now.filing, nd.now.ages, nd.now.state) == ("mfj", (44, 42), "CA")
    assert (nd.now.wages_cents, nd.now.payroll_wages_cents, nd.now.ss_wages_by_person_cents) == \
        (14_400_000, 16_000_000, (16_000_000, 0))
    assert nd.now.dependents == (11,) and nd.now.business_profit_cents == 0
    assert nd.later.ages == (67, 67) and nd.later.ira_distributions_cents == 7_200_000
    assert 0.0 < nd.real_return < 0.1 and nd.inflation == 0.025


def test_settings_and_the_hsa_answer_come_from_facts(db):
    ready(db)
    add_fact(db, "next_dollar.cash_months", "9")
    add_fact(db, "next_dollar.debt_rate_bp", "800")
    add_fact(db, "health.hsa_plan", "yes")
    nd = nd_for(db)
    assert (nd.cash_months, nd.debt_rate_bp, nd.hsa_plan) == (9, 800, "yes")


def test_a_business_sets_six_months_and_the_profit_range(db):
    ready(db)
    db.add(BusinessState(key="type", value="sole_prop", updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    db.commit()
    pi = build_inputs(db, TODAY)
    nd = build_next_dollar(db, TODAY, pi)
    assert nd.has_business and nd.cash_months == 6
    assert nd.business_profit_low_cents == pi.business.low_cents
    assert nd.now.business_profit_cents == pi.business.mid_cents


def test_contributions_are_this_years_tagged_transfers_by_owner(db):
    accts = ready(db)
    make_txn(db, accts["roth"], date(2026, 3, 1), 50_000, "IRA CONTRIBUTION", category="transfer", is_transfer=True)
    make_txn(db, accts["roth"], date(2025, 12, 15), 70_000, "IRA CONTRIBUTION", category="transfer", is_transfer=True)
    make_txn(db, accts["roth"], date(2026, 6, 1), 9_999, "DIVIDEND", category="income")
    sam_ira = make_account(db, "Sam IRA", type="traditional_ira", owner="spouse")
    make_txn(db, sam_ira, date(2026, 4, 1), 30_000, "IRA CONTRIBUTION", category="transfer", is_transfer=True)
    solo = make_account(db, "Solo 401(k)", type="k401", owner="business")
    make_txn(db, solo, date(2026, 9, 1), 500_000, "CONTRIBUTION", category="transfer", is_transfer=True)
    hsa = make_account(db, "HSA", type="hsa", owner="jr")
    make_txn(db, hsa, date(2026, 2, 1), 120_000, "HSA CONTRIBUTION", category="transfer", is_transfer=True)
    nd = nd_for(db)
    assert nd.ira_in_cents == (50_000, 30_000)
    assert nd.business_plan_in_cents == 500_000
    assert nd.k401_in_cents is None                 # JR's employer 401(k) has no transactions
    assert nd.has_hsa_account and nd.hsa_in_cents == 120_000
    assert nd.taxable_in_cents is None


def test_debts_read_rates_balances_and_interest(db):
    ready(db)
    add_fact(db, "mortgage.rate_bp", "287.5")
    card = make_account(db, "Visa", type="credit")
    card.rate_bp = 2290
    db.commit()
    balance(db, card, -430_000)
    store = make_account(db, "Store card", type="credit")
    balance(db, store, -50_000)
    make_txn(db, store, date(2026, 9, 20), -1_200, "INTEREST CHARGE", category="interest")
    paid = make_account(db, "Paid-off card", type="credit")
    balance(db, paid, 0)
    nd = nd_for(db)
    by_name = {d.name: d for d in nd.debts}
    assert set(by_name) == {"Visa", "Store card", "Mortgage"}
    assert (by_name["Visa"].owed_cents, by_name["Visa"].rate_bp, by_name["Visa"].interest_charged) == (430_000, 2290, False)
    assert (by_name["Store card"].rate_bp, by_name["Store card"].interest_charged) == (None, True)
    m = by_name["Mortgage"]
    assert (m.owed_cents, m.rate_bp, m.is_mortgage) == (40_000_000, 287.5, True)


def test_an_account_rate_beats_the_mortgage_fact(db):
    accts = ready(db)
    add_fact(db, "mortgage.rate_bp", "287.5")
    accts["mortgage"].rate_bp = 650
    db.commit()
    assert next(d for d in nd_for(db).debts if d.is_mortgage).rate_bp == 650


def test_a_single_filer_has_one_adult(db):
    ready(db)
    add_fact(db, "filing_status", "single", as_of=date(2026, 10, 5))
    nd = nd_for(db)
    assert (nd.owners, nd.ages, nd.ira_in_cents) == (("JR",), (44,), (0,))
    assert nd.now.filing == "single" and nd.now.ss_wages_by_person_cents == (16_000_000,)
    assert nd.hsa_family                           # a child still makes it family coverage


def test_solo_401k_room_counts_all_of_jrs_deferrals_roth_included(db):
    ready(db)
    add_fact(db, "jr.k401_roth_share_bp", "10000", as_of=date(2026, 10, 2))
    db.add(BusinessState(key="type", value="sole_prop", updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    db.commit()
    nd = nd_for(db)
    assert nd.business_owner == 0
    assert nd.business_owner_w2_deferral_cents == 1_600_000   # 10% of $160,000, all Roth, still counts toward 402(g)
    assert nd.now.wages_cents == 16_000_000                    # Roth deferrals stay in taxable wages


def test_the_adult_who_runs_the_business_sets_the_owner_and_their_own_deferrals(db):
    """Final review I-2: Sam runs the business and JR holds the W-2 job. Sam's age, none of JR's deferrals, and only
    Sam's (zero) wages against the Social Security wage base."""
    from steward.business.settings import update_settings
    ready(db)
    update_settings(db, {"type": "sole_prop", "owner": "spouse"}, year=2026, this_year=2026, periods=2, user_id=1,
                    at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    db.commit()
    nd = nd_for(db)
    assert nd.business_owner == 1 and nd.business_owner_w2_deferral_cents == 0
    assert nd.now.business_owner == 1 and nd.now.ss_wages_by_person_cents == (16_000_000, 0)


def test_a_spouse_owner_falls_back_to_the_one_adult_for_a_single_filer(db):
    from steward.business.settings import update_settings
    ready(db)
    update_settings(db, {"type": "sole_prop", "owner": "spouse"}, year=2026, this_year=2026, periods=2, user_id=1,
                    at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    add_fact(db, "filing_status", "single", as_of=date(2026, 10, 5))
    nd = nd_for(db)
    assert nd.business_owner == 0 and nd.business_owner_w2_deferral_cents == 1_600_000


def test_payroll_amounts_are_this_years_facts(db):
    """Final review ruling I3: a dated fact per person and year; last year's amount is blank this year."""
    ready(db)
    add_fact(db, "jr.payroll_hsa_cents", "500000", as_of=date(2025, 12, 1))
    add_fact(db, "jr.payroll_k401_cents", "900000", as_of=date(2025, 12, 1))
    nd = nd_for(db)
    assert (nd.hsa_payroll_cents, nd.k401_payroll_cents) == (None, None)
    add_fact(db, "jr.payroll_hsa_cents", "600000", as_of=date(2026, 9, 30))
    add_fact(db, "jr.payroll_k401_cents", "1200000", as_of=date(2026, 9, 30))
    nd = nd_for(db)
    assert (nd.hsa_payroll_cents, nd.k401_payroll_cents) == (600_000, 1_200_000)
