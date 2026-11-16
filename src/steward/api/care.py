"""Care (spec 4): the screen's answer and its writes. Parent books only: every route goes through open_book and
parent_only, so a household book answers 404, a non-member 404, and a viewer 403 on anything that changes the book.
Every write answers the full Care JSON, so the screen replaces what it has in one step."""
from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.care import edit as E
from steward.care.book import balances
from steward.care.views import care_out, compute
from steward.db.models import CareScenario
from steward.deps import BookContext, book_db, open_book, parent_only, recorded

router = APIRouter(prefix="/care", dependencies=[Depends(open_book), Depends(parent_only)])


def _owners(ctx: BookContext) -> dict[str, str]:
    return {o.key: o.label for o in ctx.owners}


def _answer(db: Session, ctx: BookContext) -> dict:
    t = deps.today()
    return care_out(compute(db, _owners(ctx), t), _owners(ctx), t)


def _write(db: Session, ctx: BookContext, fn: Callable[[], object]) -> dict:
    try:
        fn()
    except E.CareRefused as e:
        raise bad(str(e), e.status) from None
    db.commit()
    return _answer(db, ctx)


def _scenario(db: Session, scenario_id: int) -> CareScenario:
    row = db.get(CareScenario, scenario_id)
    if row is None:
        raise bad(E.NO_SUCH_SCENARIO, 404)
    return row


@router.get("")
def get_care(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return _answer(db, ctx)


@router.put("/setup")
@recorded
def put_setup(body: dict = Depends(json_object), db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return _write(db, ctx, lambda: E.save_setup(db, ctx, body, deps.today()))


@router.post("/scenarios", status_code=201)
@recorded
def post_scenario(body: dict = Depends(json_object), db: Session = Depends(book_db),
                  ctx: BookContext = Depends(open_book)):
    return _write(db, ctx, lambda: E.add_scenario(db, ctx, body, deps.today(), balances(db).home_value_cents))


@router.patch("/scenarios/{scenario_id}")
@recorded
def patch_scenario(scenario_id: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
                   ctx: BookContext = Depends(open_book)):
    row = _scenario(db, scenario_id)
    return _write(db, ctx, lambda: E.edit_scenario(db, ctx, row, body, deps.today(), balances(db).home_value_cents))


@router.delete("/scenarios/{scenario_id}")
@recorded
def delete_scenario(scenario_id: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    row = _scenario(db, scenario_id)
    return _write(db, ctx, lambda: E.remove_scenario(db, ctx, row, deps.today()))


@router.put("/quotes/{key}")
@recorded
def put_quote(key: str, body: dict = Depends(json_object), db: Session = Depends(book_db),
              ctx: BookContext = Depends(open_book)):
    return _write(db, ctx, lambda: E.set_quote(db, ctx, key, body, deps.today()))


@router.delete("/quotes/{key}")
@recorded
def delete_quote(key: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return _write(db, ctx, lambda: E.remove_quote(db, ctx, key))
