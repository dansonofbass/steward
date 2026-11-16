from datetime import date

from steward.services.vault_flows import complete_months, derive_flows, month_add, months_between, window
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 13)


def monthly(db, acct, day, cents, raw, category, months=12, first=date(2025, 10, 1), **kw):
    for i in range(months):
        make_txn(db, acct, month_add(first, i).replace(day=day), cents, raw, category=category, **kw)


def test_month_helpers():
    assert month_add(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert month_add(date(2025, 11, 1), 14) == date(2027, 1, 1)
    assert months_between(date(2025, 10, 1), date(2026, 10, 1)) == 12
    assert window(TODAY) == (date(2025, 10, 1), date(2026, 10, 1))


def test_spending_basis_and_surplus_match_a_hand_sum(db):
    chk = make_account(db, "Checking", type="checking")
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    monthly(db, chk, 1, 500_000, "PAYROLL", "income")
    monthly(db, chk, 10, -200_000, "GROCER", "groceries")
    for d in (date(2025, 10, 28), date(2026, 1, 28), date(2026, 4, 28), date(2026, 7, 28)):
        make_txn(db, chk, d, -50_000, "IRS ESTIMATED", category="taxes")                 # the engine computes taxes
    make_txn(db, chk, date(2026, 2, 2), -100_000, "TO SAVINGS", category="transfer", is_transfer=True)
    make_txn(db, chk, date(2026, 2, 3), -30_000, "CLIENT LUNCH", category="dining", is_business=True)
    make_txn(db, biz, date(2026, 3, 3), 300_000, "CLIENT A", category="business_income", is_business=True)
    make_txn(db, biz, date(2026, 6, 3), 300_000, "CLIENT B", category="business_income", is_business=True)
    make_txn(db, chk, date(2025, 12, 20), 1_000_000, "GIFT FROM FAMILY", category="gifts")   # the gift: a lever, not income
    make_txn(db, chk, date(2025, 12, 22), -5_000, "FLOWER CART", category="gifts")           # buying a gift is spending
    make_txn(db, chk, date(2025, 9, 15), -999_999, "BEFORE THE WINDOW", category="shopping")
    make_txn(db, chk, date(2026, 10, 5), -777, "THIS MONTH", category="shopping")
    f = derive_flows(db, TODAY)
    assert (f.months, f.start, f.end) == (12, date(2025, 10, 1), date(2026, 10, 1))
    assert f.money_in_cents == 6_000_000 and f.money_out_cents == 2_405_000 and f.mortgage_paid_cents == 0
    assert f.spending_basis_cents == 2_405_000 and f.surplus_cents == 3_595_000
    assert f.gift_12mo_cents == 1_000_000 and f.consulting_12mo_cents == 600_000


def test_partial_first_month_is_left_out_and_the_rest_annualized(db):
    chk = make_account(db, "Checking", type="checking")
    make_txn(db, chk, date(2026, 3, 17), -50_000, "FIRST DAY OF HISTORY", category="shopping")
    monthly(db, chk, 1, 400_000, "PAYROLL", "income", months=6, first=date(2026, 4, 1))
    monthly(db, chk, 12, -100_000, "DINER", "dining", months=6, first=date(2026, 4, 1))
    f = derive_flows(db, TODAY)
    assert (f.months, f.start) == (6, date(2026, 4, 1))
    assert f.money_out_cents == 600_000 and f.spending_basis_cents == 1_200_000
    assert f.surplus_cents == 3_600_000
    assert complete_months(db, TODAY) == 6


def _mortgage_household(db, paired, months=12):
    chk = make_account(db, "Checking", type="checking")
    mort = make_account(db, "Mortgage", type="mortgage")
    monthly(db, chk, 1, 800_000, "PAYROLL", "income")
    monthly(db, chk, 9, -100_000, "GROCER", "groceries")
    for i in range(months):
        d = month_add(date(2025, 10, 1), i).replace(day=5)
        if paired:
            out = make_txn(db, chk, d, -268_000, "LOAN PAYMENT", category="transfer", is_transfer=True)
            inn = make_txn(db, mort, d, 268_000, "PAYMENT RECEIVED", category="transfer", is_transfer=True)
            out.transfer_peer_id, inn.transfer_peer_id = inn.id, out.id
            db.commit()
        else:
            make_txn(db, chk, d, -268_000, "HOME LOAN SVC", category="housing")


def test_unpaired_mortgage_payments_leave_the_basis_but_not_the_surplus(db):
    _mortgage_household(db, paired=False)
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.mortgage_paid_cents == 3_216_000
    assert f.spending_basis_cents == 1_200_000 and f.surplus_cents == 5_184_000


def test_paired_mortgage_transfers_are_not_subtracted_twice(db):
    _mortgage_household(db, paired=True)
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.mortgage_paid_cents == 3_216_000
    assert f.spending_basis_cents == 1_200_000 and f.surplus_cents == 5_184_000      # the same as unpaired


def test_escrow_in_a_paired_mortgage_transfer_stays_in_spending(db):
    chk = make_account(db, "Checking", type="checking")
    mort = make_account(db, "Mortgage", type="mortgage")
    monthly(db, chk, 1, 800_000, "PAYROLL", "income")
    monthly(db, chk, 9, -100_000, "GROCER", "groceries")
    for i in range(12):                    # $2,680 of principal and interest plus $400 of escrow, sent as one transfer
        d = month_add(date(2025, 10, 1), i).replace(day=5)
        out = make_txn(db, chk, d, -308_000, "LOAN PAYMENT", category="transfer", is_transfer=True)
        inn = make_txn(db, mort, d, 308_000, "PAYMENT RECEIVED", category="transfer", is_transfer=True)
        out.transfer_peer_id, inn.transfer_peer_id = inn.id, out.id
        db.commit()
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.mortgage_paid_cents == 3_216_000
    assert f.spending_basis_cents == 1_680_000 and f.surplus_cents == 4_704_000


def _paired_months(db, amounts, **out_kw):
    chk = make_account(db, "Checking", type="checking")
    mort = make_account(db, "Mortgage", type="mortgage")
    monthly(db, chk, 1, 800_000, "PAYROLL", "income")
    monthly(db, chk, 9, -100_000, "GROCER", "groceries")
    for i, cents in enumerate(amounts):
        d = month_add(date(2025, 10, 1), i).replace(day=5)
        out = make_txn(db, chk, d, -cents, "LOAN PAYMENT", category="transfer", is_transfer=True, **out_kw)
        inn = make_txn(db, mort, d, cents, "PAYMENT RECEIVED", category="transfer", is_transfer=True)
        out.transfer_peer_id, inn.transfer_peer_id = inn.id, out.id
        db.commit()


def test_a_regular_payment_with_escrow_counts_the_escrow_as_spending(db):
    _paired_months(db, [368_000] * 12)                                # $2,680 P&I and $1,000 of taxes and insurance
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.spending_basis_cents == 1_200_000 + 12 * 100_000


def test_an_extra_principal_month_is_capped_at_the_usual_escrow(db):
    _paired_months(db, [368_000] * 11 + [518_000])                    # $1,500 extra principal on top
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.spending_basis_cents == 1_200_000 + 12 * 100_000


def test_a_payoff_transfer_counts_nothing_and_is_not_a_payment(db):
    _paired_months(db, [268_000] * 11 + [15_000_000])                 # the last month pays off $150,000
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.spending_basis_cents == 1_200_000 - 268_000              # that month's payment is not among the paired ones


def test_escrow_is_capped_at_two_percent_of_the_home_value_a_year(db):
    _paired_months(db, [368_000] * 12)
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1), home_value_cents=20_000_000)    # $200,000 home
    assert f.spending_basis_cents == 1_200_000 + 400_000


