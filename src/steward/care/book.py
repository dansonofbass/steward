"""What Care projects from (spec 4.1, 3.4): the book's balances, income, spending, long-term care policies and home,
gathered once per request into a CareBook the scenarios share. Amounts are cents in today's dollars.

Ruling 11: checking, savings and CDs are cash; brokerage is taxable; an IRA or annuity is traditional (Roth when the
account's type is Roth IRA); card balances come off cash, then taxable, then traditional money, never below zero; loans
are left out (their payments are already in spending); the largest property is the home and others are left out.
Ruling 12: Social Security keeps pace with prices; pensions, annuities and other income stay fixed in dollars; an RMD
income item is left out because the engine works out RMDs from the IRA. Ruling 17: a long-term care policy needs a
benefit and a total or benefit years; without a waiting period, 90 days is assumed."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.care.store import Setup
from steward.db.models import Account, AccountType, InventoryItem, Transaction
from steward.engine.project import Income
from steward.inventory import kinds as K
from steward.inventory.present import parent_name
from steward.services.accounts import latest_balance
from steward.services.vault_flows import counted_start, months_between, personal_amount, personal_clauses, window

DEFAULT_WAITING_DAYS = 90
INCOME_KIND = {"social_security": "social_security", "pension": "pension", "annuity": "pension", "other": "pension"}
NO_BENEFIT = "A long-term care policy has no benefit amount yet, so the projection leaves it out."
NO_POOL = "A long-term care policy needs its total benefit or benefit years before the projection can use it."
NO_WAIT = "A long-term care policy has no waiting period entered, so 90 days is assumed."
NOT_THEIRS = "A long-term care policy ({name}) isn't counted: it covers {covers}."
LOANS = "Loan balances aren't subtracted; their payments are already in spending."
DEBT_LEFT = "Card balances are more than the savings; the rest isn't counted."


@dataclass(frozen=True)
class PolicyTerms:
    item_id: int
    benefit_daily_cents: int | None
    benefit_monthly_cents: int | None
    waiting_days: int
    total_benefit_cents: int | None
    benefit_years: int | None
    benefit_growth: float              # the inflation protection, a year
    premium_yearly_cents: int = 0      # 0 when none is entered or an income pays it (it was never in spending)


@dataclass(frozen=True)
class Balances:
    cash_cents: int
    taxable_cents: int
    traditional_cents: int
    roth_cents: int
    home_value_cents: int | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class CareBook:
    this_year: int
    person_label: str                  # the first word of the owner's label: "Margaret"
    birth_year: int
    spouse_birth_year: int | None
    state: str
    care_inflation: float
    cash_cents: int
    taxable_cents: int
    traditional_cents: int
    roth_cents: int
    home_value_cents: int | None
    incomes: tuple[Income, ...]
    spending_yearly_cents: int
    spending_months: int               # months of transactions behind it; 0 when typed in or when there are none
    spending_typed: bool
    policies: tuple[PolicyTerms, ...]
    notes: tuple[str, ...]             # what was left out or assumed, in plain words

    @property
    def age(self) -> int:
        return self.this_year - self.birth_year


def _open_items(db: Session, kind: str) -> list[InventoryItem]:
    return list(db.scalars(select(InventoryItem).where(InventoryItem.kind == kind, InventoryItem.status != "closed")
                           .order_by(InventoryItem.id)))


def _details(item: InventoryItem) -> dict:
    return json.loads(item.details or "{}")


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def balances(db: Session) -> Balances:
    cash = taxable = trad = roth = owed = 0
    homes: list[int] = []
    loans = missing = 0
    for item in _open_items(db, "account"):
        if item.account_id is None:
            continue
        t = _details(item).get("type")
        if t == "loan":
            loans += 1
            continue
        lb = latest_balance(db, item.account_id)
        if lb is None:
            missing += 1
            continue
        cents = lb[1]
        if t in K.FLOOR_TYPES:
            cash += cents
        elif t == "brokerage":
            taxable += cents
        elif t in ("ira", "annuity"):
            if db.get(Account, item.account_id).type == AccountType.roth_ira:
                roth += cents
            else:
                trad += cents
        elif t == "property":
            homes.append(cents)
        elif t == "credit_card":
            owed += max(-cents, 0)
    pots = [max(cash, 0), max(taxable, 0), max(trad, 0)]
    for i in range(3):          # Review Focus 4: card debt comes off each in turn, never below zero
        take = min(pots[i], owed)
        pots[i] -= take
        owed -= take
    notes = []
    if len(homes) > 1:
        notes.append(_count(len(homes) - 1, "1 other property isn't in the projection.",
                            "{n} other properties aren't in the projection."))
    if loans:
        notes.append(LOANS)
    if missing:
        notes.append(_count(missing, "1 account has no balance yet and isn't counted.",
                            "{n} accounts have no balance yet and aren't counted."))
    if owed:
        notes.append(DEBT_LEFT)
    return Balances(pots[0], pots[1], pots[2], max(roth, 0), max(homes) if homes else None, tuple(notes))


def incomes(db: Session, this_year: int) -> tuple[Income, ...]:
    out = []
    for item in _open_items(db, "income"):
        d = _details(item)
        src, amount, freq = d.get("source"), d.get("amount_cents"), d.get("frequency")
        if src not in INCOME_KIND or not amount or freq not in K.FREQUENCIES:
            continue
        out.append(Income(label=K.type_label("income", src) or "Income", amount_cents=amount * 12 // K.FREQUENCIES[freq],
                          start_year=this_year, growth="prices" if src == "social_security" else "fixed_dollars",
                          kind=INCOME_KIND[src]))
    return tuple(out)


def spending_from_history(db: Session, today: date) -> tuple[int, int]:
    """Yearly money out over the complete months of history (up to 12), with the months behind it. Taxes are left out
    (the engine works out tax); so are transfers, whether paired (personal_clauses) or only categorized as one (a card
    payment the feed didn't pair would otherwise count the card's purchases twice), and business shares."""
    start = counted_start(db, today)
    if start is None:
        return 0, 0
    end = window(today)[1]
    months = months_between(start, end)
    pa = personal_amount()
    out = db.scalar(select(func.coalesce(func.sum(-pa), 0)).join(Account, Account.id == Transaction.account_id)
                    .where(Transaction.posted_at >= start, Transaction.posted_at < end, Transaction.amount_cents < 0,
                           Transaction.category.not_in(("taxes", "transfer")), *personal_clauses()))
    return (int(out) * 24 + months) // (2 * months), months


def _premium(db: Session, d: dict) -> int:
    """The policy's yearly premium, which spending already holds; 0 when an income item pays it (final review M5)."""
    amount, freq = d.get("amount_cents"), d.get("frequency")
    if not amount or freq not in K.FREQUENCIES:
        return 0
    payer = db.get(InventoryItem, d["paid_from_id"]) if d.get("paid_from_id") else None
    return 0 if payer is not None and payer.kind == "income" else amount * 12 // K.FREQUENCIES[freq]


