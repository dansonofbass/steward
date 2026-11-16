"""The vault -> engine adapter. What Plan still needs before it can answer (spec 2.2, rulings 1-2), and the
engine's frozen input bundle built from facts, balances, holdings, children, earnings and transactions (spec 2.5)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import (
    Account, AccountType, BalanceSnapshot, Child, Fact, Owner, SetupStep, Source, SsEarnings, Transaction, active_children,
)
from steward.business.report import ProfitRange, profit_range
from steward.business.settings import business_type, owner_index
from steward.books.people import Person as BookPerson, household_labels, household_people, names_of, people_of
from steward.engine.social_security import estimated_record
from steward.engine import Bucket, ChecklistInputs, Household, Mix, ObservedTry, Person
from steward.engine import Child as EngineChild
from steward.services import asset_classes as ac
from steward.services import home_value
from steward.services import networth
from steward.services import setasides as sas
from steward.services.accounts import staleness_days
from steward.services.contributions import contributions
from steward.services.vault_flows import Flows, complete_months, derive_flows, window

SUGGESTED_HEALTH_PREMIUM_CENTS = 1_680_000   # $1,400 a month: 2026 unsubsidized Silver estimate, couple + two children (ruling 14)
STALE_MANUAL_DAYS = 90
BUCKET_OF = {
    AccountType.checking: "cash", AccountType.savings: "cash", AccountType.brokerage_taxable: "taxable",
    AccountType.k401: "traditional", AccountType.traditional_ira: "traditional", AccountType.roth_ira: "roth",
    AccountType.hsa: "hsa",
}
BUCKET_DEFAULTS = {"cash": ac.CASH_MIX, "taxable": ac.TAXABLE_DEFAULT, "traditional": ac.RETIREMENT_DEFAULT,
                   "roth": ac.RETIREMENT_DEFAULT, "hsa": ac.RETIREMENT_DEFAULT}
ENGINE_LEVEL = {"not_sure": "in_state_public"}   # P9: Profile keeps Not sure yet; the engine costs it as in-state public
HOUSEHOLD_FACTS = ("jr.dob", "spouse.dob", "state", "filing_status")
PAY_FACTS = ("jr.salary_cents", "jr.k401_pct_bp", "employer.match_rate_bp", "employer.match_cap_bp")


def latest_facts(db: Session) -> dict[str, Fact]:
    out: dict[str, Fact] = {}
    for f in db.scalars(select(Fact).order_by(Fact.as_of.asc(), Fact.id.asc())):
        out[f.key] = f
    return out


def owner_users(db: Session) -> tuple[BookPerson | None, BookPerson | None]:
    """Person 1 and Person 2 (books/people.py, household_people)."""
    return household_people(people_of(db))


def owner_names(db: Session) -> dict[str, str]:
    return {**household_labels(people_of(db)), "joint": "Joint"}


@dataclass(frozen=True)
class SetupItem:
    key: str
    title: str
    done: bool
    required: bool
    detail: str
    suggested_cents: int | None = None

    def as_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "done": self.done, "required": self.required,
                "detail": self.detail, "suggested_cents": self.suggested_cents}


class SetupIncomplete(RuntimeError):
    def __init__(self, items: list[SetupItem]):
        super().__init__("Plan setup isn't finished.")
        self.items = items


def _active(db: Session, *types: AccountType) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.is_active.is_(True), Account.type.in_(types)).order_by(Account.id)))


def unclaimed_529s(db: Session) -> list[Account]:
    """Active 529 accounts no kid is linked to; the Plan waits until each belongs to a kid."""
    linked = set(db.scalars(select(Child.account_id).where(Child.account_id.is_not(None), Child.removed_at.is_(None))))
    return [a for a in _active(db, AccountType.plan529) if a.id not in linked]


def not_applying(db: Session) -> set[str]:
    """Profile sections the household marked Doesn't apply (only Kids and college can be)."""
    return set(db.scalars(select(SetupStep.step).where(SetupStep.status == "doesnt_apply")))


