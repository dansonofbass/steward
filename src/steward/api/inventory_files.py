"""Files on items (spec 3.5, 8; decision 7). The upload is read by hand so its size is checked before the body is
parsed, and a refused upload leaves no row and no bytes."""
import hashlib
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from steward.api.body import bad
from steward.api.inventory import detail, get_item
from steward.books.history import names_for
from steward.db.models import StoredFile, TaxForm
from steward.deps import BookContext, book_db, now, open_book, parent_only, recorded, today
from steward.inventory import kinds as K
from steward.inventory.changes import record
from steward.inventory.files import (
    DISK, EMPTY, MAX_BYTES, TOO_BIG, UNREADABLE, FileRefused, FileUnreadable, clean_name, looks_like_tax_form, sniff,
)
from steward.inventory.items import ItemRefused, edit_item
from steward.inventory.views import file_row

router = APIRouter(prefix="/inventory", dependencies=[Depends(open_book), Depends(parent_only)])
NO_FILE = "Choose a file to attach."
NO_SUCH_FILE = "No such file."
NOT_UNDERSTOOD = "That upload wasn't understood."


def _disposition(name: str) -> str:
    plain = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name)
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"


@router.post("/files", status_code=201)
@recorded
async def upload(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    declared = (request.headers.get("content-length") or "0").strip()
    if not declared.isascii() or not declared.isdigit():
        raise bad(NOT_UNDERSTOOD)
    if len(declared) > 12:
        raise bad(TOO_BIG, 413)
    if int(declared) > MAX_BYTES + 1024 * 1024:
        raise bad(TOO_BIG, 413)
    try:
        form = await request.form(max_files=1, max_fields=4)
    except Exception:  # noqa: BLE001 - any malformed multipart body
        raise bad(NOT_UNDERSTOOD) from None
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise bad(NO_FILE)
    data = await upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise bad(TOO_BIG, 413)
    if not data:
        raise bad(EMPTY)
    name = clean_name(upload.filename)
    try:
        content_type, label = sniff(name, data)
    except FileRefused as e:
        raise bad(str(e), e.status) from None
    # Off the event loop: BEGIN IMMEDIATE can wait up to the busy timeout for another request's write, and the bytes
    # go to disk.
    return await run_in_threadpool(_attach, request, db, ctx, name, data, content_type, label,
                                   form.get("item_id"), form.get("confirm") == "true")


def _attach(request: Request, db: Session, ctx: BookContext, name: str, data: bytes, content_type: str, label: str,
            raw_item, confirm: bool) -> dict:
    item = get_item(db, int(raw_item)) if isinstance(raw_item, str) and raw_item.isdigit() else None
    if raw_item not in (None, "") and item is None:
        raise bad("No such item.", 404)
    row = StoredFile(item_id=item.id if item else None, name=name, content_type=content_type, size=len(data),
                     sha256=hashlib.sha256(data).hexdigest(), uploaded_at=now(), uploaded_by=ctx.user_id)
    db.add(row)
    db.flush()
    record(db, ctx, "file.add", target_id=row.id, item_id=row.item_id, after={"name": name, "type": label, "size": len(data)})
    if item is not None and confirm and item.status == "needs_checking":
        try:
            edit_item(db, ctx, item, {"status": "confirmed", "note": f"Attached {name}"}, today=today())
        except ItemRefused as e:
            raise bad(str(e), e.status) from None
    store = request.app.state.books.file_store(ctx.book)
    try:
        store.write(row.id, data)
    except OSError:
        db.rollback()
        store.remove(row.id)
        raise bad(DISK, 507) from None
    try:
        db.commit()
    except Exception:
        store.remove(row.id)
        raise
    names = names_for(request.app.state.books.directory, [ctx.user_id])
    return {"file": file_row(row, names, today()), "item": detail(request, db, ctx, item.id) if item else None,
            "looks_like_tax_form": looks_like_tax_form(name)}


@router.get("/files/{file_id}")
def download(file_id: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    row = db.get(StoredFile, file_id)
    if row is None:
        raise bad(NO_SUCH_FILE, 404)
    try:
        data = request.app.state.books.file_store(ctx.book).read(row.id)
    except FileUnreadable:
        raise bad(UNREADABLE, 500) from None
    return Response(data, media_type=row.content_type, headers={
        "Content-Disposition": _disposition(row.name), "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.delete("/files/{file_id}", status_code=204)
@recorded
def remove(file_id: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    row = db.get(StoredFile, file_id)
    if row is None:
        raise bad(NO_SUCH_FILE, 404)
    record(db, ctx, "file.remove", target_id=row.id, item_id=row.item_id,
           before={"name": row.name, "type": K.CONTENT_LABELS.get(row.content_type, "File"), "size": row.size})
    db.execute(update(TaxForm).where(TaxForm.file_id == row.id).values(file_id=None))
    db.delete(row)
    db.commit()
    request.app.state.books.file_store(ctx.book).remove(file_id)
    return Response(status_code=204)
