"""Growth toward an oak (phase 17 spec 3.4): five milestones worked out from the book's own data with no new tracking,
and the stage, the count of milestones met, kept as a high-water mark in the fact growth.stage so the tree never
shrinks. The answer is counts, keys and a month only: no amount, name or note leaves here. (services/growth.py is the investment
page's year, unrelated.)"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from steward.db.engine import begin_write
from steward.db.models import Fact, Transaction
from steward.services import setasides
from steward.services.plan_inputs import missing, setup_items
from steward.services.review import waiting_filter

STAGE_KEY = "growth.stage"
MILESTONES = ("first_month", "covered", "checklist", "year", "five_years")
MAX_STAGE = len(MILESTONES)
YEAR_DAYS = 365
FIVE_YEAR_DAYS = 5 * 365 + 1          # five years hold at least one leap day
NOTE = "Growth toward an oak (phase 17): the highest stage reached."


def sorted_month(db: Session, today: date, now: datetime) -> str | None:
    """1. The newest calendar month before this one ("2026-09") with at least one transaction (transfers aside) and
    none still waiting: every row has a category, or someone looked and chose Ignore. None while anything waits in
    Review (#33): the line naming the month never shows beside "1 to sort in Review"."""
    if db.scalar(select(Transaction.id).where(waiting_filter(now)).limit(1)) is not None:
        return None
    month = func.strftime("%Y-%m", Transaction.posted_at)
    waiting = func.sum(case((and_(Transaction.category == "uncategorized", Transaction.reviewed_at.is_(None)), 1), else_=0))
    q = (select(month).where(Transaction.is_transfer.is_(False), Transaction.posted_at < today.replace(day=1))
         .group_by(month).having(waiting == 0).order_by(month.desc()).limit(1))
    return db.scalar(q)


def set_aside_covered(db: Session, today: date) -> bool:
    """2. The first set-aside covered before it's due: one linked to an account that covers its next installment
    strictly before the due date (setasides.standings), so the milestone and Home's moment agree (preflight F5).
    Steward has no Plan goals, so the spec's "or goal funded" falls away (orchestrator ruling R1)."""
    for st in setasides.standings(db, today).values():
        if (st.balance is not None and st.paid is None and st.next_due is not None and st.next_due > today
                and st.installment > 0 and st.put_away >= st.installment):
            return True
    return False


def checklist_done(db: Session, today: date) -> bool:
    """3. The Plan checklist complete: every required setup item done (6 of 6, or 7 of 7 with a mortgage)."""
    return not missing(setup_items(db, today))


def history_days(db: Session, today: date) -> int:
    first = db.scalar(select(func.min(Transaction.posted_at)))
    return 0 if first is None else (today - first).days


def milestones(db: Session, today: date, now: datetime) -> list[dict]:
    """4 and 5: a year (365 days) and five years of history, from the earliest transaction. The first month carries
    the month it names, None until it is met."""
    days = history_days(db, today)
    month = sorted_month(db, today, now)
    met = {"first_month": month is not None, "covered": set_aside_covered(db, today),
           "checklist": checklist_done(db, today), "year": days >= YEAR_DAYS, "five_years": days >= FIVE_YEAR_DAYS}
    return [{"key": k, "met": met[k], **({"month": month} if k == "first_month" else {})} for k in MILESTONES]


def stored_stage(db: Session) -> int:
    """The high-water mark: the largest growth.stage fact from 0 to 5. A value that isn't a whole number in that range
    (an older backup's, a hand-added row) is ignored."""
    best = 0
    for v in db.scalars(select(Fact.value).where(Fact.key == STAGE_KEY)):
        if v.isdigit() and int(v) <= MAX_STAGE:
            best = max(best, int(v))
    return best


def raise_stage(db: Session, met: int, today: date) -> int:
    """The stage: the mark, raised to `met` when that is higher. Only a rise writes, and it takes the write lock first
    and reads the mark again, so two requests at once write it once (a GET's read session: begin_write)."""
    have = stored_stage(db)
    if met <= have:
        return have
    begin_write(db)
    have = stored_stage(db)
    if met <= have:
        return have
    db.add(Fact(key=STAGE_KEY, value=str(min(met, MAX_STAGE)), as_of=today, note=NOTE))
    db.commit()
    return min(met, MAX_STAGE)


def growth_view(db: Session, today: date, now: datetime, seen: int | None) -> dict:
    """GET /growth: the stage, the milestones and whether the person asking has seen this stage (`seen` is their
    membership's mark). Stage 0 has nothing to show, so it counts as seen."""
    ms = milestones(db, today, now)
    stage = raise_stage(db, sum(m["met"] for m in ms), today)
    return {"stage": stage, "milestones": ms, "seen": stage == 0 or (seen is not None and seen >= stage)}
