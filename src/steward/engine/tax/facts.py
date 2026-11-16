"""What annual_tax takes and gives back (spec 3.3). Money is integer cents at this boundary, as everywhere in the engine."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from typing import Literal

from steward.engine.inputs import FILINGS, InputError

Filing = Literal["mfj", "single"]


@dataclass(frozen=True)
class TaxFacts:
    """One household's year. Amounts are yearly, in cents, and default to zero."""
    filing: Filing
    ages: tuple[int, ...]                      # each filer's age on December 31: one for single, two for mfj
    state: str                                 # two-letter code, e.g. "CA"
    wages_cents: int = 0                       # W-2 box 1: wages after pre-tax 401(k) and HSA payroll deferrals
    payroll_wages_cents: int | None = None     # W-2 box 5 (Medicare wages); None: the same as wages_cents
    federal_withholding_cents: int = 0
    state_withholding_cents: int = 0
    business_profit_cents: int = 0             # Schedule C net profit; a loss is negative
    business_sstb: bool = False                # a specified service business (consulting, health, law...) for the QBI rules
    scorp_profit_cents: int = 0                # S-corp K-1 ordinary income: business income, no self-employment tax
    business_w2_wages_cents: int = 0           # wages the business paid (an S-corp owner's salary included)
    business_owner: int = 0                    # which filer (an index into ages) owns the Schedule C business
    ss_wages_by_person_cents: tuple[int, ...] = ()  # each filer's own W-2 box 3 (Social Security) wages, in the order of
    #   ages. Schedule SE counts only the owner's own wages against the wage base. Empty: on a single return the wages
    #   are the filer's own; on a joint return none are counted as the owner's (the full self-employment tax).
    interest_cents: int = 0
    tax_exempt_interest_cents: int = 0
    ordinary_dividends_cents: int = 0          # the qualified part included
    qualified_dividends_cents: int = 0
    short_term_gains_cents: int = 0            # net; a loss is negative
    long_term_gains_cents: int = 0             # net; a loss is negative
    ira_distributions_cents: int = 0           # the taxable part
    pensions_cents: int = 0                    # the taxable part, annuities included
    social_security_cents: int = 0             # SSA-1099 box 5, everyone on the return together
    other_income_cents: int = 0                # any other taxable ordinary income
    hsa_contributions_cents: int = 0           # made outside payroll (Form 8889 deduction)
    payroll_hsa_cents: int = 0                 # HSA contributions through payroll (already out of wages_cents); California taxes them
    ira_deduction_cents: int = 0               # deductible traditional IRA contributions
    se_retirement_cents: int = 0               # SEP or solo 401(k) contributions for the self-employed (Schedule 1 line 16)
    se_health_insurance_cents: int = 0         # self-employed health insurance (Schedule 1 line 17)
    medical_cents: int = 0                     # unreimbursed medical and care costs, eligible long-term care premiums
    state_income_tax_cents: int = 0            # state income tax paid in the year (withholding and estimates)
    property_tax_cents: int = 0
    mortgage_interest_cents: int = 0
    charity_cents: int = 0                     # cash gifts to charities
    state_addback_cents: int = 0               # business costs the federal return deducts and the state doesn't (California's S-corp franchise tax); added to the state's income
    dependents: tuple[int, ...] = ()           # each dependent's age on December 31


_MAY_BE_NEGATIVE = {"business_profit_cents", "scorp_profit_cents", "short_term_gains_cents", "long_term_gains_cents"}


def validate_facts(f: TaxFacts) -> None:
    if f.filing not in FILINGS:
        raise InputError("The filing status must be 'mfj' or 'single'.")
    if len(f.ages) != (2 if f.filing == "mfj" else 1) or any(not isinstance(a, int) or not 0 <= a <= 120 for a in f.ages):
        raise InputError("Give one age for a single return and two for a joint return, each from 0 to 120.")
    if not (isinstance(f.state, str) and len(f.state) == 2 and f.state.isalpha() and f.state.isupper()):
        raise InputError("The state must be a two-letter code like CA.")
    if not (isinstance(f.business_owner, int) and 0 <= f.business_owner < len(f.ages)):
        raise InputError("The business owner must be one of the people on the return.")
    if f.ss_wages_by_person_cents and len(f.ss_wages_by_person_cents) != len(f.ages):
        raise InputError("Give each person's own wages, one amount per person on the return.")
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in f.ss_wages_by_person_cents):
        raise InputError("Each person's wages must be a whole number of cents, not negative.")
    if any(not isinstance(a, int) or not 0 <= a <= 120 for a in f.dependents):
        raise InputError("Each dependent's age must be from 0 to 120.")
    for fld in fields(f):
        if not fld.name.endswith("_cents") or fld.name == "ss_wages_by_person_cents":
            continue
        v = getattr(f, fld.name)
        if v is None and fld.name == "payroll_wages_cents":
            continue
        if not isinstance(v, int) or isinstance(v, bool):
            raise InputError(f"The {fld.name.removesuffix('_cents').replace('_', ' ')} must be a whole number of cents.")
        if v < 0 and fld.name not in _MAY_BE_NEGATIVE:
            raise InputError(f"The {fld.name.removesuffix('_cents').replace('_', ' ')} can't be negative.")
    if f.qualified_dividends_cents > f.ordinary_dividends_cents:
        raise InputError("Qualified dividends are part of ordinary dividends, so they can't be larger.")


@dataclass(frozen=True)
class FederalFigures:
    """What a state module needs from the federal return, in whole dollars."""
    agi: int
    taxable_social_security: int
    hsa_deduction: int


@dataclass(frozen=True)
class FederalTax:
    ordinary_cents: int            # income tax on ordinary income
    capital_gains_cents: int       # income tax on qualified dividends and long-term gains
    se_tax_cents: int              # self-employment tax
    additional_medicare_cents: int
    niit_cents: int                # net investment income tax


@dataclass(frozen=True)
class StateResult:
    state: str
    calculated: bool
    tax_cents: int = 0
    agi_cents: int = 0
    taxable_income_cents: int = 0
    credits_cents: int = 0
    rules_year: int | None = None
    explain: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaxResult:
    year: int
    rules_year: int                    # the federal rules used: the year's own, or the latest earlier
    agi_cents: int
    taxable_income_cents: int
    deduction_cents: int               # the standard deduction or the itemized total, whichever was taken
    itemized: bool
    over_65_deduction_cents: int
    qbi_deduction_cents: int
    taxable_social_security_cents: int
    federal: FederalTax
    credits_cents: int                 # child and other-dependent credits, the refundable part included
    federal_total_cents: int           # after credits; negative when a refundable credit exceeds the tax
    state: StateResult
    total_tax_cents: int
    withholding_cents: int
    marginal_rate: float               # federal and state tax on the next $100 of ordinary income, such as an IRA withdrawal
    effective_rate: float              # total tax over total income (Social Security in full, losses at zero)
    explain: tuple[str, ...]


@dataclass(frozen=True)
class Installment:
    due: date
    share: float                       # of the year's required payment