def test_transfers_after_the_payoff_month_are_not_spending(db):
    _paired_months(db, [308_000] * 12)                                # $400 escrow a month, paid off in April
    f = derive_flows(db, TODAY, 268_000, date(2026, 4, 15))
    assert f.mortgage_paid_cents == 1_608_000
    assert f.spending_basis_cents == 1_200_000 + 6 * 40_000             # only the six months before payoff carry escrow


def test_payments_stop_counting_at_the_payoff_month(db):
    _mortgage_household(db, paired=False, months=6)                                   # Oct-Mar, paid off in April
    f = derive_flows(db, TODAY, 268_000, date(2026, 4, 15))
    assert f.mortgage_paid_cents == 1_608_000
    assert f.spending_basis_cents == 1_200_000 and f.surplus_cents == 6_792_000


def test_no_complete_month_means_no_figures(db):
    assert derive_flows(db, TODAY).months == 0 and complete_months(db, TODAY) == 0
    chk = make_account(db, "Checking", type="checking")
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    make_txn(db, biz, date(2026, 1, 1), 300_000, "CLIENT", category="business_income", is_business=True)
    make_txn(db, chk, date(2026, 10, 2), -1_000, "THIS MONTH ONLY", category="dining")
    f = derive_flows(db, TODAY)
    assert (f.months, f.start, f.spending_basis_cents, f.surplus_cents) == (0, None, 0, 0)
    assert f.consulting_12mo_cents == 300_000


def _investment_rows(db):
    """A synced 401(k)'s payroll deferrals and a brokerage's dividend-and-reinvest pairs: the engine models these
    already, so they are not take-home money in or spending (ruling 5 narrowed: personal cash-flow accounts)."""
    k401 = make_account(db, "401(k)", type="k401", owner="jr")
    brk = make_account(db, "Brokerage", type="brokerage_taxable")
    monthly(db, k401, 15, 150_000, "PAYROLL CONTRIBUTION", "income")
    monthly(db, brk, 20, 40_000, "DIVIDEND", "income")
    monthly(db, brk, 21, -40_000, "REINVEST", "shopping")


