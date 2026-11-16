"""'Where savings should go' (spec section 4): seven items, each done, not yet or can't tell, with one sentence why."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from steward.engine.tax import rules

# 2026 limits from data/rules/retirement_2026.json (IRS Notice 2025-67; Rev. Proc. 2025-19).
_LIMITS = rules.table("retirement", 2026)
K401_LIMIT_CENTS = _LIMITS["k401_deferral"] * 100
ROTH_IRA_LIMIT_CENTS = _LIMITS["ira"] * 100
HSA_FAMILY_LIMIT_CENTS = _LIMITS["hsa"]["family"] * 100
EMERGENCY_MONTHS = 3

Status = Literal["done", "not_yet", "cant_tell"]


@dataclass(frozen=True)
class ChecklistInputs:
    spending_basis_cents: int                 # yearly
    cash_cents: int                           # checking + savings
    k401_pct_bp: int | None                   # None: pay not entered yet
    match_cap_bp: int | None
    k401_contribution_cents: int | None       # yearly, salary x percentage; None: pay not entered
    has_credit_accounts: bool
    interest_charges_3mo: int | None          # count of `interest` transactions on credit accounts; None: no history
    has_hsa: bool
    hsa_contributions_12mo_cents: int | None
    owners: tuple[str, ...]                   # the adults, e.g. ("jr", "spouse")
    roth_contributed_owners: frozenset[str]   # owners whose Roth IRA received contributions in the last 12 months
    taxable_contributions_12mo_cents: int | None


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    title: str
    status: Status
    why: str


def _dollars(cents: int) -> str:
    return f"${cents // 100:,.0f}"


def savings_checklist(ci: ChecklistInputs) -> tuple[ChecklistItem, ...]:
    items: list[ChecklistItem] = []

    # 1. Emergency fund
    if ci.spending_basis_cents <= 0:
        items.append(ChecklistItem("emergency_fund", "Emergency fund", "cant_tell", "There is no spending history to measure the fund against."))
    else:
        months = ci.cash_cents * 12 / ci.spending_basis_cents
        shown = round(months, 1)
        status: Status = "done" if shown >= EMERGENCY_MONTHS else "not_yet"
        items.append(ChecklistItem("emergency_fund", "Emergency fund", status,
                                   f"Cash accounts hold {shown:.1f} months of spending; the target is three."))

    # 2. Full 401(k) match
    if ci.k401_pct_bp is None or ci.match_cap_bp is None:
        items.append(ChecklistItem("full_match", "Full 401(k) match", "cant_tell", "Enter {person1}'s pay and match to check this."))
    elif ci.k401_pct_bp >= ci.match_cap_bp:
        items.append(ChecklistItem("full_match", "Full 401(k) match", "done",
                                   f"Contributing {ci.k401_pct_bp / 100:g}% of salary meets the {ci.match_cap_bp / 100:g}% match cap."))
    else:
        items.append(ChecklistItem("full_match", "Full 401(k) match", "not_yet",
                                   f"Contributing {ci.k401_pct_bp / 100:g}% of salary; the match runs to {ci.match_cap_bp / 100:g}%."))

    # 3. No carried credit-card balance
    if not ci.has_credit_accounts:
        items.append(ChecklistItem("no_card_balance", "No carried credit-card balance", "done", "No credit-card accounts in Steward."))
    elif ci.interest_charges_3mo is None:
        items.append(ChecklistItem("no_card_balance", "No carried credit-card balance", "cant_tell",
                                   "Credit-card transactions haven't been imported for the last three months."))
    elif ci.interest_charges_3mo == 0:
        items.append(ChecklistItem("no_card_balance", "No carried credit-card balance", "done", "No interest charges on credit cards in the last three months."))
    else:
        n = ci.interest_charges_3mo
        items.append(ChecklistItem("no_card_balance", "No carried credit-card balance", "not_yet",
                                   f"{n} interest charge{'s' if n != 1 else ''} on credit cards in the last three months."))

    # 4. HSA funded
    if not ci.has_hsa:
        items.append(ChecklistItem("hsa", "HSA funded", "cant_tell", "No HSA account in Steward; if your health plan qualifies, one belongs here."))
    elif ci.hsa_contributions_12mo_cents is None:
        items.append(ChecklistItem("hsa", "HSA funded", "cant_tell", "The HSA has no transaction history yet."))
    elif ci.hsa_contributions_12mo_cents >= HSA_FAMILY_LIMIT_CENTS:
        items.append(ChecklistItem("hsa", "HSA funded", "done", f"{_dollars(ci.hsa_contributions_12mo_cents)} went in over the last 12 months, the family limit."))
    else:
        items.append(ChecklistItem("hsa", "HSA funded", "not_yet",
                                   f"{_dollars(ci.hsa_contributions_12mo_cents)} went in over the last 12 months; the family limit is {_dollars(HSA_FAMILY_LIMIT_CENTS)}."))

    # 5. Roth IRA for each spouse
    missing = [o for o in ci.owners if o not in ci.roth_contributed_owners]
    if not ci.owners:
        items.append(ChecklistItem("roth_ira", "Roth IRA for each spouse", "cant_tell", "No adults are recorded for this household."))
    elif not missing:
        done_text = ("Added to a Roth IRA in the last 12 months." if len(ci.owners) == 1
                     else "Each of you added to a Roth IRA in the last 12 months.")
        items.append(ChecklistItem("roth_ira", "Roth IRA for each spouse", "done", done_text))
    else:
        items.append(ChecklistItem("roth_ira", "Roth IRA for each spouse", "not_yet",
                                   f"No Roth IRA contribution in the last 12 months for: {', '.join(missing)}."))

    # 6. 401(k) to the yearly limit
    if ci.k401_contribution_cents is None:
        items.append(ChecklistItem("k401_limit", "401(k) to the yearly limit", "cant_tell", "Enter {person1}'s pay to check this."))
    elif ci.k401_contribution_cents >= K401_LIMIT_CENTS:
        items.append(ChecklistItem("k401_limit", "401(k) to the yearly limit", "done", f"Contributions reach the {_dollars(K401_LIMIT_CENTS)} limit."))
    else:
        items.append(ChecklistItem("k401_limit", "401(k) to the yearly limit", "not_yet",
                                   f"Contributions are {_dollars(ci.k401_contribution_cents)} a year; the limit is {_dollars(K401_LIMIT_CENTS)}."))

    # 7. Investing beyond that in taxable
    if ci.taxable_contributions_12mo_cents is None:
        items.append(ChecklistItem("taxable", "Investing beyond that", "cant_tell", "No taxable brokerage history in Steward yet."))
    elif ci.taxable_contributions_12mo_cents > 0:
        items.append(ChecklistItem("taxable", "Investing beyond that", "done",
                                   f"{_dollars(ci.taxable_contributions_12mo_cents)} went into taxable investing in the last 12 months."))
    else:
        items.append(ChecklistItem("taxable", "Investing beyond that", "not_yet", "Nothing went into taxable investing in the last 12 months."))

    return tuple(items)
