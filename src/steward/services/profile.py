"""Profile (profile and household spec): the five sections' state for the household, each person's own marks, and
Home's line. A section whose data is complete counts as done whatever was said before; otherwise the household's last
answer stands (skipped, or doesn't apply for Kids and college only); no answer means not started. A section's row also
keeps the step its guided flow resumes at (P6), shared by the household because the data it resumes is."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.books.people import Person, names_of, people_of
from steward.db.models import (
    PROFILE_SECTIONS, Account, AccountType, SetupStep, SimplefinLink, SsEarnings, UserSetup, active_children,
)
from steward.services import home_value
from steward.services.accounts import debt_rate_bp
from steward.services.plan_inputs import (
    HOUSEHOLD_FACTS, PAY_FACTS, latest_facts, owner_names, owner_users, unclaimed_529s,
)

SECTION_STEPS: dict[str, tuple[str, ...]] = {   # Engineering choice 8; web/src/lib/profileSections.ts mirrors it
    "you": ("you", "partner", "taxes", "pay"),
    "kids": ("kids", "cover", "plans"),
    "home": ("own", "homes", "mortgages", "cars"),
    "benefits": ("ss", "health"),
    "banks": ("link", "types", "history"),
}
MINUTES = {"you": 3, "kids": 2, "home": 3, "benefits": 5, "banks": 5}   # P4
LATER = timedelta(days=7)                                                # P5
FINISHED = ("done", "doesnt_apply")
ONLY_KIDS = "Only Kids and college can be marked Doesn't apply."
KIDS_EXIST = "Doesn't apply is for a household with no kids or 529s. Remove them first, or skip this section."
STILL_NEEDED = "Still needed: {what}."
NO_SUCH_STEP = "Name one of the section's steps, or null."
assert set(SECTION_STEPS) == set(MINUTES) == set(PROFILE_SECTIONS)


class SectionRefused(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def join_words(parts: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def _active(db: Session, type: AccountType) -> bool:
    return db.scalar(select(Account.id).where(Account.is_active.is_(True), Account.type == type).limit(1)) is not None


def _has_kids_or_529(db: Session) -> bool:
    return db.scalar(active_children().limit(1)) is not None or _active(db, AccountType.plan529)


def owns_home(db: Session, facts) -> bool | None:
    """The home.owns answer; with none, a home value or an active property says yes (Engineering choice 5)."""
    f = facts.get("home.owns")
    if f is not None:
        return f.value == "yes"
    if "home.value_cents" in facts or _active(db, AccountType.property):
        return True
    return None


def missing(db: Session) -> dict[str, list[str]]:
    """What each section still needs, in plain words; an empty list means its data is complete (Completion table)."""
    facts = latest_facts(db)
    names = owner_names(db)

    def lack(*pairs: tuple[str, str]) -> list[str]:
        return [what for key, what in pairs if key not in facts]

    you = lack(("jr.dob", f"{names['jr']}'s birthday"), ("spouse.dob", f"{names['spouse']}'s birthday"),
               ("state", "the state"), ("filing_status", "the filing status"), ("jr.salary_cents", "the salary"),
               ("jr.k401_pct_bp", "the 401(k) contribution"), ("employer.match_rate_bp", "the employer match"),
               ("employer.match_cap_bp", "the match cap"))
    kids = [] if db.scalar(active_children().limit(1)) is not None else ["a kid, or No kids"]
    kids += [f"which kid {a.name} belongs to" for a in unclaimed_529s(db)]
    owns, home = owns_home(db, facts), []
    if owns is None:
        home = ["whether you own a home"]
    elif owns:
        if home_value.current_value(db) is None:
            home.append("the home's value")
        mortgage = home_value.main_mortgage(db)
        if mortgage is not None:
            if debt_rate_bp(mortgage, facts) is None:
                home.append("the mortgage's interest rate")
            home += lack(("mortgage.payment_cents", "the monthly payment"), ("mortgage.payoff_date", "the payoff date"))
    record = db.scalar(select(func.count()).select_from(SsEarnings).where(SsEarnings.person == "jr")) or 0
    estimate = facts.get("jr.ss_estimate") is not None and facts["jr.ss_estimate"].value == "yes"
    benefits = [] if record or estimate else [f"{names['jr']}'s earnings record or Steward's estimate"]
    benefits += lack(("health.premium_cents", "the health insurance premium"))
    linked = db.scalar(select(func.count()).select_from(SimplefinLink)) or 0
    banking = db.scalar(select(func.count()).select_from(Account).where(
        Account.is_active.is_(True),
        Account.type.not_in((AccountType.mortgage, AccountType.property, AccountType.vehicle)))) or 0
    banks = [] if linked or banking else ["a linked bank or an account"]
    return {"you": you, "kids": kids, "home": home, "benefits": benefits, "banks": banks}


@dataclass(frozen=True)
class SectionState:
    key: str
    status: str               # done | skipped | doesnt_apply | todo
    by_id: int | None
    by: str | None
    at: datetime | None
    resume_step: str | None
    missing: str | None       # what's still needed, in words; None when the data is complete

    def as_dict(self) -> dict:
        return {"key": self.key, "status": self.status, "minutes": MINUTES[self.key], "resume_step": self.resume_step,
                "by_id": self.by_id, "by": self.by, "at": self.at.isoformat() if self.at else None, "missing": self.missing}


def section_states(db: Session) -> list[SectionState]:
    gaps = missing(db)
    rows = {r.step: r for r in db.scalars(select(SetupStep))}
    names = names_of(people_of(db), mid=True)   # "Saved Oct 14 by {name}"
    out: list[SectionState] = []
    for key in PROFILE_SECTIONS:
        row = rows.get(key)
        what = join_words(gaps[key]) if gaps[key] else None
        resume = row.resume_step if row is not None else None
        said = row if row is not None and row.status is not None else None
        if not gaps[key]:
            done_by = said if said is not None and said.status == "done" else None
            out.append(SectionState(key, "done", done_by.user_id if done_by else None,
                                    names.get(done_by.user_id) if done_by else None, done_by.at if done_by else None,
                                    None, None))
        elif said is not None and said.status == "doesnt_apply" and _has_kids_or_529(db):
            out.append(SectionState(key, "todo", None, None, None, resume, what))   # a stale Doesn't apply
        elif said is not None and said.status in ("skipped", "doesnt_apply"):
            out.append(SectionState(key, said.status, said.user_id, names.get(said.user_id), said.at, resume, what))
        else:
            out.append(SectionState(key, "todo", None, None, None, resume, what))
    return out


def set_section(db: Session, key: str, status: str, user_id: int, at: datetime) -> None:
    """Record an answer (no commit). Done needs complete data; a skip on a section whose data is complete changes
    nothing, so the person who finished it stays on record. Done and Doesn't apply clear the resume point."""
    if status == "doesnt_apply" and key != "kids":
        raise SectionRefused(ONLY_KIDS, 422)
    if key == "kids" and status == "doesnt_apply" and _has_kids_or_529(db):
        raise SectionRefused(KIDS_EXIST, 422)
    gaps = missing(db)[key]
    if status == "done" and gaps:
        raise SectionRefused(STILL_NEEDED.format(what=join_words(gaps)), 409)
    if status != "done" and not gaps:
        return
    row = db.get(SetupStep, key)
    if row is None:
        row = SetupStep(step=key)
        db.add(row)
    row.status, row.user_id, row.at = status, user_id, at
    if status in FINISHED:
        row.resume_step = None