def setup_items(db: Session, today: date) -> list[SetupItem]:
    facts = latest_facts(db)
    names = owner_names(db)

    def have(*keys: str) -> bool:
        return all(k in facts for k in keys)

    earnings = dict(db.execute(select(SsEarnings.person, func.count()).group_by(SsEarnings.person)).all())
    children = list(db.scalars(active_children()))
    unclaimed = unclaimed_529s(db)
    na = not_applying(db)
    children_done = (bool(children) and not unclaimed) or ("kids" in na and not children and not unclaimed)
    items = [
        SetupItem("household", "About you", have(*HOUSEHOLD_FACTS), True, "Both birth dates, your state and how you file taxes."),
        SetupItem("pay", "Pay", have(*PAY_FACTS), True, f"{names['jr']}'s salary, 401(k) contribution and the employer's match."),
        SetupItem("earnings", "Social Security", earnings.get("jr", 0) > 0 or _estimating(facts, "jr"), True,
                  f"{names['jr']}'s earnings record from my Social Security, or Steward's estimate."),
        SetupItem("earnings_spouse", f"{names['spouse']}'s earnings record", earnings.get("spouse", 0) > 0, False,
                  f"Optional. Without it, {names['spouse']} receives the spousal benefit only."),
        SetupItem("children", "Children", children_done, True,
                  f"Say which child {unclaimed[0].name} belongs to." if unclaimed and not children_done
                  else "Each kid's birth year, school and 529."),
    ]
    if home_value.main_mortgage(db) is not None:
        items.append(SetupItem("mortgage", "Mortgage payment",
                               have("mortgage.payment_cents", "mortgage.payoff_date"), True,
                               "The monthly principal and interest, and when the mortgage is paid off."))
    items.append(SetupItem("health", "Health insurance before Medicare", have("health.premium_cents"), True,
                           "A yearly premium for the household until Medicare.", SUGGESTED_HEALTH_PREMIUM_CENTS))
    items.append(SetupItem("history", "Spending history", complete_months(db, today) >= 1, True,
                           "At least one full month of transactions, from a bank connection or an import."))
    return items


def missing(items: list[SetupItem]) -> list[SetupItem]:
    return [i for i in items if i.required and not i.done]


@dataclass(frozen=True)
class SetAsidesNote:
    """What the Plan page says about set-asides (phase 11c): when they last changed, by whom, how many yearly ones
    are in the spending history, and the one-offs the engine pays in their year."""
    updated_at: str | None
    updated_by: str | None
    yearly_count: int
    one_offs: tuple[dict, ...]


@dataclass(frozen=True)
class PlanInputs:
    household: Household
    observed: ObservedTry
    flows: Flows
    facts_as_of: dict[str, str]
    names: dict[str, str]
    business: ProfitRange | None = None
    set_asides: SetAsidesNote = SetAsidesNote(None, None, 0, ())


def _int(facts: dict[str, Fact], key: str, default: int | None = None) -> int | None:
    f = facts.get(key)
    return default if f is None else int(f.value)


def _mortgage(db: Session, facts: dict[str, Fact]) -> tuple[int, date | None]:
    if home_value.main_mortgage(db) is None or "mortgage.payment_cents" not in facts:
        return 0, None
    payoff = facts.get("mortgage.payoff_date")
    return int(facts["mortgage.payment_cents"].value), date.fromisoformat(payoff.value) if payoff else None


def _estimating(facts: dict[str, Fact], person: str) -> bool:
    f = facts.get(f"{person}.ss_estimate")
    return f is not None and f.value == "yes"


def _earnings(db: Session, person: str) -> tuple[tuple[int, int], ...]:
    rows = db.execute(select(SsEarnings.year, SsEarnings.earnings_cents)
                      .where(SsEarnings.person == person).order_by(SsEarnings.year)).all()
    return tuple((y, c) for y, c in rows)


