from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, select, update

from steward.db.models import Account, AccountType, BalanceSnapshot, Child, Fact, SetupStep, SsEarnings
from steward.engine import EngineInputs, solve
from steward.services import asset_classes as ac
from steward.services.plan_inputs import (
    SUGGESTED_HEALTH_PREMIUM_CENTS, SetupIncomplete, build_checklist, build_inputs, missing, owner_names, setup_items,
)
from tests.factories import add_fact, make_account, make_ready_household, make_txn, make_user

TODAY = date(2026, 10, 13)


def keys(items):
    return [i.key for i in items]


def test_empty_vault_lists_every_required_input(db):
    items = setup_items(db, TODAY)
    assert keys(missing(items)) == ["household", "pay", "earnings", "children", "health", "history"]
    assert "mortgage" not in keys(items)
    health = next(i for i in items if i.key == "health")
    assert health.suggested_cents == SUGGESTED_HEALTH_PREMIUM_CENTS == 1_680_000
    assert health.as_dict()["suggested_cents"] == 1_680_000
    spouse = next(i for i in items if i.key == "earnings_spouse")
    assert not spouse.required and not spouse.done
    with pytest.raises(SetupIncomplete) as e:
        build_inputs(db, TODAY)
    assert keys(e.value.items) == keys(missing(items))


def test_ready_household_has_nothing_missing(db):
    make_ready_household(db)
    items = setup_items(db, TODAY)
    assert missing(items) == []
    assert next(i for i in items if i.key == "mortgage").done


def test_an_unclaimed_529_or_missing_mortgage_payment_holds_setup_back(db):
    make_ready_household(db)
    make_account(db, "529 Middle", type="plan529")
    db.execute(delete(Fact).where(Fact.key == "mortgage.payment_cents"))
    db.commit()
    gaps = missing(setup_items(db, TODAY))
    assert keys(gaps) == ["children", "mortgage"]
    assert gaps[0].detail == "Say which child 529 Middle belongs to."


def test_build_inputs_from_the_vault(db):
    make_user(db)
    make_user(db, "sam", "sam@x.com", "Sam")
    make_ready_household(db)
    pi = build_inputs(db, TODAY)
    hh = pi.household
    assert (hh.plan_year, hh.jr.birth_year, hh.jr.sex, hh.spouse.birth_year, hh.spouse.sex) == (2026, 1982, "male", 1984, "female")
    assert len(hh.jr.earnings) == 22 and hh.jr.earnings[0] == (2004, 3_000_000) and hh.spouse.earnings == ()
    assert (hh.filing_status, hh.state, hh.salary_cents, hh.k401_pct_bp, hh.k401_roth_share_bp, hh.match_rate_bp,
            hh.match_cap_bp) == ("mfj", "CA", 16_000_000, 1_000, 0, 5_000, 600)
    assert (hh.spending_basis_cents, hh.spending_months, hh.surplus_cents) == (7_200_000, 12, 2_400_000)
    assert (hh.mortgage_payment_cents, hh.mortgage_payoff_year, hh.health_premium_cents) == (3_600_000, 2048, 2_400_000)
    assert hh.cash.balance_cents == 4_000_000 and hh.cash.mix == ac.CASH_MIX
    assert hh.taxable.balance_cents == 15_000_000 and hh.taxable.mix.stock == pytest.approx(0.6) and hh.taxable.mix.fee_bp == 3
    assert hh.traditional.balance_cents == 45_000_000 and hh.traditional.mix.stock == pytest.approx(0.7)
    assert hh.traditional.mix.fee_bp == 20
    assert hh.roth.balance_cents == 9_000_000 and hh.roth.mix.stock == pytest.approx(0.7) and hh.hsa.balance_cents == 0
    assert [(c.label, c.birth_year, c.cost_level, c.plan529.balance_cents, c.monthly_contribution_cents) for c in hh.children] == \
        [("Oldest", 2015, "in_state_public", 3_000_000, 30_000)]
    assert hh.default_mix_symbols == ("ZZFUNDX",)
    assert hh.one_off_costs == ()
    assert hh.stale_notes == ("Lifespans use the male life table for JR and the female one for Sam.",
                              "Roth IRA has no holdings listed, so it uses the default mix for its type.",
                              "529 Oldest has no holdings listed, so it uses the default mix for its type.")
    assert (pi.observed.consulting_12mo_cents, pi.observed.gift_12mo_cents, pi.observed.spouse_earnings_cents) == (600_000, 1_000_000, 0)
    assert pi.facts_as_of["jr.salary_cents"] == "2026-10-01"
    assert pi.names == {"jr": "JR", "spouse": "Sam", "joint": "Joint"}
    res = solve(EngineInputs(hh))
    assert res.comfortable_age is not None and any("ZZFUNDX" in a for a in res.assumptions)


