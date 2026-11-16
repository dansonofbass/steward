"""The inventory (spec 3, design pass decisions 2-5): the list, the item page and every item write."""
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from steward.api.body import bad, json_object
from steward.db.models import InventoryItem
from steward.inventory.present import parent_name
from steward.deps import BookContext, book_db, now, open_book, parent_only, recorded, today, viewer_ok
from steward.inventory.changes import page
from steward.inventory.items import (
    NO_SUCH_ITEM, ItemRefused, close_item, create_item, edit_item, reopen_item, reveal,
)
from steward.inventory.overview import overview
from steward.inventory.suggestions import SuggestionRefused, get_open, mark_added, pending_income, refresh, summary
from steward.inventory.views import item_detail, item_row, load
from steward.watch.balances import check_low

router = APIRouter(prefix="/inventory", dependencies=[Depends(open_book), Depends(parent_only)])


def owners_of(ctx: BookContext) -> dict[str, str]:
    return {o.key: o.label for o in ctx.owners}


def get_item(db: Session, item_id: int) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise bad(NO_SUCH_ITEM, 404)
    return item


def detail(request: Request, db: Session, ctx: BookContext, item_id: int) -> dict:
    L = load(db, owners_of(ctx))
    return item_detail(db, L, L.by_id[item_id], today(), request.app.state.books.directory)


def refused(e: ItemRefused):
    return bad(str(e), e.status)


@router.get("")
def list_items(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    L, t = load(db, owners_of(ctx)), today()
    return {"items": [item_row(L, i, t) for i in L.items],
            "suggestions": summary(db, parent_name(L.owners.values())) if ctx.is_manager else None}


@router.get("/overview")
def home_overview(request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    owners, t = owners_of(ctx), today()
    recent = page(db, request.app.state.books.directory, ctx.book.id, user_id=None, kind=None, before=None, today=t,
                  owners=owners, limit=3)["changes"]
    L = load(db, owners)
    sugg = summary(db, parent_name(L.owners.values())) if ctx.is_manager else None
    return overview(db, L, t, recent=recent,
                    suggestions={"count": sugg["count"], "found_in": sugg["found_in"]} if sugg else None,
                    pending_income=pending_income(db) if ctx.is_manager else ())


@router.get("/items/{item_id}")
def get_one(item_id: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    get_item(db, item_id)
    return detail(request, db, ctx, item_id)


@router.post("/items", status_code=201)
@recorded
def add(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
        ctx: BookContext = Depends(open_book)):
    sugg = None
    if body.get("suggestion_id") is not None:
        try:
            sugg = get_open(db, body["suggestion_id"]) if isinstance(body["suggestion_id"], int) else None
        except SuggestionRefused as e:
            raise bad(str(e), e.status) from None
        if sugg is None:
            raise bad("No such suggestion.", 404)
    try:
        item = create_item(db, ctx, body, today=today(), from_suggestion=sugg.payer_name if sugg else None)
    except ItemRefused as e:
        raise refused(e) from None
    if sugg is not None:
        mark_added(db, ctx, sugg, item)
    refresh(db, today())
    db.commit()
    return detail(request, db, ctx, item.id)


def _floor_of(item: InventoryItem):
    return json.loads(item.details or "{}").get("floor_cents")


@router.patch("/items/{item_id}")
@recorded
def change(item_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
           ctx: BookContext = Depends(open_book)):
    item = get_item(db, item_id)
    floor = _floor_of(item)
    try:
        edit_item(db, ctx, item, body, today=today())
    except ItemRefused as e:
        raise refused(e) from None
    if item.kind == "account" and _floor_of(item) != floor:
        check_low(db, today(), now(), after="floor", account_id=item.account_id)       # watching ruling 11: a new floor checks the balance at once
    refresh(db, today())
    db.commit()
    return detail(request, db, ctx, item_id)


@router.post("/items/{item_id}/close")
@recorded
def close(item_id: int, request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
          ctx: BookContext = Depends(open_book)):
    item = get_item(db, item_id)
    try:
        close_item(db, ctx, item, body)
    except ItemRefused as e:
        raise refused(e) from None
    db.commit()
    return detail(request, db, ctx, item_id)


@router.post("/items/{item_id}/reopen")
@recorded
def reopen(item_id: int, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    item = get_item(db, item_id)
    try:
        reopen_item(db, ctx, item)
    except ItemRefused as e:
        raise refused(e) from None
    db.commit()
    return detail(request, db, ctx, item_id)


@router.post("/items/{item_id}/full-number")
@viewer_ok
@recorded
def full_number(item_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Viewers may call it (design pass 5); it changes no item, only writes its own record (ruling 12)."""
    item = get_item(db, item_id)
    try:
        number = reveal(db, ctx, item)
    except ItemRefused as e:
        raise refused(e) from None
    db.commit()
    return {"number": number}