def build_inputs(db: Session, today: date) -> PlanInputs:
    gaps = missing(setup_items(db, today))
    if gaps:
        raise SetupIncomplete(gaps)
    facts = latest_facts(db)
    names = owner_names(db)
    plan_year = today.year
    notes = [f"Lifespans use the male life table for {names['jr']} and the female one for {names['spouse']}."]
    filing = facts["filing_status"].value
    if filing not in ("mfj", "single"):
        notes.append(f"The {filing} filing status is taxed with the single brackets (approximate).")
    monthly, payoff = _mortgage(db, facts)
    flows = derive_flows(db, today, monthly, payoff, home_value.current_value(db))

    newest = (select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.as_of).label("as_of"))
              .where(BalanceSnapshot.as_of <= today).group_by(BalanceSnapshot.account_id).subquery())
    rows = db.execute(select(Account, newest.c.as_of, BalanceSnapshot.balance_cents)
                      .join(newest, newest.c.account_id == Account.id)
                      .join(BalanceSnapshot, (BalanceSnapshot.account_id == newest.c.account_id) & (BalanceSnapshot.as_of == newest.c.as_of))
                      .where(Account.is_active.is_(True))).all()
    accounts = {a.id: a for a, _, _ in rows}
    last_dates = {a.id: d for a, d, _ in rows}
    balances = {a.id: c for a, _, c in rows}
    holdings, overrides = ac.latest_holdings(db), ac.overrides(db)
    parts: dict[str, list[tuple[int, Mix]]] = {b: [] for b in BUCKET_DEFAULTS}
    mixes: dict[int, Mix] = {}
    unknown: list[str] = []
    for aid in sorted(accounts):
        a = accounts[aid]
        bucket = BUCKET_OF.get(a.type)
        if bucket is None and a.type != AccountType.plan529:
            continue                                   # property, mortgage, credit, business, unknown: outside the plan
        am = ac.account_mix(holdings.get(aid, []), a.type, overrides, plan_year)
        # Investment views spec, Costs: an adviser's fee is part of what the account costs each year.
        mix = replace(am.mix, fee_bp=am.mix.fee_bp + a.advisory_fee_bp) if a.advisory_fee_bp else am.mix
        mixes[aid] = mix
        unknown.extend(am.unknown)
        if am.no_holdings and a.type not in ac.CASH_TYPES:
            notes.append(f"{a.name} has no holdings listed, so it uses the default mix for its type.")
        days = staleness_days(last_dates.get(aid), today)
        if a.source == Source.manual and days is not None and days > STALE_MANUAL_DAYS:
            notes.append(f"{a.name}'s balance was last updated {days} days ago.")
        if bucket:
            parts[bucket].append((balances[aid], mix))

    def bucket_of(name: str) -> Bucket:
        return Bucket(max(0, sum(w for w, _ in parts[name])), ac.blend(parts[name], BUCKET_DEFAULTS[name]))

    kids = []
    for c in db.scalars(active_children()):
        if c.account_id is not None and c.account_id in mixes:
            plan529 = Bucket(max(0, balances[c.account_id]), mixes[c.account_id])
        else:
            plan529 = Bucket(0, ac.RETIREMENT_DEFAULT)
        kids.append(EngineChild(c.label, c.birth_year, ENGINE_LEVEL.get(c.cost_level, c.cost_level), plan529,
                                c.monthly_contribution_cents, c.share_pct, c.covers_living))

    jr_born = date.fromisoformat(facts["jr.dob"].value).year
    jr_record = _earnings(db, "jr")
    jr_estimated = not jr_record and _estimating(facts, "jr")
    if jr_estimated:                                   # P24: the spouse's estimate stays the spousal benefit alone
        jr_record = estimated_record(jr_born, _int(facts, "jr.salary_cents"), plan_year)
    hh = Household(
        plan_year=plan_year,
        jr=Person(jr_born, "male", jr_record, estimated=jr_estimated),
        spouse=Person(date.fromisoformat(facts["spouse.dob"].value).year, "female", _earnings(db, "spouse")),
        filing_status="mfj" if filing == "mfj" else "single",
        state=facts["state"].value,
        salary_cents=_int(facts, "jr.salary_cents"),
        k401_pct_bp=_int(facts, "jr.k401_pct_bp"),
        k401_roth_share_bp=_int(facts, "jr.k401_roth_share_bp", 0),
        match_rate_bp=_int(facts, "employer.match_rate_bp"),
        match_cap_bp=_int(facts, "employer.match_cap_bp"),
        spending_basis_cents=flows.spending_basis_cents,
        spending_months=flows.months,
        surplus_cents=flows.surplus_cents,
        mortgage_payment_cents=monthly * 12,
        mortgage_payoff_year=payoff.year if payoff else None,
        health_premium_cents=_int(facts, "health.premium_cents"),
        cash=bucket_of("cash"), taxable=bucket_of("taxable"), traditional=bucket_of("traditional"),
        roth=bucket_of("roth"), hsa=bucket_of("hsa"),
        children=tuple(kids),
        stale_notes=tuple(notes),
        default_mix_symbols=tuple(sorted(set(unknown))),
        business_owner=owner_index(db, 2 if filing == "mfj" else 1),
        one_off_costs=sas.one_off_costs(db, plan_year),
    )
    business = profit_range(db, plan_year, today) if business_type(db) != "none" else None
    # Cash profit, never the Schedule C figure: the home office and mileage only lower tax (final review ruling I3).
    consulting = max(0, business.cash_mid_cents) if business is not None else flows.consulting_12mo_cents
    observed = ObservedTry(consulting_12mo_cents=consulting, gift_12mo_cents=flows.gift_12mo_cents,
                           spouse_earnings_cents=0)
    at, by = sas.last_change(db)
    who = names_of(people_of(db), mid=True).get(by) if by is not None else None
    note = SetAsidesNote(at.isoformat() if at else None, who, sum(1 for s in sas.active(db) if s.kind != "one_off"),
                         tuple(sas.plan_one_offs(db, plan_year)))
    return PlanInputs(hh, observed, flows, {k: f.as_of.isoformat() for k, f in facts.items()}, names, business, note)


