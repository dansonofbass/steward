"""The Plan API (spec 7). A write request's session begins IMMEDIATE and a GET's reads (deps._book_session), and
each handler reads what it needs into plain objects and ends the transaction before the engine runs: a solve never
holds the write lock."""
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from steward.api.body import bad, json_object
from steward.business.report import range_out
from steward.db.directory_models import User
from steward import clock, deps
from steward.deps import book_db, current_user, household_only, open_book, viewer_ok
from steward.engine import EngineInputs, datafiles, savings_checklist
from steward.engine.inputs import InputError
from steward.engine.next_dollar import next_dollar
from steward.engine.tax.rules import RulesError
from steward.services.plan import (
    checklist_out, impact_out, impacts_cached, inputs_summary, latest_plan, moves_out, newest_before, plan_history,
    people_in, plan_out, record_failure, result_out, save_plan, saved_state, solve_cached,
)
from steward.services.profile_benefits import benefits_out
from steward.services.next_dollar import build_next_dollar, next_dollar_out
from steward.services.plan_cache import PlanCache
from steward.services.plan_inputs import (
    PlanInputs, SetupIncomplete, build_checklist, build_inputs, missing, owner_names, setup_items,
)
from steward.services.plan_levers import LeverError, LeverState, lever_specs, levers_dict, resolve_state

router = APIRouter(dependencies=[Depends(open_book), Depends(household_only)])
FINISH_SETUP = "Finish setting up the plan first."
NEXT_DOLLAR_FAILED = "Next dollar couldn't be worked out right now."


def _cache(request: Request) -> PlanCache:
    return request.app.state.books.plan_cache(request.state.book.book.id)


def _inputs(request: Request, db: Session) -> PlanInputs:
    """Built engine inputs, cached until the vault changes or the day turns; SetupIncomplete is never cached."""
    today = deps.today()
    return _cache(request).inputs.get_or_build(today, lambda: build_inputs(db, today))


def state_out(state: LeverState, notes: dict[str, str]) -> dict:
    """The resolved levers. Clients send back only what someone moved, plus `pinned` to unpin: echoing this whole
    object as `try` would pin every lever (M2-B ruling 9)."""
    return {"assumed": levers_dict(state.assumed), "try": levers_dict(state.trial), "pinned": sorted(state.pinned),
            "try_notes": notes}


def inputs_out(pi: PlanInputs, moves: dict | None = None) -> dict:
    return {"spending_months": pi.flows.months, "spending_basis_cents": pi.household.spending_basis_cents,
            "surplus_cents": pi.household.surplus_cents, "facts_as_of": pi.facts_as_of,
            "set_asides": {"updated_at": pi.set_asides.updated_at, "updated_by": pi.set_asides.updated_by,
                           "yearly_count": pi.set_asides.yearly_count, "one_offs": list(pi.set_asides.one_offs)},
            # The Try's college options in dollars, at each child's own share and living choice (Engineering choice 23).
            "college": {**datafiles.college_table(),
                        "children": [{"label": c.label, "share_pct": c.share_pct, "covers_living": c.covers_living}
                                     for c in pi.household.children]},
            "moves": moves}


def _resolve(body: dict, saved: LeverState | None, pi: PlanInputs) -> tuple[LeverState, dict[str, str]]:
    try:
        return resolve_state(body, saved, pi.household, pi.observed)
    except LeverError as e:
        raise bad(people_in(str(e), pi.names)) from None


def _engine_failed(db: Session, exc: Exception) -> HTTPException:
    return HTTPException(503, detail=record_failure(db, exc))


@router.get("/plan")
def get_plan(request: Request, db: Session = Depends(book_db)):
    try:
        pi = _inputs(request, db)
    except SetupIncomplete as e:
        return {"setup": [i.as_dict() for i in e.items]}
    row = latest_plan(db)
    state, notes = _resolve({}, saved_state(row), pi)
    saved = plan_out(db, row, current=True) if row is not None else None
    # The Overview's change line compares with the newest plan saved before today (Engineering choice 8).
    before = newest_before(db, datetime.combine(deps.today(), time.min, clock.household_tz()).astimezone(timezone.utc))
    previous = plan_out(db, before, current=(before is not None and row is not None and before.id == row.id)) \
        if before is not None else None
    benefits = benefits_out(db, deps.today())
    db.rollback()                                      # end the transaction before the engine runs
    try:
        res = solve_cached(_cache(request), EngineInputs(pi.household, state.assumed))
    except Exception as e:  # noqa: BLE001 - any engine failure gets spec 8's answer
        raise _engine_failed(db, e) from None
    return {"plan": saved, "previous": previous, "levers": state_out(state, notes), "result": result_out(res, pi.names),
            "inputs_summary": inputs_summary(pi, res),
            "lever_specs": lever_specs(pi.names), "inputs": inputs_out(pi, moves_out(pi, state.assumed, benefits)),
            "names": pi.names,
            "business": range_out(pi.business) if pi.business is not None else None}


