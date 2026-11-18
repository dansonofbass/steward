from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictInt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward import deps
from steward.business.tagging import is_business_account, retag_account
from steward.db.models import ADVISORY_FEE_MAX_BP, INVESTMENT_TYPES, LIABILITY_TYPES, Account, AccountType, Institution, Source
from steward.deps import NOT_IN_THIS_BOOK, BookContext, book_db, not_recorded, now, open_book, today
from steward.events import resolve_events_matching
from steward.services import accounts as svc
from steward.services import home_value
from steward.services.categorize import sort_investment_rows
from steward.services.transfers import account_type_changed
from steward.services.undo import capturing

router = APIRouter(dependencies=[Depends(open_book)])


class AccountIn(BaseModel):
    name: str
    type: AccountType
    owner: str
    balance_cents: int
    as_of: date | None = None
    loan_id: StrictInt | None = None     # a vehicle's loan, for display (investment views spec)


class AccountPatch(BaseModel):
    name: str | None = None
    type: AccountType | None = None
    owner: str | None = None
    is_active: bool | None = None
    rate_bp: StrictInt | None = None     # a card's or loan's yearly rate in basis points; null clears it
    advisory_fee_bp: StrictInt | None = None   # an investment account's adviser fee in basis points; null clears it
    loan_id: StrictInt | None = None           # a vehicle's loan; null clears it


RATE_TYPES = "Only a card or a loan has an interest rate here."
RATE_RANGE = "Enter a rate between 0% and 100%."
ADVISORY_TYPES = "Only an investment account has an advisory fee here."
ADVISORY_RANGE = "Enter a fee between 0% and 3%."
VEHICLE_BY_HAND = "A vehicle is entered by hand, so a bank's account can't be one."
VEHICLE_VALUE = "Enter what it's worth, as a positive number."
LOAN_ONLY = "Only a vehicle or a home has a loan against it here."
CHOOSE_LOAN = "Choose one of your loan accounts."
CHOOSE_MORTGAGE = "Choose one of your mortgage accounts."
MORTGAGE_TAKEN = "That mortgage is on another home already."
# A vehicle's loan, and a home's mortgage (profile spec P20).
LOAN_TYPES = {AccountType.vehicle: (AccountType.loan, CHOOSE_LOAN), AccountType.property: (AccountType.mortgage, CHOOSE_MORTGAGE)}


class BalanceIn(BaseModel):
    balance_cents: int
    as_of: date | None = None


OWNER_RULE = "Choose one of this book's owners."
ACCOUNTS_IN_ITEMS = "Parent books make and change accounts through their inventory items (ruling 16)."


def household_accounts(ctx: BookContext = Depends(open_book)) -> None:
    """In a parent book an account is made and changed through its inventory item (design pass decision 2)."""
    if ctx.book.kind == "parent":
        raise HTTPException(404, detail={"error": NOT_IN_THIS_BOOK})


def _check_owner(ctx: BookContext, owner: str | None) -> None:
    if owner is not None and owner not in {o.key for o in ctx.book.owner_names}:
        raise HTTPException(422, detail={"error": OWNER_RULE})


def _check_liability_sign(type_: AccountType, balance_cents: int) -> None:
    if type_ in LIABILITY_TYPES and balance_cents > 0:
        raise HTTPException(422, detail={"error": "Enter what you owe as a negative number."})


def _check_vehicle_value(type_: AccountType, balance_cents: int) -> None:
    if type_ == AccountType.vehicle and balance_cents < 0:
        raise HTTPException(422, detail={"error": VEHICLE_VALUE})


def _check_loan(db: Session, type_: AccountType, loan_id: int | None, account_id: int | None = None) -> None:
    if loan_id is None:
        return
    if type_ not in LOAN_TYPES:
        raise HTTPException(422, detail={"error": LOAN_ONLY})
    want, message = LOAN_TYPES[type_]
    loan = db.get(Account, loan_id)
    if loan is None or loan.type != want:
        raise HTTPException(422, detail={"error": message})
    if want == AccountType.mortgage and db.scalar(select(Account.id).where(
            Account.type == AccountType.property, Account.loan_id == loan_id, Account.id != (account_id or -1))) is not None:
        raise HTTPException(409, detail={"error": MORTGAGE_TAKEN})