def test_filing_status_and_stale_balances_get_notes(db):
    accts = make_ready_household(db)
    add_fact(db, "filing_status", "hoh", as_of=date(2026, 10, 2))
    db.execute(delete(BalanceSnapshot).where(BalanceSnapshot.account_id == accts["p529"].id))
    db.add(BalanceSnapshot(account_id=accts["p529"].id, as_of=date(2026, 6, 1), balance_cents=3_000_000))
    db.commit()
    pi = build_inputs(db, TODAY)
    assert pi.household.filing_status == "single"
    assert "The hoh filing status is taxed with the single brackets (approximate)." in pi.household.stale_notes
    assert "529 Oldest's balance was last updated 134 days ago." in pi.household.stale_notes


def test_checklist_inputs(db):
    make_user(db)
    make_user(db, "sam", "sam@x.com", "Sam")
    accts = make_ready_household(db)
    card = make_account(db, "Card", type="credit")
    make_txn(db, card, date(2026, 9, 20), -2_500, "INTEREST CHARGE", category="interest")
    make_txn(db, accts["roth"], date(2026, 3, 1), 50_000, "CONTRIBUTION", category="transfer", is_transfer=True)
    ci, names = build_checklist(db, TODAY)
    # the card's $25 interest is spending
    assert ci.spending_basis_cents == 7_202_500 and ci.cash_cents == 4_000_000
    assert (ci.k401_pct_bp, ci.match_cap_bp, ci.k401_contribution_cents) == (1_000, 600, 1_600_000)
    assert ci.has_credit_accounts and ci.interest_charges_3mo == 1
    assert not ci.has_hsa and ci.hsa_contributions_12mo_cents is None
    assert ci.owners == ("JR", "Sam") and ci.roth_contributed_owners == frozenset({"JR"})
    assert ci.taxable_contributions_12mo_cents is None          # the brokerage has no transactions at all
    assert names["spouse"] == "Sam"


def test_checklist_ignores_dividends_and_sale_proceeds(db):
    """Leftovers #12: Sam's Roth only had a dividend and the brokerage only a sale, so neither counts as money put in."""
    make_user(db)
    make_user(db, "sam", "sam@x.com", "Sam")
    accts = make_ready_household(db)
    sam_roth = make_account(db, "Sam Roth", type="roth_ira", owner="spouse")
    make_txn(db, sam_roth, date(2026, 6, 1), 9_999, "DIVIDEND", category="income")
    make_txn(db, accts["taxable"], date(2026, 6, 1), 1_500_000, "SOLD VTI", category="uncategorized")
    ci, _ = build_checklist(db, TODAY)
    assert ci.roth_contributed_owners == frozenset()
    assert ci.taxable_contributions_12mo_cents == 0


def test_checklist_works_before_setup(db):
    ci, names = build_checklist(db, TODAY)
    assert ci.spending_basis_cents == 0 and ci.k401_pct_bp is None and ci.k401_contribution_cents is None
    assert not ci.has_credit_accounts and ci.interest_charges_3mo is None
    assert names == {"jr": "Person 1", "spouse": "Person 2", "joint": "Joint"}


def test_owner_names_put_the_earliest_manager_first(db):
    make_user(db, "jr", "jr@x.com", "J.R.")
    make_user(db, "sam", "sam@x.com", "Sam")
    assert owner_names(db) == {"jr": "J.R.", "spouse": "Sam", "joint": "Joint"}


