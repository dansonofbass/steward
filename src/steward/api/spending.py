"""Spending (phase 11b spec, API): the month, Over time and the targets. Household books only: every route goes
through open_book and household_only, so a parent book answers 404 (a parent's money never appears in the household's
spending) and a viewer gets 403 on the one write. Integer cents throughout."""
from __future__ import annotations

import calendar
import re
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from steward import deps
from steward.api.body import bad, json_object
from steward.db.models import SpendingTarget
from steward.books.people import names_of
from steward.deps import BookContext, book_db, household_only, open_book
from steward.services import spending as svc
from steward.services.undo import capturing

router = APIRouter(prefix="/spending", dependencies=[Depends(open_book), Depends(household_only)])
MONTH = re.compile(r"(\d{4})-(\d{2})", re.ASCII)   # fullmatch: no trailing newline gets through
BAD_MONTH = "Choose a month like 2026-10: this month or an earlier one."
BAD_SPAN = "Choose 6 or 12 months."
BAD_FLOW_SPAN = "Choose between 1 and 24 months."


def _month(month: str | None, today: date) -> date:
    """?month= (engineering choice 15): YYYY-MM, 2000 or later, not after the household's month; default this one."""
    this = today.replace(day=1)
    if month is None:
        return this
    m = MONTH.fullmatch(month)
    if not m or not 1 <= int(m.group(2)) <= 12 or int(m.group(1)) < 2000:
        raise bad(BAD_MONTH)
    chosen = date(int(m.group(1)), int(m.group(2)), 1)
    if chosen > this:
        raise bad(BAD_MONTH)
    return chosen


def _before_history(month: date, this: date, earliest: str | None) -> str | None:
    """Ruling 22: a past month before the book's earliest month (any past month, in a book with no history yet) has
    nothing to show; the refusal names the first month there is. Never this month: a book whose only rows are dated
    after today's household month still opens on it."""
    first = min(svc.first_of(earliest), this) if earliest else this
    if month >= first:
        return None
    return f"Spending has nothing to show before {calendar.month_name[first.month]} {first.year}."


def _name(ctx: BookContext, user_id: int | None) -> str | None:
    return names_of(ctx.people, mid=True).get(user_id) if user_id is not None else None


def _targets(db: Session, ctx: BookContext) -> dict:
    body = svc.targets_view(db, deps.today())
    body["updated_by"] = _name(ctx, body.pop("updated_by_id"))
    return body


@router.get("")
def get_month(month: str | None = None, db: Session = Depends(book_db)):
    t = deps.today()
    chosen = _month(month, t)
    earliest = svc.earliest_month(db)
    refusal = _before_history(chosen, t.replace(day=1), earliest)
    if refusal:
        raise bad(refusal, 404)
    return svc.month_view(db, t, chosen, earliest=earliest)


@router.get("/flow")
def get_flow(months: str = "12", db: Session = Depends(book_db)):
    """Home's "this month so far" strip, by Spending's rules (services.spending.flow_view)."""
    if not (months.isascii() and months.isdigit()) or not 1 <= int(months) <= 24:
        raise bad(BAD_FLOW_SPAN)
    return svc.flow_view(db, deps.today(), int(months))


@router.get("/trends")
def get_trends(months: str = "12", db: Session = Depends(book_db)):
    if months not in ("6", "12"):
        raise bad(BAD_SPAN)
    return svc.trends_view(db, deps.today(), int(months))


@router.get("/targets")
def get_targets(db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    return _targets(db, ctx)


@router.put("/targets")
def put_targets(body: dict = Depends(json_object), db: Session = Depends(book_db),
                ctx: BookContext = Depends(open_book)):
    """Parse, save what changed and commit once, in the request's IMMEDIATE session, so two saves run one after the
    other. A refusal writes nothing. A "prefs" key is ignored (P17)."""
    try:
        targets = svc.parse_targets(body)
    except svc.TargetsError as e:
        raise bad(str(e)) from None
    svc.save_targets(db, targets, user_id=ctx.user_id, who=_name(ctx, ctx.user_id) or "Someone", at=deps.now())
    db.commit()
    return _targets(db, ctx)


@router.post("/targets/{category}/check")
def answer_check(category: str, body: dict = Depends(json_object), db: Session = Depends(book_db),
                 ctx: BookContext = Depends(open_book)):
    """The monthly target check (P19): Set writes the typical month, Keep sets check_after. One Undo each."""
    answer, seen = body.get("answer"), body.get("target_cents")
    if answer not in ("set", "keep") or isinstance(seen, bool) or not isinstance(seen, int):
        raise bad(svc.NOT_UNDERSTOOD)
    t, who = deps.today(), _name(ctx, ctx.user_id) or "Someone"
    try:
        row, typical = svc.check_target(db, t, category, seen)
    except svc.TargetChanged as e:
        raise bad(str(e), 409) from None
    except svc.TargetsError as e:
        raise bad(str(e), 404) from None
    until = None
    with capturing(db, ctx.user_id, "target_check", deps.now()) as cap:
        if answer == "set":
            svc.save_targets(db, [(category, "everyday", typical)], user_id=ctx.user_id, who=who, at=deps.now())
        else:
            until = svc.keep_target(db, row, t, who=who).isoformat()
    db.commit()
    return {"target_cents": typical if answer == "set" else seen, "until": until, "undo": cap.token}


@router.delete("/targets/{category}/kept")
def check_again(category: str, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Kept targets' Check again (P20): clears check_after, with Undo."""
    row = db.get(SpendingTarget, category) if category in svc.DEFAULT_KINDS else None
    if row is None or row.check_after is None:
        raise bad(svc.NOT_KEPT, 404)
    with capturing(db, ctx.user_id, "target_check", deps.now()) as cap:
        svc.check_again(db, category, who=_name(ctx, ctx.user_id) or "Someone")
    db.commit()
    return {"undo": cap.token}


@router.put("/kinds/{category}")
def put_kind(category: str, body: dict = Depends(json_object), db: Session = Depends(book_db),
             ctx: BookContext = Depends(open_book)):
    """The category page's kind select (spec, Kinds; P12): saves at once, with one Undo."""
    if category not in svc.DEFAULT_KINDS:
        raise bad(svc.NOT_A_CATEGORY, 404)
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in svc.KINDS:
        raise bad(svc.BAD_KIND)
    with capturing(db, ctx.user_id, "kind", deps.now()) as cap:
        svc.set_kind(db, category, kind, user_id=ctx.user_id, who=_name(ctx, ctx.user_id) or "Someone", at=deps.now())
    db.commit()
    return {"category": category, "kind": kind, "undo": cap.token}
