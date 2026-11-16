"""Profile (profile and household spec, API): the five sections' state, each person's own marks, and Home's line.
Household books only; writes are a manager's (open_book refuses a viewer). /api/setup is gone (P31)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object, one_of
from steward.db.directory_models import User
from steward.db.models import PROFILE_SECTIONS, STEP_STATUSES, Account, AccountType, Fact
from steward.deps import BookContext, book_db, current_user, household_only, open_book
from steward.services import children
from steward.services.accounts import latest_balance
from steward.services.profile_benefits import benefits_out
from steward.services.profile_home import home_out
from steward.services.undo import capturing
from steward.services.profile import NO_SUCH_STEP, SectionRefused, mark, profile_out, set_resume, set_section

router = APIRouter(prefix="/profile", dependencies=[Depends(open_book), Depends(household_only)])
NO_SUCH_SECTION = "No such section."
CHOOSE_STATUS = "Choose done, skipped or doesnt_apply."
SAY_LATER = "Say true or false for later."


def _only(body: dict, *allowed: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise bad(f"Unknown field: {unknown[0]}.")


def _section(key: str) -> str:
    if key not in PROFILE_SECTIONS:
        raise bad(NO_SUCH_SECTION, 404)
    return key


@router.get("")
def get_profile(me: User = Depends(current_user), db: Session = Depends(book_db)):
    return profile_out(db, me.id, deps.now())


@router.get("/benefits")
def benefits(db: Session = Depends(book_db)):
    return benefits_out(db, deps.today())


@router.post("/sections/{key}")
def answer(key: str, body: dict = Depends(json_object), me: User = Depends(current_user), db: Session = Depends(book_db)):
    _section(key)
    _only(body, "status")
    status = one_of(body.get("status"), STEP_STATUSES, CHOOSE_STATUS)
    children.purge_removed(db, deps.now())
    try:
        set_section(db, key, status, me.id, deps.now())
    except SectionRefused as e:
        raise bad(e.message, e.status) from None
    db.commit()
    return profile_out(db, me.id, deps.now())


@router.put("/sections/{key}/resume")
def resume(key: str, body: dict = Depends(json_object), me: User = Depends(current_user), db: Session = Depends(book_db)):
    _section(key)
    _only(body, "step")
    step = body.get("step", ...)
    if step is ... or (step is not None and not isinstance(step, str)):
        raise bad(NO_SUCH_STEP)
    try:
        set_resume(db, key, step, me.id, deps.now())
    except SectionRefused as e:
        raise bad(e.message, e.status) from None
    db.commit()
    return profile_out(db, me.id, deps.now())


@router.post("/seen")
def seen(body: dict = Depends(json_object), me: User = Depends(current_user), db: Session = Depends(book_db)):
    _only(body)
    mark(db, me.id, deps.now(), seen=True)
    db.commit()
    return profile_out(db, me.id, deps.now())


@router.post("/confirm")
def confirm(body: dict = Depends(json_object), me: User = Depends(current_user), db: Session = Depends(book_db)):
    _only(body)
    mark(db, me.id, deps.now(), confirmed=True)
    db.commit()
    return profile_out(db, me.id, deps.now())


@router.post("/later")
def later(body: dict = Depends(json_object), me: User = Depends(current_user), db: Session = Depends(book_db)):
    _only(body, "later")
    value = body.get("later")
    if not isinstance(value, bool):
        raise bad(SAY_LATER)
    with capturing(db, me.id, "later", deps.now()) as cap:
        mark(db, me.id, deps.now(), later=value)
    db.commit()
    return {**profile_out(db, me.id, deps.now()), "undo": cap.token}


CHOOSE_HOME = "Choose one of your homes."


@router.get("/home")
def home(db: Session = Depends(book_db)):
    return home_out(db, deps.today())


@router.put("/home/where")
def where(body: dict = Depends(json_object), ctx: BookContext = Depends(open_book), db: Session = Depends(book_db)):
    """P19: where you live is the Plan's and Care's home: the home.account_id link moves, and home.value_cents takes
    the new home's latest balance."""
    _only(body, "account_id")
    aid = body.get("account_id")
    a = db.get(Account, aid) if isinstance(aid, int) and not isinstance(aid, bool) else None
    if a is None or a.type != AccountType.property or not a.is_active:
        raise bad(CHOOSE_HOME)
    t = deps.today()
    with capturing(db, ctx.user_id, "where", deps.now()) as cap:
        db.add(Fact(key="home.account_id", value=str(a.id), as_of=t))
        lb = latest_balance(db, a.id)
        if lb is not None:
            db.add(Fact(key="home.value_cents", value=str(lb[1]), as_of=t))
    db.commit()
    return {**home_out(db, t), "undo": cap.token}
