from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from steward.api.transactions import note_counts, transaction_row
from steward.business.settings import business_type
from steward.db.models import CATEGORIES, Account, CategorySource, DuplicateKeep, Transaction
from steward import clock
from steward.deps import BookContext, book_db, not_recorded, now, open_book, recorded, today
from steward.inventory.changes import about, record
from steward.services.catchup import progress
from steward.services.categorize import P2P_MERCHANTS
from steward.services.categorizer_client import NullModelClient
from steward.services.category_rules import matching_counts
from steward.services import reimburse as rb
from steward.services.review import duplicate_pairs, waiting_filter
from steward.services.undo import capturing

router = APIRouter(prefix="/review", dependencies=[Depends(open_book)])

SNOOZE_DAYS = 7
LEARN_DAYS = 180
FIXED_CHIPS = ("groceries", "dining", "shopping", "transport", "subscriptions", "personal")
NOT_CHIPS = ("uncategorized", "transfer", "investment")


def top_categories(db: Session) -> list[str]:
    """The six chips: the most-used corrected categories lately, filled from the fixed six."""
    since = now() - timedelta(days=LEARN_DAYS)
    rows = db.execute(select(Transaction.category, func.count()).where(
        Transaction.category_source == CategorySource.correction, Transaction.reviewed_at >= since,
        Transaction.category.not_in(NOT_CHIPS)).group_by(Transaction.category)).all()
    ranked = sorted(rows, key=lambda r: (-r[1], CATEGORIES.index(r[0]) if r[0] in CATEGORIES else len(CATEGORIES)))
    out = [c for c, _ in ranked][:6]
    out += [c for c in FIXED_CHIPS if c not in out]
    return out[:6]


class KeepIn(BaseModel):
    a: int
    b: int


SUGGEST_AT = 60
BUSINESS_ROWS = 50


def business_questions(db: Session, on: date) -> tuple[list[tuple[Transaction, str]], int]:
    """Money out since the start of last year that the categorizer thinks is likely business, still personal with no
    decision, not a transfer, not yet answered (business plan ruling 5). Oldest first."""
    cond = and_(Transaction.amount_cents < 0, Transaction.is_transfer.is_(False), Transaction.business_pct == 0,
                Transaction.business_source == "none", Transaction.reimburser_id.is_(None),
                Transaction.business_hint >= SUGGEST_AT,
                Transaction.business_answered_at.is_(None), Transaction.posted_at >= date(on.year - 1, 1, 1))
    count = db.scalar(select(func.count()).select_from(Transaction).where(cond))
    rows = db.execute(select(Transaction, Account.name).join(Account).where(cond)
                      .order_by(Transaction.posted_at.asc(), Transaction.id.asc()).limit(BUSINESS_ROWS)).all()
    return [(t, n) for t, n in rows], count


def reason_of(t: Transaction, expected: bool = True) -> str:
    """Why the row is in Review (phase 12 decision 8): a payment app's row, the model's guess, the model couldn't
    tell, the model hasn't looked yet, or, with no categorizer coming, no rule matched it (INS-21)."""
    if t.merchant in P2P_MERCHANTS:
        return "p2p"
    if t.guess_category:
        return "unsure"
    if t.model_asked_at is not None:
        return "unknown"
    return "waiting" if expected else "no_rule"


def _review_row(t: Transaction, name: str, matching: int | None, patterns: set[str] | None, notes: int,
                expected: bool = True) -> dict:
    row = {**transaction_row(t, name, note_count=notes), "reason": reason_of(t, expected), "guess": t.guess_category,
           "matching": matching}
    if patterns is not None:
        row["reimburse_ok"] = rb.can_reimburse(t, patterns)
    return row


def _health(request: Request) -> dict | None:
    monitor = getattr(getattr(request.app.state, "advisor", None), "monitor", None)
    health = getattr(monitor, "health", None)
    return health if isinstance(health, dict) else None


def _gateway_categorizing(request: Request) -> bool:
    """True only when the gateway's last health answer lists the categorizer; a missing advisor reads as waiting."""
    health = _health(request)
    return health is not None and health.get("categorizer") is True