def test_doesnt_apply_satisfies_kids_but_never_an_open_mortgage(db):
    u = make_user(db)
    make_ready_household(db)
    db.execute(delete(Child))
    db.execute(update(Account).where(Account.type == AccountType.plan529).values(is_active=False))  # no kids or 529s
    db.execute(delete(Fact).where(Fact.key.in_(("mortgage.payment_cents", "mortgage.payoff_date"))))
    db.commit()
    assert keys(missing(setup_items(db, TODAY))) == ["children", "mortgage"]
    at = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)
    db.add(SetupStep(step="kids", status="skipped", user_id=u.id, at=at))
    db.commit()
    assert keys(missing(setup_items(db, TODAY))) == ["children", "mortgage"]
    db.get(SetupStep, "kids").status = "doesnt_apply"
    db.commit()
    assert keys(missing(setup_items(db, TODAY))) == ["mortgage"]
    with pytest.raises(SetupIncomplete):
        build_inputs(db, TODAY)
    add_fact(db, "mortgage.payment_cents", "300000")
    add_fact(db, "mortgage.payoff_date", "2048-06-01")
    assert build_inputs(db, TODAY).household.children == ()


def test_the_plan_never_waits_on_the_mortgage_rate_but_profile_does(db):
    """Preflight F1: JR's mortgage syncs without a rate; Profile asks for it, the Plan never gates on it."""
    from steward.services import profile
    make_ready_household(db)
    assert db.query(Fact).filter(Fact.key == "mortgage.rate_bp").count() == 0
    assert missing(setup_items(db, TODAY)) == []
    assert build_inputs(db, TODAY).household.mortgage_payment_cents == 3_600_000
    assert profile.missing(db)["home"] == ["whether you own a home"]   # the ready household says nothing about the home itself
    add_fact(db, "home.owns", "yes")
    add_fact(db, "home.value_cents", "125000000")
    assert profile.missing(db)["home"] == ["the mortgage's interest rate"]


def test_a_removed_kid_is_left_out_of_the_plan(db):
    make_ready_household(db)
    db.add(Child(label="Gone", birth_year=2012, cost_level="private", monthly_contribution_cents=0,
                 removed_at=datetime(2026, 10, 13, tzinfo=timezone.utc)))
    db.commit()
    assert [c.label for c in build_inputs(db, TODAY).household.children] == ["Oldest"]


def test_an_accounts_advisory_fee_adds_to_its_fee_in_the_plan(db):
    from datetime import date
    from steward.services.plan_inputs import build_inputs
    from tests.factories import make_ready_household
    accts = make_ready_household(db)
    before = build_inputs(db, date(2026, 10, 13)).household.taxable.mix.fee_bp
    accts["taxable"].advisory_fee_bp = 25
    db.commit()
    assert build_inputs(db, date(2026, 10, 13)).household.taxable.mix.fee_bp == before + 25


def test_not_sure_is_costed_as_in_state_public_and_share_and_living_reach_the_engine(db):
    make_ready_household(db)
    kid = db.scalar(select(Child))
    kid.cost_level, kid.share_pct, kid.covers_living = "not_sure", 50, False
    db.commit()
    c = build_inputs(db, TODAY).household.children[0]
    assert (c.cost_level, c.share_pct, c.covers_living) == ("in_state_public", 50, False)


def test_with_no_record_jr_s_estimate_lets_the_plan_run(db):
    make_ready_household(db)
    db.execute(delete(SsEarnings).where(SsEarnings.person == "jr"))
    db.commit()
    earnings = next(i for i in setup_items(db, TODAY) if i.key == "earnings")
    assert (earnings.title, earnings.done) == ("Social Security", False)
    add_fact(db, "jr.ss_estimate", "yes")
    assert missing(setup_items(db, TODAY)) == []
    jr = build_inputs(db, TODAY).household.jr
    assert jr.estimated and jr.earnings[0][0] == 2004 and jr.earnings[-1][0] == 2025


def test_a_record_wins_over_the_estimate(db):
    make_ready_household(db)
    add_fact(db, "jr.ss_estimate", "yes")
    jr = build_inputs(db, TODAY).household.jr
    assert not jr.estimated and jr.earnings[0] == (2004, 3_000_000)