def _prepare(request: Request, body: dict, db: Session) -> tuple[PlanInputs, LeverState, dict[str, str]]:
    try:
        pi = _inputs(request, db)
    except SetupIncomplete as e:
        raise HTTPException(409, detail={"error": FINISH_SETUP, "setup": [i.as_dict() for i in e.items]}) from None
    state, notes = _resolve(body, saved_state(latest_plan(db)), pi)
    db.rollback()
    return pi, state, notes


@router.post("/plan/preview")
@viewer_ok
def preview(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    pi, state, notes = _prepare(request, body, db)
    try:
        res = solve_cached(_cache(request), EngineInputs(pi.household, state.assumed))
    except Exception as e:  # noqa: BLE001
        raise _engine_failed(db, e) from None
    return {"levers": state_out(state, notes), "result": result_out(res, pi.names)}


@router.post("/plan/impacts")
@viewer_ok
def impacts(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db)):
    pi, state, notes = _prepare(request, body, db)
    try:
        rows = impacts_cached(_cache(request), EngineInputs(pi.household, state.assumed), state.trial)
    except Exception as e:  # noqa: BLE001
        raise _engine_failed(db, e) from None
    return {"levers": state_out(state, notes), "impacts": [impact_out(i, pi.names) for i in rows]}


@router.post("/plan", status_code=201)
def save(request: Request, body: dict = Depends(json_object), me: User = Depends(current_user),
         db: Session = Depends(book_db)):
    user_id = me.id
    pi, state, notes = _prepare(request, body, db)
    try:
        res = solve_cached(_cache(request), EngineInputs(pi.household, state.assumed))
    except Exception as e:  # noqa: BLE001
        raise _engine_failed(db, e) from None
    saved_at = deps.now()

    p = save_plan(db, user_id, state, res, saved_at, summary=inputs_summary(pi, res))
    db.commit()
    return {"plan": plan_out(db, p, current=True), "levers": state_out(state, notes), "result": result_out(res, pi.names)}


@router.get("/plan/history")
def history(limit: str = "20", db: Session = Depends(book_db)):
    if not (limit.isascii() and limit.isdigit()) or not 1 <= int(limit) <= 200:
        raise bad("Choose between 1 and 200 saves.")
    rows = plan_history(db, int(limit))
    return {"history": [plan_out(db, p, current=(i == 0)) for i, p in enumerate(rows)]}


@router.get("/plan/setup")
def get_setup(db: Session = Depends(book_db)):
    items = setup_items(db, deps.today())
    return {"ready": not missing(items), "setup": [i.as_dict() for i in items], "names": owner_names(db)}


@router.get("/checklist")
def checklist(db: Session = Depends(book_db)):
    ci, names = build_checklist(db, deps.today())
    return {"items": checklist_out(savings_checklist(ci), names)}


@router.get("/next-dollar")
def get_next_dollar(request: Request, db: Session = Depends(book_db)):
    """Where the next dollar goes (cash-flow and tax spec section 6). Read-only: Steward suggests; it never moves
    money. Answers and settings go through POST /facts and PATCH /accounts/{id}."""
    try:
        pi = _inputs(request, db)
    except SetupIncomplete as e:
        raise HTTPException(409, detail={"error": FINISH_SETUP, "setup": [i.as_dict() for i in e.items]}) from None
    nd = build_next_dollar(db, deps.today(), pi)
    db.rollback()                                        # end the transaction before the engine runs
    try:
        steps = next_dollar(nd)
    except (InputError, RulesError):
        raise HTTPException(503, detail={"error": NEXT_DOLLAR_FAILED}) from None
    return next_dollar_out(nd, steps)