def _categorizer_expected(request: Request) -> bool:
    """Install gate INS-21: a categorizer is coming only from a paired gateway (or the development categorizer URL) that
    lists it, or that is away and so not known to lack one. With no gateway, or one that answers without a local model,
    rows wait in Review and nothing says the gateway will sort them."""
    model = getattr(request.app.state, "model", None)
    if model is None or isinstance(model, NullModelClient):
        return False
    health = _health(request)
    return health is None or health.get("categorizer") is True


@router.get("")
def review_queue(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    cond = waiting_filter(now())
    count = db.scalar(select(func.count()).select_from(Transaction).where(cond))
    rows = db.execute(select(Transaction, Account.name).join(Account).where(cond)
                      .order_by(Transaction.posted_at.asc(), Transaction.id.asc()).limit(100)).all()
    matches = matching_counts(db, [t for t, _ in rows])
    sorted_count = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.category_source == CategorySource.model, Transaction.reviewed_at.is_(None))) or 0
    expected = _categorizer_expected(request)
    background = {**progress(db, now()), "waiting": not _gateway_categorizing(request), "expected": expected}
    pairs = duplicate_pairs(db)
    names = dict(db.execute(select(Account.id, Account.name)).all())
    asked, asked_count = ([], 0)
    if ctx.book.kind == "household" and business_type(db) != "none":
        asked, asked_count = business_questions(db, today())
    pats = rb.refundable_patterns(db) if ctx.book.kind == "household" else None
    # Each card's note count, so a card shows notes written anywhere; counts only, the card asks for the notes it shows.
    # This route is the web's alone: no advisor or gateway path reads it (tests/advisor/test_tools_never_read_notes.py).
    notes = note_counts(db, [t.id for t, _ in rows] + [t.id for t, _ in asked] + [x.id for pair in pairs for x in pair])

    def row(t: Transaction, name: str) -> dict:
        return transaction_row(t, name, note_count=notes.get(t.id, 0))

    return {"uncategorized": [_review_row(t, n, matches[t.id], pats, notes.get(t.id, 0), expected)
                              for t, n in rows], "count": count,
            "sorted_count": sorted_count, "background": background,
            "empty": db.scalar(select(Transaction.id).limit(1)) is None,   # phase 17: a book with no transactions at all
            "duplicates": [{"a": row(x, names[x.account_id]), "b": row(y, names[y.account_id])} for x, y in pairs],
            "duplicate_count": len(pairs), "top_categories": top_categories(db),
            "business": [row(t, n) for t, n in asked], "business_count": asked_count}


@router.post("/duplicates/keep", status_code=204)
@recorded
def keep_both(body: KeepIn, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    lo, hi = sorted((body.a, body.b))
    a, b = (db.get(Transaction, lo), db.get(Transaction, hi)) if lo != hi else (None, None)
    if a is None or b is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    if db.get(DuplicateKeep, (lo, hi)) is None:
        db.add(DuplicateKeep(a_id=lo, b_id=hi, kept_at=now()))
        record(db, ctx, "txn.keep_both", after={"about": [about(a), about(b)]})
        db.commit()
    return Response(status_code=204)


def _get_or_404(db: Session, tid: int) -> Transaction:
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(404, detail={"error": "No such transaction."})
    return t


@router.post("/{tid}/snooze")
@not_recorded("Snoozing only hides a transaction from Review for a while.")
def snooze(tid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    t = _get_or_404(db, tid)
    at = now()
    until = at + timedelta(days=SNOOZE_DAYS)
    with capturing(db, ctx.user_id, "snooze", at) as cap:
        cap.target = t.id
        t.snoozed_until = until
    db.commit()
    return {"undo": cap.token, "until": until.astimezone(clock.household_tz()).date().isoformat()}


@router.post("/{tid}/ignore")
@recorded
def ignore(tid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    t = _get_or_404(db, tid)
    at = now()
    with capturing(db, ctx.user_id, "ignore", at) as cap:
        cap.target = t.id
        t.reviewed_at = at
    record(db, ctx, "txn.reviewed", target_id=tid, after={"about": about(t)})
    db.commit()
    return {"undo": cap.token}