def set_resume(db: Session, key: str, step: str | None, user_id: int, at: datetime) -> None:
    """Record the step the section's flow resumes at (no commit); a row with no answer keeps it (Engineering choice 3)."""
    if step is not None and step not in SECTION_STEPS[key]:
        raise SectionRefused(NO_SUCH_STEP, 422)
    row = db.get(SetupStep, key)
    if row is None:
        if step is None:
            return
        row = SetupStep(step=key, status=None, user_id=user_id, at=at)
        db.add(row)
    row.resume_step = step


def marks_out(db: Session, user_id: int, now: datetime) -> dict:
    m = db.get(UserSetup, user_id)
    later = m.later_until if m is not None and m.later_until is not None and m.later_until > now else None
    return {"seen": bool(m and m.seen_at), "confirmed": bool(m and m.confirmed_at),
            "later_until": later.isoformat() if later else None}


def mark(db: Session, user_id: int, at: datetime, *, seen: bool = False, confirmed: bool = False,
         later: bool | None = None) -> None:
    """Set one person's own marks (no commit). Confirming also counts as having seen the welcome."""
    m = db.get(UserSetup, user_id)
    if m is None:
        m = UserSetup(user_id=user_id)
        db.add(m)
    if seen or confirmed:
        m.seen_at = m.seen_at or at
    if confirmed:
        m.confirmed_at = m.confirmed_at or at
    if later is not None:
        m.later_until = at + LATER if later else None


def _person(u: Person | None) -> dict | None:
    return {"user_id": u.id, "display_name": u.display_name} if u is not None else None


def profile_out(db: Session, user_id: int, now: datetime) -> dict:
    states = section_states(db)
    jr, spouse = owner_users(db)
    role = "jr" if jr is not None and jr.id == user_id else "spouse" if spouse is not None and spouse.id == user_id else None
    nxt = next((s.key for s in states if s.status not in FINISHED), None)
    return {
        "sections": [s.as_dict() for s in states],
        "done": sum(s.status in FINISHED for s in states),
        "total": len(PROFILE_SECTIONS),
        "next": nxt,
        "finished": nxt is None,
        "me": {"user_id": user_id, "role": role, **marks_out(db, user_id, now)},
        "names": owner_names(db),
        "people": {"jr": _person(jr), "spouse": _person(spouse)},
    }