def build_checklist(db: Session, today: date) -> tuple[ChecklistInputs, dict[str, str]]:
    facts = latest_facts(db)
    names = owner_names(db)
    w_start, w_end = window(today)
    monthly, payoff = _mortgage(db, facts)
    flows = derive_flows(db, today, monthly, payoff, home_value.current_value(db))
    balances = networth._latest_per_account(db, today)
    types = dict(db.execute(select(Account.id, Account.type).where(Account.id.in_(balances.keys()))).all())
    cash = max(0, sum(c for aid, c in balances.items() if types[aid] in ac.CASH_TYPES))
    salary, pct = _int(facts, "jr.salary_cents"), _int(facts, "jr.k401_pct_bp")
    credit = [a.id for a in _active(db, AccountType.credit)]
    interest = None
    if credit:
        since = today - timedelta(days=90)
        recent = db.scalar(select(func.count()).select_from(Transaction)
                           .where(Transaction.account_id.in_(credit), Transaction.posted_at >= since))
        if recent:
            interest = db.scalar(select(func.count()).select_from(Transaction).where(
                Transaction.account_id.in_(credit), Transaction.posted_at >= since,
                Transaction.category == "interest", Transaction.amount_cents < 0))
    hsa = [a.id for a in _active(db, AccountType.hsa)]
    contributed = frozenset(names[a.owner] for a in _active(db, AccountType.roth_ira)
                            if a.owner in (Owner.jr, Owner.spouse) and (contributions(db, [a.id], w_start, w_end) or 0) > 0)
    ci = ChecklistInputs(
        spending_basis_cents=flows.spending_basis_cents,
        cash_cents=cash,
        k401_pct_bp=pct,
        match_cap_bp=_int(facts, "employer.match_cap_bp"),
        k401_contribution_cents=salary * pct // 10_000 if salary is not None and pct is not None else None,
        has_credit_accounts=bool(credit),
        interest_charges_3mo=interest,
        has_hsa=bool(hsa),
        hsa_contributions_12mo_cents=contributions(db, hsa, w_start, w_end),
        owners=(names["jr"], names["spouse"]),
        roth_contributed_owners=contributed,
        taxable_contributions_12mo_cents=contributions(db, [a.id for a in _active(db, AccountType.brokerage_taxable)], w_start, w_end),
    )
    return ci, names