@router.get("/accounts")
def list_accounts(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    rows = db.scalars(select(Account).order_by(Account.type, Account.name))
    t, labels = today(), ctx.owner_labels()
    return {"accounts": [svc.account_out(db, a, t, labels) for a in rows]}


@router.post("/accounts", status_code=201, dependencies=[Depends(household_accounts)])
@not_recorded(ACCOUNTS_IN_ITEMS)
def create_account(body: AccountIn, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    _check_owner(ctx, body.owner)
    _check_liability_sign(body.type, body.balance_cents)
    _check_vehicle_value(body.type, body.balance_cents)
    _check_loan(db, body.type, body.loan_id)
    t = today()
    with capturing(db, ctx.user_id, "account", deps.now()) as cap:
        inst = svc.manual_institution(db)
        a = Account(institution_id=inst.id, name=body.name, type=body.type, owner=body.owner, source=Source.manual,
                    loan_id=body.loan_id)
        db.add(a)
        db.flush()
        svc.record_balance(db, a.id, body.as_of or t, body.balance_cents)
    db.commit()
    return {**svc.account_out(db, a, t, ctx.owner_labels()), "undo": cap.token}


@router.patch("/accounts/{aid}", dependencies=[Depends(household_accounts)])
@not_recorded(ACCOUNTS_IN_ITEMS)
def patch_account(aid: int, body: AccountPatch, db: Session = Depends(book_db),
                  ctx: BookContext = Depends(open_book)):
    _check_owner(ctx, body.owner)
    a = db.get(Account, aid)
    if a is None:
        raise HTTPException(404, detail={"error": "No such account."})
    if body.type == AccountType.vehicle and a.source != Source.manual:
        raise HTTPException(422, detail={"error": VEHICLE_BY_HAND})
    household = ctx.book.kind == "household"
    was_unknown, old_name, was_business, was_type = a.type == AccountType.unknown, a.name, is_business_account(a, household), a.type
    changes = body.model_dump(exclude_none=True)
    for k in ("rate_bp", "advisory_fee_bp", "loan_id"):
        changes.pop(k, None)
    if "rate_bp" in body.model_fields_set and body.rate_bp is not None:
        if not 0 <= body.rate_bp <= 10_000:
            raise HTTPException(422, detail={"error": RATE_RANGE})
        if (body.type or a.type) not in LIABILITY_TYPES:
            raise HTTPException(422, detail={"error": RATE_TYPES})
    if "advisory_fee_bp" in body.model_fields_set and body.advisory_fee_bp is not None:
        if not 0 <= body.advisory_fee_bp <= ADVISORY_FEE_MAX_BP:
            raise HTTPException(422, detail={"error": ADVISORY_RANGE})
        if (body.type or a.type) not in INVESTMENT_TYPES:
            raise HTTPException(422, detail={"error": ADVISORY_TYPES})
    if "loan_id" in body.model_fields_set:
        _check_loan(db, body.type or a.type, body.loan_id, a.id)
    with capturing(db, ctx.user_id, "account", deps.now()) as cap:
        if "rate_bp" in body.model_fields_set:
            a.rate_bp = body.rate_bp
        if "advisory_fee_bp" in body.model_fields_set:
            a.advisory_fee_bp = body.advisory_fee_bp
        if "loan_id" in body.model_fields_set:
            a.loan_id = body.loan_id
        for k, v in changes.items():
            setattr(a, k, v)
        if a.loan_id is not None:
            loan = db.get(Account, a.loan_id)
            if a.type not in LOAN_TYPES or loan is None or loan.type != LOAN_TYPES[a.type][0]:
                a.loan_id = None                 # the account's new type takes no such loan
        if is_business_account(a, household) != was_business:
            retag_account(db, a, household)
        account_type_changed(db, a, was_type)   # payments into a loan are Loan payments; into anything else, transfers
        if a.type != was_type:
            sort_investment_rows(db, a)          # an investment account's trades and fees leave Review (roadmap 12)
        if was_unknown and a.type != AccountType.unknown:
            resolve_events_matching(db, "system", f"New account '{old_name}' from ", now())
    db.commit()
    return {**svc.account_out(db, a, today(), ctx.owner_labels()), "undo": cap.token}


@router.post("/accounts/{aid}/balance", dependencies=[Depends(household_accounts)])
@not_recorded(ACCOUNTS_IN_ITEMS)
def set_balance(aid: int, body: BalanceIn, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    a = db.get(Account, aid)
    if a is None:
        raise HTTPException(404, detail={"error": "No such account."})
    if a.source != Source.manual:
        raise HTTPException(409, detail={"error": "This account updates itself from the bank."})
    _check_liability_sign(a.type, body.balance_cents)
    _check_vehicle_value(a.type, body.balance_cents)
    as_of = body.as_of or today()
    with capturing(db, ctx.user_id, "balance", deps.now()) as cap:
        svc.record_balance(db, aid, as_of, body.balance_cents)
        home_value.balance_saved(db, aid, body.balance_cents, as_of)   # the Home account's balance is Profile's home value
    db.commit()
    return {**svc.account_out(db, a, today(), ctx.owner_labels()), "undo": cap.token}


@router.get("/institutions")
def list_institutions(db: Session = Depends(book_db)):
    counts = dict(db.execute(select(Account.institution_id, func.count()).group_by(Account.institution_id)).all())
    rows = db.scalars(select(Institution).order_by(Institution.name))
    return {"institutions": [{
        "id": i.id, "name": i.name, "source": i.source.value,
        "last_sync_at": i.last_sync_at.isoformat() if i.last_sync_at else None,
        "last_error": i.last_error, "account_count": counts.get(i.id, 0)} for i in rows]}
