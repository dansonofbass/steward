"""Reimbursable expenses (reimbursable spec): the payers, the rules, the trips, the Reimbursements tab and Settle.
Household books only: every route goes through open_book and household_only, so a parent book answers 404 and a viewer
gets 403 on anything that changes the book."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward import clock, deps
from steward.api.body import NOT_UNDERSTOOD, bad, json_object
from steward.api.transactions import transaction_row
from steward.db.models import Account, ReimburseSettlement, Reimburser, Transaction, Trip
from steward.deps import BookContext, book_db, household_only, open_book
from steward.services import reimburse as rb
from steward.services import reimburse_rules as rr
from steward.services import trips
from steward.services.spending import SPENDING_CATEGORIES
from steward.services.undo import capturing

router = APIRouter(prefix="/reimburse", dependencies=[Depends(open_book), Depends(household_only)])


def payer_out(p: Reimburser) -> dict:
    return {"id": p.id, "name": p.name}


def _payer_or_404(db: Session, pid: int) -> Reimburser:
    p = db.get(Reimburser, pid)
    if p is None:
        raise HTTPException(404, detail={"error": rb.NO_SUCH_PAYER})
    return p


SINGLES = 100


def _balance(o: rb.Owed) -> dict:
    return {"owed_cents": o.owed_cents, "marked_cents": o.marked_cents, "repaid_cents": o.repaid_cents,
            "refunds_cents": o.refunds_cents, "settled_cents": o.settled_cents, "cleared_cents": o.cleared_cents,
            "since": o.since.isoformat() if o.since else None,
            "last_repaid_on": o.last_repaid_on.isoformat() if o.last_repaid_on else None}


def _trip_sums(db: Session) -> dict[int, tuple[int, int]]:
    """Each trip's charges: (rows, what they add to the balance)."""
    rows = db.execute(select(Transaction.trip_id, func.count(), func.coalesce(func.sum(-Transaction.amount_cents), 0))
                      .where(Transaction.trip_id.is_not(None)).group_by(Transaction.trip_id)).all()
    return {tid: (int(n), int(c)) for tid, n, c in rows}


def trip_out(t: Trip, payer: str, sums: dict[int, tuple[int, int]], items: dict[tuple[str, int], rb.Item]) -> dict:
    n, total = sums.get(t.id, (0, 0))
    item = items.get(("trip", t.id))
    return {"id": t.id, "name": t.name, "start": t.start.isoformat(), "end": t.end.isoformat(), "city": t.city,
            "reimburser_id": t.reimburser_id, "payer": payer, "count": n, "total_cents": total,
            "status": item.status if item and n else None}


def _one_trip(db: Session, t: Trip) -> dict:
    items = {(i.kind, i.id): i for its in rb.statuses(db).values() for i in its}
    return trip_out(t, db.get(Reimburser, t.reimburser_id).name, _trip_sums(db), items)


def _trip_or_404(db: Session, trip_id: int) -> Trip:
    t = db.get(Trip, trip_id)
    if t is None:
        raise HTTPException(404, detail={"error": trips.NO_SUCH_TRIP})
    return t


@router.get("/payers")
def list_payers(db: Session = Depends(book_db)):
    return {"payers": [payer_out(p) for p in rb.payers(db)]}


@router.post("/payers")
def add_payer(body: dict = Depends(json_object), db: Session = Depends(book_db)):
    """Made on first use (decision 6): 201 for a new payer, 200 with the one already there."""
    try:
        p, made = rb.add_payer(db, body.get("name"), deps.now())
    except rb.ReimburseError as e:
        raise bad(str(e)) from None
    db.commit()
    return JSONResponse(payer_out(p), status_code=201 if made else 200)


