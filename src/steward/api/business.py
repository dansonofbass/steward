"""Business and personal (spec 5): household books only. Every route goes through open_book and household_only, so a
parent book answers 404 and a viewer gets 403 on anything that changes the book."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.api.transactions import transaction_row
from steward.business.lines import LINE_BY_KEY
from steward.business.report import business_report, line_rows, report_out
from steward.business.rules import RuleError, add_rule, remove_rule, rule_out
from steward.business.rules_table import business_rules
from steward.engine.inputs import InputError
from steward.business.scorp import NotReady, compare, comparison_out
from steward.business.settings import SettingsError, business_type, expect_for, miles_for, read_settings, update_settings
from steward.business.tagging import TagError, set_business
from steward.services.reimburse import unmark
from steward.db.models import Account, BusinessRule, Transaction
from steward.deps import BookContext, book_db, household_only, open_book
from steward.services.plan import engine_text
from steward.services.plan_inputs import latest_facts, owner_names, owner_users

router = APIRouter(prefix="/business", dependencies=[Depends(open_book), Depends(household_only)])
YEARS = "Choose this year or last year."
NOT_ON_RETURN = "Choose one of the adults on the return."


def adults(db: Session) -> list[dict]:
    """The household's adults who can run the business: Person 1, and Person 2 on a joint return or, before the
    filing status is known, when the book has a second person."""
    f = latest_facts(db)
    filing = f["filing_status"].value if "filing_status" in f else None
    names = owner_names(db)
    two = filing == "mfj" or (filing is None and owner_users(db)[1] is not None)
    return [{"key": k, "name": names[k]} for k in (("jr", "spouse") if two else ("jr",))]


def year_param(year: str | int | None) -> int:
    this = deps.today().year
    if year is None:
        return this
    text = str(year)
    if isinstance(year, bool) or not (text.isascii() and text.isdigit()) or int(text) not in (this, this - 1):
        raise bad(YEARS)
    return int(text)


def settings_out(db: Session, year: int) -> dict:
    s = read_settings(db, year)
    rules = business_rules(year)
    people = adults(db)
    owner = s.owner if any(a["key"] == s.owner for a in people) else "jr"
    miles = miles_for(db, year, len(rules.mileage))
    e = expect_for(db, year)
    return {"year": year, "this_year": deps.today().year, "type": s.type, "home_office": asdict(s.home_office), "car_method": s.car_method,
            "miles": [{"from": p.start.isoformat(), "to": p.end.isoformat(), "rate_tenths": p.tenths_of_cent,
                       "miles": m} for p, m in zip(rules.mileage, miles)],
            "expect": asdict(e) if e else None, "s_corp": asdict(s.s_corp), "owner": owner, "adults": people,
            "rules": {"year": rules.year, "using_note": rules.using_note,
                      "home_office_rate_cents": rules.home_office_rate_cents,
                      "home_office_max_sqft": rules.home_office_max_sqft, "meals_pct": rules.meals_pct}}


@router.get("/settings")
def get_settings(year: str | None = None, db: Session = Depends(book_db)):
    return settings_out(db, year_param(year))


@router.put("/settings")
def put_settings(body: dict = Depends(json_object), db: Session = Depends(book_db),
                 ctx: BookContext = Depends(open_book)):
    year = year_param(body.get("year"))
    if body.get("owner") in ("jr", "spouse") and not any(a["key"] == body["owner"] for a in adults(db)):
        raise bad(NOT_ON_RETURN)
    try:
        update_settings(db, body, year=year, this_year=deps.today().year,
                        periods=len(business_rules(year).mileage), user_id=ctx.user_id, at=deps.now())
    except SettingsError as e:
        raise bad(str(e)) from None
    db.commit()
    return settings_out(db, year)


NO_SUCH_TRANSACTION = "No such transaction."
PERCENT = "Choose a whole percent from 0 to 100."


def _txn_or_404(db: Session, tid: int) -> Transaction:
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": NO_SUCH_TRANSACTION})
    return t


@router.put("/transactions/{tid}")
def tag_transaction(tid: int, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    t = _txn_or_404(db, tid)
    if "pct" not in body:
        raise bad(PERCENT)
    kw = {"line": body["line"]} if "line" in body else {}
    try:
        set_business(t, body["pct"], source="manual", **kw)
    except TagError as e:
        db.rollback()
        raise bad(str(e)) from None
    if t.business_pct > 0 and t.reimburser_id is not None:
        unmark(t)                          # a charge is either business or reimbursable
    db.commit()
    return transaction_row(t, db.get(Account, t.account_id).name)


def _account_names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Account.id, Account.name)).all())


@router.get("/rules")
def list_rules(db: Session = Depends(book_db)):
    names = _account_names(db)
    return {"rules": [rule_out(r, names) for r in db.scalars(select(BusinessRule).order_by(BusinessRule.id))]}


def _id(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@router.post("/rules", status_code=201)
def make_rule(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    kind = body.get("kind")
    txn = account = None
    if kind in ("merchant", "client"):
        tid = _id(body.get("transaction_id"))
        txn = db.get(Transaction, tid) if tid is not None else None
        if txn is None:
            raise HTTPException(404, detail={"error": NO_SUCH_TRANSACTION})
    elif kind == "account":
        aid = _id(body.get("account_id"))
        account = db.get(Account, aid) if aid is not None else None
        if account is None:
            raise HTTPException(404, detail={"error": "No such account."})
    try:
        r, n = add_rule(db, kind=kind, pct=body.get("pct"), line=body.get("line"), user_id=ctx.user_id,
                        at=deps.now(), txn=txn, account=account)
    except RuleError as e:
        db.rollback()
        raise bad(str(e)) from None
    db.commit()
    return {"rule": rule_out(r, _account_names(db)), "also_tagged": n}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(book_db)):
    if not remove_rule(db, rule_id):
        raise HTTPException(404, detail={"error": "No such rule."})
    db.commit()
    return Response(status_code=204)


@router.post("/suggestions/{tid}")
def answer_suggestion(tid: int, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    t = _txn_or_404(db, tid)
    answer = body.get("answer")
    if answer not in ("business", "personal"):
        raise bad("Answer business or personal.")
    try:
        set_business(t, 100 if answer == "business" else 0, source="manual")
    except TagError as e:
        db.rollback()
        raise bad(str(e)) from None
    if t.business_pct > 0 and t.reimburser_id is not None:
        unmark(t)                          # a charge is either business or reimbursable
    t.business_answered_at = deps.now()
    db.commit()
    return transaction_row(t, db.get(Account, t.account_id).name)


@router.get("")
def get_report(year: str | None = None, db: Session = Depends(book_db)):
    return report_out(business_report(db, year_param(year), deps.today()), deps.today().year)


@router.get("/lines/{line}")
def get_line(line: str, year: str | None = None, db: Session = Depends(book_db)):
    found = LINE_BY_KEY.get(line)
    if found is None:
        raise HTTPException(404, detail={"error": "No such line."})
    rows = line_rows(db, year_param(year), line, deps.today())
    return {"line": {"key": found.key, "number": found.number, "label": found.label},
            "transactions": [{**transaction_row(t, n), "share_cents": s} for t, n, s in rows]}


@router.get("/s-corp")
def get_s_corp(year: str | None = None, db: Session = Depends(book_db)):
    if business_type(db) not in ("sole_prop", "s_corp"):
        return {"available": False, "reason": "Choose sole proprietor or S-corp in Settings, Business."}
    try:
        return comparison_out(compare(db, year_param(year), deps.today()))
    except (NotReady, InputError) as e:
        return {"available": False, "reason": engine_text(db, e)}
