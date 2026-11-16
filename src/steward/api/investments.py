"""The investment account page's routes (investment views spec), household books only: fund cost overrides here; the
positions import, the contribution limits and the page join in Tasks 4 to 6."""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from steward.api.body import bad, json_object
from steward.api.imports import CHUNK, _decode
from steward.api.limits import MB
from steward.db.directory_models import User
from steward.db.models import INVESTMENT_TYPES, Account
from steward.deps import book_db, current_user, household_only, now, open_book, today
from steward.events import log_event
from steward.services import contributed, costs, investment_page, positions
from steward.services.importers.base import ParseError

router = APIRouter(dependencies=[Depends(open_book), Depends(household_only)])


@router.put("/expense-ratios")
def set_expense_ratio(body: dict = Depends(json_object), me: User = Depends(current_user), db: Session = Depends(book_db)):
    if "ratio_pct" not in body:
        raise bad(costs.RATIO_RULE)
    try:
        symbol = costs.set_override(db, body.get("symbol"), body["ratio_pct"], me.id, now())
    except ValueError as e:
        raise bad(str(e)) from None
    db.commit()
    ovr = costs.overrides(db)
    return {"symbol": symbol, "ratio_pct": costs.pct_text(ovr[symbol]) if symbol in ovr else None}


NO_SUCH_ACCOUNT = "No such account."
NOT_INVESTMENT = "That isn't an investment account."
FUTURE = "Choose a date that isn't in the future."
NOT_A_DATE = "Choose a date."
TOO_BIG = "That file is bigger than 1 MB."


def investment_account(db: Session, aid: int) -> Account:
    a = db.get(Account, aid)
    if a is None:
        raise bad(NO_SUCH_ACCOUNT, 404)
    if a.type not in INVESTMENT_TYPES:
        raise bad(NOT_INVESTMENT, 409)
    return a


def _as_of(raw: str | None) -> date:
    if not raw:
        return today()
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        raise bad(NOT_A_DATE) from None
    if day > today():
        raise bad(FUTURE)
    return day


def _text(file: UploadFile) -> str:
    """Read the upload in memory (the import rule: it is never written anywhere)."""
    raw = b""
    while chunk := file.file.read(CHUNK):
        raw += chunk
        if len(raw) > MB:
            raise bad(TOO_BIG, 413)
    return _decode(raw)


def _plain(e: Exception) -> str:
    return e.reason if isinstance(e, ParseError) else str(e)


# Plain def, as the transaction import's: FastAPI runs them in its threadpool, so a wait for the book's write lock
# never stalls the event loop.
@router.post("/accounts/{aid}/positions/preview")
def preview_positions(aid: int, file: UploadFile = File(...), mapping: str | None = Form(None),
                      as_of: str | None = Form(None), db: Session = Depends(book_db)):
    a = investment_account(db, aid)
    day = _as_of(as_of)
    text = _text(file)
    try:
        return {**positions.preview(db, a, text, positions.mapping_from(mapping)), "as_of": day.isoformat()}
    except ValueError as e:
        raise bad(_plain(e)) from None


@router.post("/accounts/{aid}/positions", status_code=201)
def save_positions(aid: int, file: UploadFile = File(...), mapping: str = Form(...), as_of: str | None = Form(None),
                   me: User = Depends(current_user), db: Session = Depends(book_db)):
    a = investment_account(db, aid)
    day = _as_of(as_of)
    text = _text(file)
    try:
        out = positions.commit(db, a, text, file.filename or "positions.csv", positions.mapping_from(mapping), day,
                               me.id, now())
    except ValueError as e:
        raise bad(_plain(e)) from None
    log_event(db, "info", "import", f"Imported {out['count']} positions into {a.name}")
    db.commit()
    return out


@router.get("/contributions")
def contribution_limits(db: Session = Depends(book_db)):
    return contributed.limits_out(db, today())


@router.get("/accounts/{aid}/investment")
def investment(aid: int, db: Session = Depends(book_db)):
    return investment_page.investment_out(db, investment_account(db, aid), today())
