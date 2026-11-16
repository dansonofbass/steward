"""Home and cars in Profile (profile spec, Home and cars; P19-P23): whether the household owns a home, which home is
where you live (the Plan's and Care's), each property with its mortgage, each car with its loan, and the loans and
mortgages no property or car links yet. Where you live's mortgage carries the Plan's payment and payoff date and the
payment read from its transfer; another property's mortgage carries only its rate (its payments stay in spending)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, Source
from steward.services import home_value, mortgage_payment
from steward.services.accounts import debt_rate_bp, latest_balance
from steward.services.plan_inputs import latest_facts
from steward.services.profile import owns_home


def _active(db: Session, type_: AccountType) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.is_active.is_(True), Account.type == type_).order_by(Account.id)))


def _balance(db: Session, a: Account) -> tuple[int | None, str | None]:
    lb = latest_balance(db, a.id)
    return (lb[1], lb[0].isoformat()) if lb else (None, None)


def _loan(db: Session, a: Account, facts, today: date, main: bool) -> dict:
    owed, as_of = _balance(db, a)
    out = {"account_id": a.id, "name": a.name, "balance_cents": abs(owed) if owed is not None else None, "as_of": as_of,
           "manual": a.source == Source.manual, "institution": a.institution.name,
           "rate_bp": a.rate_bp if not main else debt_rate_bp(a, facts)}
    if a.type == AccountType.mortgage:
        payment, payoff = facts.get("mortgage.payment_cents"), facts.get("mortgage.payoff_date")
        out |= {"payment_cents": int(payment.value) if main and payment else None,
                "payoff_date": payoff.value if main and payoff else None,
                "detected": mortgage_payment.detected(db, a.id, today) if main else None}
    return out


def _thing(db: Session, a: Account) -> dict:
    value, as_of = _balance(db, a)
    return {"account_id": a.id, "name": a.name, "value_cents": value, "as_of": as_of}


def where_you_live(db: Session, properties: list[Account]) -> Account | None:
    home = home_value.linked_account(db)
    if home is not None and home.is_active:
        return home
    return properties[0] if len(properties) == 1 else None


def home_out(db: Session, today: date) -> dict:
    facts = latest_facts(db)
    props = _active(db, AccountType.property)
    where = where_you_live(db, props)
    main = home_value.main_mortgage(db)
    shown: set[int] = set()
    properties = []
    for p in sorted(props, key=lambda a: (a is not where, a.id)):     # where you live first
        m = main if p is where else (db.get(Account, p.loan_id) if p.loan_id else None)
        if m is not None and (not m.is_active or m.type != AccountType.mortgage):
            m = None
        if m is not None:
            shown.add(m.id)
        properties.append({**_thing(db, p), "mortgage": _loan(db, m, facts, today, p is where) if m else None})
    cars = []
    for c in _active(db, AccountType.vehicle):
        loan = db.get(Account, c.loan_id) if c.loan_id else None
        loan = loan if loan is not None and loan.is_active and loan.type == AccountType.loan else None
        if loan is not None:
            shown.add(loan.id)
        cars.append({**_thing(db, c), "loan": _loan(db, loan, facts, today, False) if loan else None})
    return {
        "owns_home": owns_home(db, facts),
        "where_you_live": where.id if where else None,
        "properties": properties,
        "cars": cars,
        "loans": [_loan(db, a, facts, today, False) for a in _active(db, AccountType.loan) if a.id not in shown],
        "mortgages": [_loan(db, a, facts, today, False) for a in _active(db, AccountType.mortgage) if a.id not in shown],
    }
