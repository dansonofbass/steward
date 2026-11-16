"""Next dollar's inputs from the vault (cash-flow and tax spec section 6), household books only.

Built from the plan's cached PlanInputs (so setup must be finished, as for Plan) and a few reads: this year's tagged
transfers into each kind of account (steward.services.contributions, leftovers #12), the cards and loans with their
balances and rates, and three facts (the cash target in months, the debt rate setting, whether the health plan
qualifies for an HSA). A 401(k) owned by Business is the business plan; Person 1's own 401(k) is the employer's. The W-2
salary is Person 1's; who runs the business is a business setting (final review ruling I2)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.business.settings import business_type, owner_index
from steward.db.models import LIABILITY_TYPES, Account, AccountType, Owner, Transaction
from steward.engine.decisions import expected_real_return, later_facts_estimate
from steward.engine.inputs import InputError
from steward.engine.next_dollar import (
    CASH_MONTHS_BUSINESS, CASH_MONTHS_OTHER, DEFAULT_DEBT_RATE_BP, HSA_PLAN_ANSWERS, Debt, NextDollarInputs, Step,
)
from steward.engine.project import Assumptions
from steward.engine.tax.facts import TaxFacts
from steward.services.accounts import debt_rate_bp, latest_balance
from steward.services.contributions import contributions
from steward.services.plan import BACKDOOR_ROTH_SHEET
from steward.services.plan_inputs import PlanInputs, latest_facts

PAYROLL_KEYS = {"hsa": "jr.payroll_hsa_cents", "match": "jr.payroll_k401_cents"}   # by step; the W-2 pay is Person 1's
DEPENDENT_AGE_LIMIT = 19         # a qualifying child is under 19 on December 31 (students to 24 aren't counted)
INTEREST_LOOKBACK_DAYS = 90


def _ids(accounts: list[Account], *types: AccountType, owner: str | None = None) -> list[int]:
    return [a.id for a in accounts if a.type in types and (owner is None or a.owner == owner)]


def _later_rate(db: Session, today: date, pi: PlanInputs) -> float | None:
    """The saved plan's rate in retirement from the projection (tax decisions plan Task 8); None if it can't run."""
    from steward.taxes.roth import saved_plan_later_rate
    try:
        return saved_plan_later_rate(db, today, pi).rate
    except InputError:
        return None


def build_next_dollar(db: Session, today: date, pi: PlanInputs) -> NextDollarInputs:
    hh = pi.household
    facts = latest_facts(db)
    year = today.year
    start, end = date(year, 1, 1), today + timedelta(days=1)
    accounts = list(db.scalars(select(Account).where(Account.is_active.is_(True)).order_by(Account.id)))
    has_business = business_type(db) != "none"

    def fact_int(key: str, default: int) -> int:
        f = facts.get(key)
        return default if f is None else int(f.value)

    def this_year(key: str) -> int | None:
        """A payroll amount counts only in the year it is dated (final review ruling I3); None: blank."""
        f = facts.get(key)
        return int(f.value) if f is not None and f.as_of.year == year else None

    def put_in(ids: list[int]) -> int | None:
        return contributions(db, ids, start, end)

    mfj = hh.filing_status == "mfj"
    ages = (year - hh.jr.birth_year, year - hh.spouse.birth_year) if mfj else (year - hh.jr.birth_year,)
    owners = (pi.names["jr"], pi.names["spouse"])[:len(ages)]
    owner_keys = (Owner.jr.value, Owner.spouse.value)[:len(ages)]
    ira_in = tuple(put_in(_ids(accounts, AccountType.roth_ira, AccountType.traditional_ira, owner=k)) or 0
                   for k in owner_keys)
    hsa_ids = _ids(accounts, AccountType.hsa)

    since = today - timedelta(days=INTEREST_LOOKBACK_DAYS)
    charged = set(db.scalars(select(Transaction.account_id).where(
        Transaction.category == "interest", Transaction.amount_cents < 0, Transaction.posted_at >= since).distinct()))
    debts: list[Debt] = []
    for a in accounts:
        if a.type not in LIABILITY_TYPES:
            continue
        latest = latest_balance(db, a.id)          # a few cards and loans: far cheaper than every account's balance
        owed = -latest[1] if latest is not None else 0
        if owed <= 0:
            continue
        debts.append(Debt(a.id, a.name, owed, debt_rate_bp(a, facts), a.id in charged, a.type == AccountType.mortgage))

    salary, pct = hh.salary_cents, hh.k401_pct_bp
    pretax_401k = salary * pct * (10_000 - hh.k401_roth_share_bp) // 100_000_000
    kids = tuple(year - c.birth_year for c in hh.children if 0 <= year - c.birth_year < DEPENDENT_AGE_LIMIT)
    profit = pi.business
    owner = owner_index(db, len(ages))              # who runs the business (final review ruling I2); W-2 pay is Person 1's
    now = TaxFacts(filing=hh.filing_status, ages=ages, state=hh.state, wages_cents=salary - pretax_401k,
                   payroll_wages_cents=salary, ss_wages_by_person_cents=(salary, 0) if mfj else (salary,),
                   business_profit_cents=profit.mid_cents if profit is not None else 0, dependents=kids,
                   business_owner=owner)
    answer = facts.get("health.hsa_plan")
    return NextDollarInputs(
        year=year, month=today.month, owners=owners, ages=ages,
        spending_basis_cents=hh.spending_basis_cents, cash_cents=hh.cash.balance_cents,
        cash_months=fact_int("next_dollar.cash_months", CASH_MONTHS_BUSINESS if has_business else CASH_MONTHS_OTHER),
        has_business=has_business, business_profit_low_cents=profit.low_cents if profit is not None else 0,
        salary_cents=salary, k401_pct_bp=pct, match_rate_bp=hh.match_rate_bp, match_cap_bp=hh.match_cap_bp,
        k401_in_cents=put_in(_ids(accounts, AccountType.k401, owner=Owner.jr.value)),
        hsa_plan=answer.value if answer is not None and answer.value in HSA_PLAN_ANSWERS else None,
        hsa_family=mfj or bool(hh.children), has_hsa_account=bool(hsa_ids), hsa_in_cents=put_in(hsa_ids),
        ira_in_cents=ira_in,
        business_plan_in_cents=put_in(_ids(accounts, AccountType.k401, owner=Owner.business.value)),
        debts=tuple(debts), debt_rate_bp=fact_int("next_dollar.debt_rate_bp", DEFAULT_DEBT_RATE_BP),
        taxable_in_cents=put_in(_ids(accounts, AccountType.brokerage_taxable)),
        business_owner=owner,                    # 402(g) counts Roth and pre-tax deferrals alike; only the owner's own
        business_owner_w2_deferral_cents=salary * pct // 10_000 if owner == 0 else 0,
        hsa_payroll_cents=this_year(PAYROLL_KEYS["hsa"]), k401_payroll_cents=this_year(PAYROLL_KEYS["match"]),
        now=now, later=later_facts_estimate(now, hh.spending_basis_cents),
        real_return=expected_real_return(hh.taxable.mix), inflation=Assumptions().inflation,
        later_rate=_later_rate(db, today, pi),
    )


def next_dollar_out(nd: NextDollarInputs, steps: Sequence[Step]) -> dict:
    return {
        "year": nd.year,
        "settings": {"cash_months": nd.cash_months, "debt_rate_bp": nd.debt_rate_bp},
        "steps": [{"key": s.key, "title": s.title, "status": s.status, "why": s.why, "in_cents": s.in_cents,
                   "room_cents": s.room_cents, "rules_year": s.rules_year, "choice": s.choice,
                   "needs_rate": [{"account_id": aid, "name": name} for aid, name in s.needs_rate],
                   "payroll": {"key": PAYROLL_KEYS[s.key], "cents": s.payroll_cents}
                   if s.takes_payroll and s.key in PAYROLL_KEYS else None} for s in steps],
        "backdoor_sheet": BACKDOOR_ROTH_SHEET,
    }
