from dataclasses import replace

from steward.engine.checklist import (
    HSA_FAMILY_LIMIT_CENTS, K401_LIMIT_CENTS, ROTH_IRA_LIMIT_CENTS, ChecklistInputs, savings_checklist,
)

GOOD = ChecklistInputs(
    spending_basis_cents=8_400_000, cash_cents=2_500_000, k401_pct_bp=1_000, match_cap_bp=600, k401_contribution_cents=2_450_000,
    has_credit_accounts=True, interest_charges_3mo=0, has_hsa=True, hsa_contributions_12mo_cents=875_000,
    owners=("jr", "spouse"), roth_contributed_owners=frozenset({"jr", "spouse"}), taxable_contributions_12mo_cents=120_000,
)


def test_limits_are_the_2026_published_figures():
    assert (K401_LIMIT_CENTS, ROTH_IRA_LIMIT_CENTS, HSA_FAMILY_LIMIT_CENTS) == (2_450_000, 750_000, 875_000)


def test_seven_items_in_spec_order_all_done():
    items = savings_checklist(GOOD)
    assert [i.key for i in items] == ["emergency_fund", "full_match", "no_card_balance", "hsa", "roth_ira", "k401_limit", "taxable"]
    assert [i.status for i in items] == ["done"] * 7
    assert items[0].title == "Emergency fund" and items[0].why == "Cash accounts hold 3.6 months of spending; the target is three."
    assert all(i.why.endswith(".") for i in items)


def test_not_yet_with_reasons():
    items = {i.key: i for i in savings_checklist(replace(
        GOOD, cash_cents=1_000_000, k401_pct_bp=400, interest_charges_3mo=2, hsa_contributions_12mo_cents=100_000,
        roth_contributed_owners=frozenset({"jr"}), k401_contribution_cents=1_000_000, taxable_contributions_12mo_cents=0))}
    assert items["emergency_fund"].status == "not_yet" and "1.4 months" in items["emergency_fund"].why
    assert items["full_match"].status == "not_yet" and "4%" in items["full_match"].why and "6%" in items["full_match"].why
    assert items["no_card_balance"].status == "not_yet" and "2 interest charges" in items["no_card_balance"].why
    assert items["hsa"].status == "not_yet" and "$1,000" in items["hsa"].why and "$8,750" in items["hsa"].why
    assert items["roth_ira"].status == "not_yet" and "spouse" in items["roth_ira"].why
    assert items["k401_limit"].status == "not_yet" and "$10,000" in items["k401_limit"].why and "$24,500" in items["k401_limit"].why
    assert items["taxable"].status == "not_yet"


def test_cant_tell_when_the_vault_has_no_data():
    items = {i.key: i for i in savings_checklist(replace(
        GOOD, spending_basis_cents=0, k401_pct_bp=None, match_cap_bp=None, k401_contribution_cents=None,
        interest_charges_3mo=None, hsa_contributions_12mo_cents=None, taxable_contributions_12mo_cents=None))}
    assert items["emergency_fund"].status == "cant_tell" and "spending" in items["emergency_fund"].why
    assert items["full_match"].status == "cant_tell" and "pay" in items["full_match"].why.lower()
    assert items["no_card_balance"].status == "cant_tell"
    assert items["hsa"].status == "cant_tell"
    assert items["k401_limit"].status == "cant_tell"
    assert items["taxable"].status == "cant_tell"


def test_no_credit_accounts_and_no_hsa():
    items = {i.key: i for i in savings_checklist(replace(GOOD, has_credit_accounts=False, has_hsa=False, hsa_contributions_12mo_cents=None))}
    assert items["no_card_balance"].status == "done" and "No credit-card accounts" in items["no_card_balance"].why
    assert items["hsa"].status == "cant_tell" and "if your health plan qualifies" in items["hsa"].why


def test_single_adult_household():
    items = {i.key: i for i in savings_checklist(replace(GOOD, owners=("jr",), roth_contributed_owners=frozenset()))}
    assert items["roth_ira"].status == "not_yet" and "jr" in items["roth_ira"].why


def _item(ci, key):
    return {i.key: i for i in savings_checklist(ci)}[key]


def test_emergency_fund_status_agrees_with_the_rounded_figure_shown():
    item = _item(replace(GOOD, cash_cents=2_090_000), "emergency_fund")
    assert item.status == "done"
    assert item.why == "Cash accounts hold 3.0 months of spending; the target is three."


def test_roth_ira_cant_tell_when_no_owners_are_recorded():
    item = _item(replace(GOOD, owners=(), roth_contributed_owners=frozenset()), "roth_ira")
    assert item.status == "cant_tell"
    assert item.why == "No adults are recorded for this household."


def test_roth_ira_single_owner_done_wording_and_not_yet_is_one_sentence():
    one = replace(GOOD, owners=("jr",), roth_contributed_owners=frozenset({"jr"}))
    assert _item(one, "roth_ira").why == "Added to a Roth IRA in the last 12 months."
    missing = _item(replace(GOOD, roth_contributed_owners=frozenset({"jr"})), "roth_ira")
    assert missing.why == "No Roth IRA contribution in the last 12 months for: spouse."
