import base64
from contextlib import nullcontext
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from steward.api.body import bad
from steward.business.tagging import TagError, set_business
from steward.db.models import (CATEGORIES, Account, CategorySource, MerchantRule, Reimburser, SetAside, SetAsideMatch, Transaction,
                               TransactionNote)
from steward.api.accounts import OWNER_RULE
from steward.books.people import names_of
from steward.deps import BookContext, book_db, now, open_book, recorded, today
from steward.events import log_event
from steward.inventory.changes import about, changed, record
from steward.inventory.suggestions import refresh
from steward.services.came_from import came_from as came_from_of
from steward.services.category_rules import CATEGORY_CHANGED, RULE_GONE, matching_counts, spread
from steward.services import reimburse as rb
from steward.services import reimburse_rules as rr
from steward.services.review import forget_duplicate_keeps
from steward.services.transactions import apply_correction, normalize, rules_for
from steward.services.undo import capturing
from steward.services.transfers import unpair_peers

router = APIRouter(dependencies=[Depends(open_book)])


class TxnPatch(BaseModel):
    merchant: str | None = Field(default=None, max_length=200)
    category: str | None = None
    is_business: bool | None = None
    apply_to_matching: bool = False
    reimbursable: bool | None = None           # reimbursable spec, Marking: the switch
    reimburser_id: int | None = None           # who, when there are two or more payers


def transaction_row(t: Transaction, account_name: str, set_aside: dict | None = None, note_count: int = 0) -> dict:
    return {"id": t.id, "account_id": t.account_id, "account_name": account_name,
            "posted_at": t.posted_at.isoformat(), "amount_cents": t.amount_cents,
            "raw_description": t.raw_description, "merchant": t.merchant, "nickname": t.nickname, "category": t.category,
            "is_business": t.is_business, "is_transfer": t.is_transfer,
            "business_pct": t.business_pct, "business_line": t.business_line, "business_source": t.business_source,
            "category_source": t.category_source.value, "from_bank": t.external_id is not None,
            "reviewed_at": t.reviewed_at.isoformat() if t.reviewed_at else None, "set_aside": set_aside,
            "note_count": note_count,
            "reimburser_id": t.reimburser_id, "trip_id": t.trip_id}


_row = transaction_row


def with_reimburse(row: dict, t: Transaction, patterns: set[str] | None) -> dict:
    """A household row says whether the Reimbursable switch is offered (spec, Marking; R2). None: not a household book."""
    if patterns is not None:
        row["reimburse_ok"] = rb.can_reimburse(t, patterns)
    return row


def note_counts(db: Session, ids: list[int]) -> dict[int, int]:
    """Phase 12: how many notes each of these rows carries, for the note mark in lists."""
    if not ids:
        return {}
    q = (select(TransactionNote.transaction_id, func.count()).where(TransactionNote.transaction_id.in_(ids))
         .group_by(TransactionNote.transaction_id))
    return dict(db.execute(q).all())


def set_asides_of(db: Session, ids: list[int]) -> dict[int, dict]:
    """Phase 11c: the set-aside each of these payments is matched to, {id, name, how}, for the rows that have one."""
    if not ids:
        return {}
    q = (select(SetAsideMatch.transaction_id, SetAside.id, SetAside.name, SetAsideMatch.how, SetAside.archived_at)
         .join(SetAside, SetAside.id == SetAsideMatch.set_aside_id)
         .where(SetAsideMatch.transaction_id.in_(ids), SetAsideMatch.how.in_(("auto", "hand"))))
    return {tid: {"id": sid, "name": name, "how": how, "archived": archived is not None}
            for tid, sid, name, how, archived in db.execute(q)}


def _enc(d: date, i: int) -> str:
    return base64.urlsafe_b64encode(f"{d.isoformat()}|{i}".encode()).decode()


def _dec(c: str) -> tuple[date, int]:
    try:
        d, i = base64.urlsafe_b64decode(c.encode()).decode().split("|")
        return date.fromisoformat(d), int(i)
    except (ValueError, OverflowError):
        raise HTTPException(422, detail={"error": "That page marker isn't valid."}) from None