def policies(db: Session, person: str, owners: dict[str, str]) -> tuple[tuple[PolicyTerms, ...], tuple[str, ...]]:
    """The long-term care policies that pay toward `person`'s care: only that person's own (final review I1). Another
    person's policy, or one owned jointly, is named in a note and left out."""
    terms, notes = [], []
    first = parent_name([owners.get(person, "")])
    for item in _open_items(db, "insurance"):
        d = _details(item)
        if d.get("type") != "long_term_care":
            continue
        if item.owner != person:
            covers = ("both, and only " + first + "'s own policies count" if item.owner == "joint"
                      else parent_name([owners.get(item.owner, "")]))
            notes.append(NOT_THEIRS.format(name=item.name, covers=covers))
            continue
        if not d.get("benefit_cents"):
            notes.append(NO_BENEFIT)
            continue
        if d.get("pool_cents") is None and d.get("benefit_years") is None:
            notes.append(NO_POOL)
            continue
        waiting = d.get("waiting_days")
        if waiting is None:
            notes.append(NO_WAIT)
            waiting = DEFAULT_WAITING_DAYS
        per_day = (d.get("benefit_per") or "day") == "day"
        terms.append(PolicyTerms(item.id, d["benefit_cents"] if per_day else None,
                                 None if per_day else d["benefit_cents"], int(waiting), d.get("pool_cents"),
                                 d.get("benefit_years"), (d.get("rider_bp") or 0) / 10_000, _premium(db, d)))
    return tuple(terms), tuple(notes)


def load_book(db: Session, setup: Setup, owners: dict[str, str], today: date) -> CareBook:
    b = balances(db)
    terms, policy_notes = policies(db, setup.person, owners)
    if setup.spending_monthly_cents is not None:
        yearly, months, typed = 12 * setup.spending_monthly_cents, 0, True
    else:
        (yearly, months), typed = spending_from_history(db, today), False
    return CareBook(this_year=today.year, person_label=parent_name([owners.get(setup.person, "")]),
                    birth_year=setup.birth_year, spouse_birth_year=setup.spouse_birth_year, state=setup.state,
                    care_inflation=setup.care_inflation, cash_cents=b.cash_cents, taxable_cents=b.taxable_cents,
                    traditional_cents=b.traditional_cents, roth_cents=b.roth_cents, home_value_cents=b.home_value_cents,
                    incomes=incomes(db, today.year), spending_yearly_cents=yearly, spending_months=months,
                    spending_typed=typed, policies=terms, notes=b.notes + policy_notes)