@router.patch("/payers/{pid}")
def rename_payer(pid: int, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    p = _payer_or_404(db, pid)
    try:
        rb.rename_payer(db, p, body.get("name"))
    except rb.ReimburseError as e:
        db.rollback()
        raise bad(str(e)) from None
    db.commit()
    return payer_out(p)


@router.post("/rules", status_code=201)
def make_rule(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """'Always reimbursable for "HILTON"' (spec, Marking). The row itself is marked first, by a person (manual), so the
    rule's retag skips it and "Also marked {n} more" counts only the other rows. One action with one Undo: there is no
    rule-delete route, so the mark, the rule and the bulk marks come back together."""
    tid = body.get("transaction_id")
    t = db.get(Transaction, tid) if isinstance(tid, int) and not isinstance(tid, bool) else None
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    try:
        payer = rb.payer_for(db, body.get("reimburser_id"))
        if t.is_transfer:
            raise rb.ReimburseError(rb.NOT_FOR_TRANSFERS)
        with capturing(db, ctx.user_id, "rule", deps.now()) as cap:
            cap.target = t.id
            rb.mark(t, payer)
            db.flush()
            rule, n = rr.add_rule(db, t, payer, deps.now())
    except rb.ReimburseError as e:
        db.rollback()
        raise bad(str(e)) from None
    db.commit()
    return {"rule": {"id": rule.id, "pattern": rule.pattern, "reimburser_id": rule.reimburser_id}, "also_marked": n,
            "undo": cap.token}


@router.get("")
def summary(db: Session = Depends(book_db)):
    """The Reimbursements tab (spec, Where they live): each payer's balance, the trips newest first, the single
    charges."""
    owed = rb.owed_by(db)
    by_payer = rb.statuses(db, owed)
    items = {(i.kind, i.id): i for its in by_payer.values() for i in its}
    payers = rb.payers(db)
    names = {p.id: p.name for p in payers}
    sums = _trip_sums(db)
    singles = db.execute(
        select(Transaction, Account.name).join(Account, Account.id == Transaction.account_id)
        .where(Transaction.reimburser_id.is_not(None), Transaction.trip_id.is_(None), Transaction.amount_cents < 0,
               Transaction.category != rb.REPAYMENT, Transaction.is_transfer.is_(False))
        .order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(SINGLES)).all()
    return {
        "as_of": deps.today().isoformat(),
        "payers": [{**payer_out(p), **_balance(owed[p.id]),
                    "settle_category": rb.settle_category(db, p.id, by_payer.get(p.id, []))} for p in payers],
        "trips": [trip_out(t, names[t.reimburser_id], sums, items)
                  for t in db.scalars(select(Trip).order_by(Trip.start.desc(), Trip.id.desc()))],
        "singles": [{**transaction_row(t, n), "status": items[("charge", t.id)].status
                     if ("charge", t.id) in items else "waiting"} for t, n in singles],
    }


@router.post("/trips", status_code=201)
def add_trip(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    try:
        fields = trips.trip_fields(db, body)
    except rb.ReimburseError as e:
        raise bad(str(e)) from None
    t = Trip(**fields, created_at=deps.now(), created_by=ctx.user_id)
    db.add(t)
    db.commit()
    return {"trip": _one_trip(db, t)}


@router.patch("/trips/{trip_id}")
def edit_trip(trip_id: int, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    """Changing the dates re-runs the grouping; the trip's own rows stay ticked (spec, Editing)."""
    t = _trip_or_404(db, trip_id)
    try:
        fields = trips.trip_fields(db, body)
    except rb.ReimburseError as e:
        raise bad(str(e)) from None
    if fields["reimburser_id"] != t.reimburser_id:
        # The trip's marked charges follow its payer, or the balances land under the old one (pre-flight F11).
        for row in db.scalars(select(Transaction).where(Transaction.trip_id == t.id,
                                                        Transaction.reimburser_id.is_not(None))):
            row.reimburser_id = fields["reimburser_id"]
    for k, v in fields.items():
        setattr(t, k, v)
    db.commit()
    return {"trip": _one_trip(db, t)}


@router.get("/trips/{trip_id}")
def get_trip(trip_id: int, db: Session = Depends(book_db)):
    t = _trip_or_404(db, trip_id)
    names = dict(db.execute(select(Account.id, Account.name)).all())
    return {"trip": _one_trip(db, t),
            "rows": [{**transaction_row(r.txn, names[r.txn.account_id]), "group": r.group, "reason": r.reason,
                      "ticked": r.ticked} for r in trips.review(db, t)]}


@router.post("/trips/{trip_id}/mark")
def mark_trip(trip_id: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
              ctx: BookContext = Depends(open_book)):
    """'Mark {n} reimbursable' (spec, The button): the ticked rows take the trip and its payer, and the rows that were on
    the trip and are unticked now leave it and stop being reimbursable (engineering choice 4). One request, one Undo."""
    t = _trip_or_404(db, trip_id)
    ids = body.get("ids")
    if (not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
            or len(set(ids)) != len(ids)):
        raise bad(NOT_UNDERSTOOD)
    listed = {r.txn.id: r.txn for r in trips.review(db, t)}
    if not set(ids) <= set(listed):
        raise bad(trips.STALE)
    payer = db.get(Reimburser, t.reimburser_id)
    with capturing(db, ctx.user_id, "trip", deps.now()) as cap:
        for tid in ids:
            rb.mark(listed[tid], payer, trip_id=t.id)
        for row in listed.values():
            if row.trip_id == t.id and row.id not in ids:
                rb.unmark(row)
    db.commit()
    return {"count": len(ids), "total_cents": sum(-listed[i].amount_cents for i in ids), "payer": payer.name,
            "owed_cents": rb.owed_map(db).get(payer.id, 0), "undo": cap.token, "trip": _one_trip(db, t)}


@router.post("/payers/{pid}/settle")
def settle(pid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    """Settle (spec, Settling): the whole balance still owed becomes the household's spending in a category this month.
    The amount must be the balance as it stands (engineering choice 7), so a second tap or a second tab settles
    nothing twice (Review Focus 3). Undoable; the undo entry is the record (engineering choice 8)."""
    p = _payer_or_404(db, pid)
    owed = rb.owed_map(db).get(p.id, 0)
    if owed <= 0:
        raise bad(rb.NOTHING_TO_SETTLE)
    amount, category = body.get("amount_cents"), body.get("category")
    if isinstance(amount, bool) or amount != owed:
        raise bad(rb.BALANCE_CHANGED, 409)
    if category not in SPENDING_CATEGORIES:
        raise bad(rb.SETTLE_CATEGORY)
    at = deps.now()
    with capturing(db, ctx.user_id, "settle", at) as cap:
        db.add(ReimburseSettlement(reimburser_id=p.id, amount_cents=owed, category=category, settled_at=at,
                                   created_by=ctx.user_id))
    db.commit()
    d = at.astimezone(clock.household_tz()).date()
    return {"owed_cents": 0, "settled_cents": owed, "category": category, "month": f"{d.year:04d}-{d.month:02d}",
            "undo": cap.token}