@router.get("/transactions")
def list_transactions(q: str | None = None, account_id: int | None = None, category: str | None = None,
                      owner: str | None = None, business: bool | None = None, sorted: str | None = None,
                      batch: int | None = None, from_: date | None = Query(None, alias="from"), to: date | None = None,
                      limit: int = Query(50, ge=1, le=500), cursor: str | None = None,
                      db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    if owner is not None and owner not in {o.key for o in ctx.book.owner_names}:
        raise HTTPException(422, detail={"error": OWNER_RULE})
    stmt = select(Transaction, Account.name).join(Account, Account.id == Transaction.account_id)
    if q:
        # Phase 12 decision 18 and polish round P5: the web's search only; no advisor tool reaches this route, reads notes or names.
        noted = select(TransactionNote.transaction_id).where(TransactionNote.body.icontains(q, autoescape=True))
        stmt = stmt.where(or_(Transaction.merchant.icontains(q, autoescape=True),
                              Transaction.raw_description.icontains(q, autoescape=True),
                              Transaction.nickname.icontains(q, autoescape=True),
                              Transaction.id.in_(noted)))
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if category:
        stmt = stmt.where(Transaction.category == category)
    if owner:
        stmt = stmt.where(Account.owner == owner)
    if business is not None:
        stmt = stmt.where(Transaction.is_business == business)
    if sorted is not None:
        if sorted == "steward":            # decision 5: rows the model sorted that nobody checked
            stmt = stmt.where(Transaction.category_source == CategorySource.model, Transaction.reviewed_at.is_(None))
        elif sorted == "unsure":           # the model's guess is still on the row
            stmt = stmt.where(Transaction.guess_category.is_not(None), Transaction.category == "uncategorized")
        else:
            raise HTTPException(422, detail={"error": "That filter isn't one Steward knows."})
    if batch is not None:
        stmt = stmt.where(Transaction.import_batch_id == batch)
    if from_:
        stmt = stmt.where(Transaction.posted_at >= from_)
    if to:
        stmt = stmt.where(Transaction.posted_at <= to)
    if cursor:
        cd, ci = _dec(cursor)
        stmt = stmt.where(or_(Transaction.posted_at < cd, and_(Transaction.posted_at == cd, Transaction.id < ci)))
    stmt = stmt.order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(limit + 1)
    rows = db.execute(stmt).all()
    page = rows[:limit]
    nxt = _enc(page[-1][0].posted_at, page[-1][0].id) if len(rows) > limit else None
    found = set_asides_of(db, [t.id for t, _ in page])
    notes = note_counts(db, [t.id for t, _ in page])
    pats = rb.refundable_patterns(db) if ctx.book.kind == "household" else None
    return {"transactions": [with_reimburse(_row(t, n, found.get(t.id), notes.get(t.id, 0)), t, pats) for t, n in page],
            "next_cursor": nxt}


@router.get("/transactions/{tid}/matching")
def transaction_matching(tid: int, db: Session = Depends(book_db)):
    """Sorting redesign, The transaction detail: how many other rows "Also apply to N matching transactions" reaches."""
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    return {"count": matching_counts(db, [t])[t.id] or 0}


@router.get("/transactions/{tid}/came-from")
def transaction_came_from(tid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Came from (JR, Oct 31): one quiet line for the detail, loaded when it opens (plan Engineering choice 2)."""
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    return {"came_from": came_from_of(db, t, names_of(ctx.people, mid=True), ctx.is_manager)}


def _fields(t: Transaction) -> dict:
    return {"category": t.category, "merchant": t.merchant, "is_business": t.is_business}


HOUSEHOLD_BUSINESS = "Business or personal is for household books."


def _rule_now(db: Session, t: Transaction) -> tuple[str | None, str] | None:
    """The rule apply_correction will change for this row (the amount rule, else the plain one), before the sort."""
    pattern = normalize(t.raw_description)
    if not pattern:
        return None
    amount, plain = rules_for(db, pattern, t.amount_cents)
    r = amount or plain
    return (r.category, r.merchant) if r is not None else None


def _rule_word(had: tuple[str, str] | None, rule: MerchantRule | None) -> str:
    if rule is None:
        return "none"
    if had is None:
        return "made"
    return "kept" if had == (rule.category, rule.merchant) else "changed"


def _reimburse_facts(db: Session, t: Transaction, was_payer: int | None, reimbursable: bool | None,
                     before: dict[int, int]) -> dict | None:
    """result.reimburse (engineering choice 10): what the sort or the switch did to a payer's balance."""
    if t.category == rb.REPAYMENT and t.reimburser_id is not None:
        change, pid = "repaid", t.reimburser_id
    elif reimbursable is True and t.reimburser_id is not None:
        change, pid = "marked", t.reimburser_id
    elif reimbursable is False and was_payer is not None:
        change, pid = "unmarked", was_payer
    else:
        return None
    return {"change": change, "reimburser_id": pid, "payer": db.get(Reimburser, pid).name,
            "was_cents": before.get(pid, 0), "owed_cents": rb.owed_map(db).get(pid, 0)}


@router.patch("/transactions/{tid}")
@recorded
def patch_transaction(tid: int, body: TxnPatch, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    if body.category is not None and body.category not in CATEGORIES:
        raise HTTPException(422, detail={"error": "That isn't one of the categories."})
    household = ctx.book.kind == "household"
    if body.is_business is not None and not household:
        raise bad(HOUSEHOLD_BUSINESS)
    repaying = body.category == rb.REPAYMENT
    if not household and (body.reimbursable is not None or body.reimburser_id is not None or repaying):
        raise bad(rb.HOUSEHOLD_ONLY)
    if body.reimbursable and body.is_business:
        raise bad(rb.EITHER)
    payer = None
    if body.reimbursable or repaying:
        try:
            payer = rb.payer_for(db, body.reimburser_id)
        except rb.ReimburseError as e:
            raise bad(str(e)) from None
    if body.reimbursable:
        if t.is_transfer or body.category == "transfer":
            raise bad(rb.NOT_FOR_TRANSFERS)
        if not rb.can_reimburse(t, rb.refundable_patterns(db), body.category):
            raise bad(rb.NOT_REIMBURSABLE)
    was = _fields(t)
    was_payer, was_category = t.reimburser_id, t.category
    owed_before = rb.owed_map(db) if household else {}
    at = now()
    sorting = body.category is not None
    acting = sorting or body.reimbursable is not None
    rule, had, spread_ids = None, None, []
    # Sorting redesign: the correction, the rule and the matching rows are one action in one transaction, with its
    # undo; the reimbursable spec's mark, Not reimbursed and a repayment's payer ride the same action.
    with capturing(db, ctx.user_id, "sort", at) if acting else nullcontext() as cap:
        if cap is not None:
            cap.target = t.id
        if body.merchant is not None or sorting:   # a tag alone is not a review (spec 5)
            had = _rule_now(db, t)
            rule = apply_correction(db, t, body.merchant, body.category, None, at)
        if body.is_business is not None:
            try:
                set_business(t, 100 if body.is_business else 0, source="manual")
            except TagError as e:
                db.rollback()
                raise bad(str(e)) from None
            if body.is_business and t.reimburser_id is not None:
                rb.unmark(t)                   # a charge is either business or reimbursable
        if household:
            rb.after_sort(t, was_category, payer, body.reimbursable)
            if t.category == rb.REPAYMENT and payer is not None:
                rr.remember_payer(db, t, payer, at)     # before the spread, so the matching deposits take this payer
        if sorting and body.apply_to_matching and rule is not None:
            spread_ids = spread(db, rule, at)
    applied = len(spread_ids)
    before, after = changed(was, _fields(t))
    if after:
        record(db, ctx, "txn.edit", target_id=t.id, before=before, after={**after, "about": about(t)})
    if applied:
        record(db, ctx, "txn.spread", target_id=t.id, after={"count": applied, "about": about(t)})
    db.commit()
    out = _row(t, db.get(Account, t.account_id).name, set_asides_of(db, [t.id]).get(t.id),
               note_counts(db, [t.id]).get(t.id, 0))
    if household:
        with_reimburse(out, t, rb.refundable_patterns(db))
    if acting:
        out["result"] = {"category": t.category, "applied": applied, "ids": spread_ids, "rule": _rule_word(had, rule), "undo": cap.token,
                         "reimburse": _reimburse_facts(db, t, was_payer, body.reimbursable, owed_before)
                         if household else None}
    return out


SORT_MAX = 200
TOO_MANY = "Sort up to 200 at a time."
NOTHING_CHOSEN = "Choose what to sort."
NOT_A_CATEGORY = "That isn't one of the categories."
ID_MAX = 2**63 - 1        # SQLite's largest integer


class SortMany(BaseModel):
    ids: list[StrictInt]
    category: str


@router.post("/transactions/sort")
@recorded
def sort_many(body: SortMany, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Profile spec, Sorting several rows at once: up to 200 rows take one category in one action, with one Undo. Each
    row is a person's correction as the PATCH makes it (reviewed, source correction, a transfer paired or unpaired), but
    no merchant or payer rule is made (P29), nothing spreads and nothing is tagged business. An unknown id refuses the
    whole request and changes nothing. A row that can't take the category is skipped with the reason."""
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise bad(NOTHING_CHOSEN)
    if len(ids) > SORT_MAX:
        raise bad(TOO_MANY)
    if body.category not in CATEGORIES or body.category == "uncategorized":
        raise bad(NOT_A_CATEGORY)
    household = ctx.book.kind == "household"
    repaying = body.category == rb.REPAYMENT
    if repaying and not household:
        raise bad(rb.HOUSEHOLD_ONLY)
    # An id SQLite can't hold (past 2**63 - 1, or below 1) names no row: the same 404, never an OverflowError.
    in_range = all(1 <= i <= ID_MAX for i in ids)
    found = {t.id: t for t in db.scalars(select(Transaction).where(Transaction.id.in_(ids)))} if in_range else {}
    if len(found) != len(ids):
        raise HTTPException(404, detail={"error": "No such transaction."})
    payer, why = None, None
    if repaying:
        try:
            payer = rb.payer_for(db)       # Steward never guesses between payers: none or two, and the rows wait
        except rb.ReimburseError as e:
            why = str(e)
    at = now()
    skipped = [{"id": i, "reason": why} for i in ids] if why else []
    done: list[int] = []
    token = None
    if not skipped:
        with capturing(db, ctx.user_id, "sort_many", at) as cap:
            for i in ids:
                t = found[i]
                was_category = t.category
                apply_correction(db, t, None, body.category, None, at, make_rule=False)
                if household:
                    rb.after_sort(t, was_category, payer, None)
                done.append(i)
        token = cap.token
        record(db, ctx, "txn.sort_many", after={"count": len(done), "category": body.category})
    db.commit()
    return {"sorted": len(done), "ids": done, "category": body.category, "skipped": skipped, "undo": token}


@router.post("/transactions/{tid}/spread")
@recorded
def spread_transaction(tid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Decision 1: apply the row's rule to the rows decision 12 names. 409 in plain words when the rule went or the
    row's category changed since the offer."""
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    pattern = normalize(t.raw_description)
    amount, plain = rules_for(db, pattern, t.amount_cents) if pattern else (None, None)
    rule = amount or plain
    if rule is None:
        raise HTTPException(409, detail={"error": RULE_GONE})
    if rule.category != t.category:
        raise HTTPException(409, detail={"error": CATEGORY_CHANGED})
    n = len(spread(db, rule, now()))
    record(db, ctx, "txn.spread", target_id=t.id, after={"count": n, "about": about(t)})
    db.commit()
    return {"changed": n}


@router.delete("/transactions/{tid}", status_code=204)
@recorded
def delete_transaction(tid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    if t.external_id is not None:
        raise HTTPException(409, detail={"error": "This came from the bank, so it can't be removed."})
    log_event(db, "info", "import", "Removed a transaction that came from a file")   # the confirmation promises it
    record(db, ctx, "txn.remove", target_id=tid, after={"about": about(t)})
    forget_duplicate_keeps(db, [tid])
    unpair_peers(db, [tid])
    db.delete(t)
    if ctx.book.kind == "parent":
        refresh(db, today())       # a suggestion that leaned on this transaction is re-read now, not at the next sync
    db.commit()
    return Response(status_code=204)
