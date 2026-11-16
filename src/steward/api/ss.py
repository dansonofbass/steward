"""POST the my Social Security XML as the raw request body. It is read into memory, parsed and dropped;
it is never written to disk (multipart uploads over 1 MB spool to a temp file, so this endpoint takes raw bytes)."""
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import NOT_UNDERSTOOD, bad
from steward.db.models import PERSONS
from steward.deps import BookContext, book_db, household_only, open_book
from steward.events import log_event
from steward.services.ss_import import NOT_A_RECORD, NotAnEarningsRecord, earnings_summary, parse_earnings, replace_earnings
from steward.services.undo import capturing

router = APIRouter(prefix="/ss", dependencies=[Depends(open_book), Depends(household_only)])
MAX_BYTES = 1024 * 1024
TOO_BIG = "That file is bigger than 1 MB."
UPLOAD_TYPES = ("application/xml", "application/octet-stream")


@router.post("/import", status_code=201)
async def import_earnings(request: Request, person: str | None = None, db: Session = Depends(book_db),
                        ctx: BookContext = Depends(open_book)):
    if person not in PERSONS:
        raise bad("Say whose record this is.")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() not in UPLOAD_TYPES:
        raise bad(NOT_UNDERSTOOD, 415)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise bad(TOO_BIG, 413)
    db.rollback()  # end the sign-in check's transaction so the upload doesn't hold the write lock
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BYTES:
            raise bad(TOO_BIG, 413)
    try:
        parsed = parse_earnings(bytes(raw), latest_year=deps.today().year)
    except NotAnEarningsRecord:
        raise bad(NOT_A_RECORD) from None
    finally:
        raw.clear()

    def store() -> str | None:
        with capturing(db, ctx.user_id, "earnings", deps.now()) as cap:   # P26: the import replaces what the Plan uses
            replace_earnings(db, person, parsed, deps.now())
        log_event(db, "info", "import", f"Imported a Social Security earnings record: {len(parsed.years)} years.")
        db.commit()
        return cap.token

    undo = await run_in_threadpool(store)
    return {"undo": undo,"person": person, "years": len(parsed.years), "first_year": parsed.years[0][0],
            "last_year": parsed.years[-1][0], "skipped": parsed.skipped}


@router.get("")
def records(db: Session = Depends(book_db)):
    return {"records": earnings_summary(db)}