def test_investment_account_rows_leave_basis_and_surplus_alone(db):
    chk = make_account(db, "Checking", type="checking")
    monthly(db, chk, 1, 500_000, "PAYROLL", "income")
    monthly(db, chk, 10, -200_000, "GROCER", "groceries")
    before = derive_flows(db, TODAY)
    _investment_rows(db)
    after = derive_flows(db, TODAY)
    assert (after.money_in_cents, after.money_out_cents) == (before.money_in_cents, before.money_out_cents)
    assert (after.spending_basis_cents, after.surplus_cents) == (2_400_000, 3_600_000)


def test_spending_counts_a_split_rows_personal_share(db):
    from steward.services.vault_flows import derive_flows
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 8, 1), -10_000, "GROCER", category="groceries")
    make_txn(db, chk, date(2026, 9, 4), -10_000, "MOBILE ONE WIRELESS", category="utilities", business_pct=40)
    f = derive_flows(db, date(2026, 10, 13))
    assert (f.months, f.money_out_cents) == (2, 16_000)


def test_a_zero_percent_deposit_on_a_business_account_is_not_consulting(db):
    """Final review N1: a deposit a person kept personal counts in money in, not in Consulting too."""
    from steward.business.tagging import set_business
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    t = make_txn(db, biz, date(2026, 3, 3), 300_000, "ACH CLIENT INV 1", category="business_income")
    set_business(t, 0, source="manual")
    make_txn(db, biz, date(2026, 3, 4), 200_000, "ACH CLIENT INV 2", category="business_income", is_business=True)
    db.commit()
    assert derive_flows(db, date(2026, 10, 13)).consulting_12mo_cents == 200_000


def test_a_business_row_sent_to_the_mortgage_carries_no_escrow_into_spending(db):
    _paired_months(db, [368_000] * 12, is_business=True)              # the business paid the household's mortgage
    f = derive_flows(db, TODAY, 268_000, date(2051, 3, 1))
    assert f.spending_basis_cents == 1_200_000


def _match(db, sa, t, due_on):
    from steward.db.models import SetAsideMatch
    db.add(SetAsideMatch(transaction_id=t.id, set_aside_id=sa.id, due_on=due_on, how="auto", late=False))
    db.commit()


def test_matched_property_tax_stays_in_the_basis_but_income_tax_and_a_one_off_leave_it(db):
    """Phase 11c, decisions 9 and 17."""
    from datetime import datetime, timezone
    from steward.db.models import SetAside
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    chk = make_account(db, "Checking", type="checking")
    monthly(db, chk, 1, 500_000, "PAYROLL", "income")
    monthly(db, chk, 10, -200_000, "GROCER", "groceries")
    county = make_txn(db, chk, date(2026, 4, 10), -421_000, "COUNTY TAX COLLECTOR", merchant="County Tax Collector", category="taxes")
    irs = make_txn(db, chk, date(2026, 4, 15), -300_000, "USTREAS IRS ESTIMATED TAX", category="taxes")
    roof = make_txn(db, chk, date(2026, 6, 5), -1_800_000, "ROOFERS INC", merchant="Roofers Inc", category="home")
    assert derive_flows(db, TODAY).money_out_cents == 2_400_000 + 1_800_000           # taxes out, the roof in, as before
    tax_sa = SetAside(name="Property tax", kind="twice_yearly", amount_cents=421_000, due_month=11, due_day=1, second_month=4,
                      second_day=10, first_month=date(2025, 1, 1), payee_key="COUNTY TAX COLLECTOR", category="taxes",
                      created_at=at, updated_at=at)
    irs_sa = SetAside(name="Estimated tax", kind="twice_yearly", amount_cents=300_000, due_month=4, due_day=15, second_month=10,
                      second_day=15, first_month=date(2025, 1, 1), payee_key="IRS", category="taxes", created_at=at, updated_at=at)
    roof_sa = SetAside(name="Roof", kind="one_off", amount_cents=1_800_000, due_year=2026, due_month=6, first_month=date(2025, 1, 1),
                       payee_key="ROOFERS INC", category="home", created_at=at, updated_at=at)
    db.add_all([tax_sa, irs_sa, roof_sa]); db.commit()
    _match(db, tax_sa, county, date(2026, 4, 10))
    _match(db, irs_sa, irs, date(2026, 4, 15))
    _match(db, roof_sa, roof, date(2026, 6, 1))
    f = derive_flows(db, TODAY)
    assert f.money_out_cents == 2_400_000 + 421_000                                      # property tax kept, income tax and the roof gone
    assert f.spending_basis_cents == 2_400_000 + 421_000
    roof_sa.archived_at = at
    db.commit()
    assert derive_flows(db, TODAY).money_out_cents == 2_400_000 + 421_000               # archived: its payment stays out
