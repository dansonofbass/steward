"""Add an item → From a tax form (decision 10). Saving runs the suggester, then says what the form added."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from steward.api.body import bad, json_object
from steward.api.inventory import owners_of
from steward.db.models import StoredFile, Suggestion
from steward.deps import BookContext, book_db, open_book, parent_only, recorded, today
from steward.inventory.present import parent_name
from steward.inventory.suggestions import refresh
from steward.inventory.taxforms import FormRefused, clean_form, parse_csv, result_for, save_form

router = APIRouter(prefix="/inventory/tax-forms", dependencies=[Depends(open_book), Depends(parent_only)])
NO_CSV = "Choose a CSV file."
MAX_CSV = 1024 * 1024
CSV_TOO_BIG = "That file is bigger than 1 MB."


def _open_keys(db: Session) -> set[tuple[str, str]]:
    return set(db.execute(select(Suggestion.kind, Suggestion.payer_key).where(Suggestion.status == "open")).all())


@router.post("", status_code=201)
@recorded
def type_in(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    try:
        clean = clean_form(body, set(owners_of(ctx)), today().year)
    except FormRefused as e:
        raise bad(str(e), e.status) from None
    file_id = body.get("file_id")
    if file_id is not None and (not isinstance(file_id, int) or isinstance(file_id, bool)
                                or db.get(StoredFile, file_id) is None):
        raise bad("No such file.", 404)
    before = _open_keys(db)
    f = save_form(db, ctx, clean, file_id=file_id)
    refresh(db, today())
    out = result_for(db, f, before, parent_name(owners_of(ctx).values()))
    db.commit()
    return out


@router.post("/csv", status_code=201)
@recorded
async def import_csv(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    try:
        form = await request.form(max_files=1, max_fields=2)
    except Exception:  # noqa: BLE001 - a malformed multipart body
        raise bad("That upload wasn't understood.") from None
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise bad(NO_CSV)
    raw = await upload.read(MAX_CSV + 1)
    if len(raw) > MAX_CSV:
        raise bad(CSV_TOO_BIG, 413)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise bad("Save the CSV as UTF-8 and try again.") from None
    owners, year = owners_of(ctx), today().year
    try:
        rows = parse_csv(text, owners)
        cleaned = []
        for r in rows:
            try:
                cleaned.append(clean_form(r, set(owners), year))
            except FormRefused as e:
                raise FormRefused(f"Row {r['_row']}: {e}") from None
    except FormRefused as e:
        raise bad(str(e), e.status) from None
    note = f"From {upload.filename or 'a CSV'}"

    def store() -> dict:
        before = _open_keys(db)
        saved = [save_form(db, ctx, c, note=note) for c in cleaned]
        refresh(db, today())
        name = parent_name(owners.values())
        results = [result_for(db, f, before, name) for f in saved]
        db.commit()
        return {"saved": len(saved), "results": results}

    # Off the event loop: BEGIN IMMEDIATE can wait up to the busy timeout for another request's write.
    return await run_in_threadpool(store)
