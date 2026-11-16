"""Kids for college planning (profile spec, Kids and college): each kid's name, birth year, school, the share the
household plans to cover and whether that includes living costs, their 529 and its monthly amount. Removing a kid is
soft (P27); every write returns an Undo token (P26) and purges kids removed longer ago than the undo window."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object, one_of, text, whole
from steward.db.models import COLLEGE_COST_LEVELS, Account, AccountType, Child, active_children
from steward.deps import BookContext, book_db, household_only, open_book
from steward.engine import datafiles
from steward.engine.simulate import COLLEGE_START_AGE
from steward.services import children as kids
from steward.services.undo import capturing

router = APIRouter(prefix="/children", dependencies=[Depends(open_book), Depends(household_only)])

FIELDS = ("label", "birth_year", "cost_level", "account_id", "monthly_contribution_cents", "share_pct", "covers_living",
          "set_type")
NAME = "Enter the kid's name."
LEVEL = "Choose a school type."
SHARE = "Choose a share from 0% to 100%."
LIVING = "Say true or false for living costs."
ACCOUNT = "Choose one of your 529 accounts."
SET_TYPE = "That account can't be a 529 plan."
TAKEN = "That 529 already belongs to {name}."
NO_SUCH_CHILD = "No such child."
MONTHLY = "Enter a monthly amount that isn't negative."
MAX_MONTHLY_CENTS = 10_000_000   # $100,000 a month; anything above is a typo


def child_out(c: Child, plan: dict | None, plan_year: int) -> dict:
    return {"id": c.id, "label": c.label, "birth_year": c.birth_year, "cost_level": c.cost_level,
            "account_id": c.account_id, "monthly_contribution_cents": c.monthly_contribution_cents,
            "share_pct": c.share_pct, "covers_living": c.covers_living,
            "college_start_year": c.birth_year + COLLEGE_START_AGE,
            "outlook": kids.outlook_out(c, plan, plan_year),
            "plan529": None if plan is None else {"balance_cents": plan["balance_cents"],
                                                  "monthly_cents": c.monthly_contribution_cents,
                                                  "real_return": plan["real_return"]}}


def _one(db: Session, c: Child) -> dict:
    t = deps.today()
    plan = next((p for p in kids.plans_out(db, t) if p["account_id"] == c.account_id), None)
    return child_out(c, plan, t.year)


def _apply(db: Session, c: Child, body: dict[str, Any], creating: bool) -> None:
    unknown = sorted(set(body) - set(FIELDS))
    if unknown:
        raise bad(f"Unknown field: {unknown[0]}.")
    lo, hi = deps.today().year - 30, deps.today().year + 1          # hi admits a kid on the way
    year_msg = f"Enter a birth year between {lo} and {hi}."
    if creating:
        for key, message in (("label", NAME), ("birth_year", year_msg)):
            if key not in body:
                raise bad(message)
    if "label" in body:
        c.label = text(body["label"], NAME, 40)
    if "birth_year" in body:
        c.birth_year = whole(body["birth_year"], year_msg, lo, hi)
    if "cost_level" in body:
        c.cost_level = one_of(body["cost_level"], COLLEGE_COST_LEVELS, LEVEL)
    if "share_pct" in body:
        share = whole(body["share_pct"], SHARE, 0, 100)
        if share % 10:
            raise bad(SHARE)                  # the slider moves in tens; the engine itself takes any whole percent
        c.share_pct = share
    if "covers_living" in body:
        if not isinstance(body["covers_living"], bool):
            raise bad(LIVING)
        c.covers_living = body["covers_living"]
    if "monthly_contribution_cents" in body:
        c.monthly_contribution_cents = whole(body["monthly_contribution_cents"], MONTHLY, 0, MAX_MONTHLY_CENTS)
    set_type = body.get("set_type", False)
    if not isinstance(set_type, bool) or (set_type and body.get("account_id") is None):
        raise bad(ACCOUNT)
    if "account_id" in body:
        aid = body["account_id"]
        if aid is not None:
            aid = whole(aid, ACCOUNT, 1, 2**63 - 1)
            acct = db.get(Account, aid)
            if acct is None or not acct.is_active:
                raise bad(ACCOUNT)
            if set_type and acct.type in kids.NOT_A_529:
                raise bad(SET_TYPE)
            if not set_type and acct.type != AccountType.plan529:
                raise bad(ACCOUNT)
            holder = db.scalar(active_children().where(Child.account_id == aid, Child.id != (c.id or -1)))
            if holder is not None:
                raise bad(TAKEN.format(name=holder.label), 409)
            if set_type and acct.type != AccountType.plan529:
                kids.make_529(db, acct, deps.now())
        c.account_id = aid


def _find(db: Session, cid: str) -> Child:
    c = db.get(Child, int(cid)) if cid.isascii() and cid.isdigit() and len(cid) <= 18 else None
    if c is None or c.removed_at is not None:
        raise bad(NO_SUCH_CHILD, 404)
    return c


@router.get("")
def list_children(db: Session = Depends(book_db)):
    t = deps.today()
    plans = kids.plans_out(db, t)
    by_id = {p["account_id"]: p for p in plans}
    return {"children": [child_out(c, by_id.get(c.account_id), t.year) for c in db.scalars(active_children())],
            "college": datafiles.college_table(), "suggestions": kids.suggest(db), "plans": plans}


@router.post("", status_code=201)
def create_child(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    at = deps.now()
    kids.purge_removed(db, at)
    c = Child(cost_level="not_sure", monthly_contribution_cents=0, account_id=None, share_pct=100, covers_living=True)
    with capturing(db, ctx.user_id, "kid", at) as cap:
        _apply(db, c, body, creating=True)
        db.add(c)
    db.commit()
    return {**_one(db, c), "undo": cap.token}


@router.patch("/{cid}")
def patch_child(cid: str, body: dict = Depends(json_object), db: Session = Depends(book_db),
                ctx: BookContext = Depends(open_book)):
    at = deps.now()
    kids.purge_removed(db, at)
    c = _find(db, cid)
    with capturing(db, ctx.user_id, "kid", at) as cap:
        _apply(db, c, body, creating=False)
    db.commit()
    return {**_one(db, c), "undo": cap.token}


@router.delete("/{cid}")
def delete_child(cid: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P27: soft. The 529 is let go at once, so it can be linked again; Undo puts the link back if it is still free."""
    at = deps.now()
    kids.purge_removed(db, at)
    c = _find(db, cid)
    with capturing(db, ctx.user_id, "kid_remove", at) as cap:
        c.removed_at, c.account_id = at, None
    db.commit()
    return {"undo": cap.token}
