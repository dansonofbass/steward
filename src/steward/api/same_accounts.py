"""Same account, two feeds (same-account spec, API). Household books only: every route goes through open_book and
household_only, so a parent book answers 404 and a viewer gets 403 on every write. Each write takes the write lock
first (begin_write) and commits once; Undo is the usual POST /undo/{token}."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import NOT_UNDERSTOOD, bad, json_object
from steward.db.engine import begin_write
from steward.db.models import Account, HeldFeed, SameAccountAnswer
from steward.deps import BookContext, book_db, household_only, open_book
from steward.services.same_account import apart, questions
from steward.services.same_account import merge as merging

router = APIRouter(dependencies=[Depends(open_book), Depends(household_only)])
ANSWERED = "That question was already answered."


def _merged(kept: Account, dropped: int, kept_new: int) -> dict:
    return {"kept": {"id": kept.id, "name": kept.name}, "dropped": dropped, "kept_new": kept_new}


def _open(db: Session, question: str) -> HeldFeed | SameAccountAnswer:
    q = questions.get(db, question)
    if q is None:
        raise bad(ANSWERED, 404)
    return q


def _into(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad(NOT_UNDERSTOOD)
    return value


def _pair(db: Session, aid: int, into: int, *, same_type: bool = True) -> tuple[Account, Account]:
    """(the account kept, the one merged into it) for Merge into…, or its plain-words refusal. The card's merge
    passes same_type=False (Engineering choice 12)."""
    keep, other = db.get(Account, into), db.get(Account, aid)
    try:
        merging.check(db, keep, other, same_type=same_type)
    except merging.MergeRefused as e:
        raise bad(str(e), e.status) from None
    return keep, other


@router.get("/same-accounts")
def list_questions(db: Session = Depends(book_db)):
    return {"questions": questions.open_questions(db)}


@router.post("/same-accounts/{question}/merge")
def merge_question(question: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    q = _open(db, question)
    if isinstance(q, HeldFeed):
        keep_id, other = q.candidate_account_id, q
    else:                                   # a pair question can be stale: Merge into's refusals, bar the type check
        keep_id, other = _pair(db, q.other_account_id, q.account_id, same_type=False)[0].id, q.other_account_id
    m = merging.merge(db, keep_id, other, user_id=ctx.user_id, now=deps.now())
    db.commit()
    return {"merged": _merged(db.get(Account, m.kept_id), m.dropped, m.kept_new), "undo": m.undo}


@router.post("/same-accounts/{question}/different")
def keep_apart(question: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    begin_write(db)
    token = apart.keep_apart(db, _open(db, question), ctx.user_id, deps.now())
    db.commit()
    return {"undo": token}


@router.get("/accounts/{aid}/merge-preview")
def merge_preview(aid: int, into: str = "", db: Session = Depends(book_db)):
    if not (into.isascii() and into.isdigit()) or len(into) > 12:
        raise bad(NOT_UNDERSTOOD)
    keep, other = _pair(db, aid, int(into))
    dropped, moved = merging.preview(db, keep.id, other.id)
    return {"merged": _merged(keep, dropped, moved)}


@router.post("/accounts/{aid}/merge-into")
def merge_into(aid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
               ctx: BookContext = Depends(open_book)):
    begin_write(db)
    keep, other = _pair(db, aid, _into(body.get("into")))
    m = merging.merge(db, keep.id, other.id, user_id=ctx.user_id, now=deps.now())
    db.commit()
    return {"merged": _merged(db.get(Account, m.kept_id), m.dropped, m.kept_new), "undo": m.undo}
