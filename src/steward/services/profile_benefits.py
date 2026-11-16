"""Social Security and Medicare in Profile (profile spec, P24-P25): each person's record or Steward's estimate and what
it gives at 67 from earnings so far, and what health insurance costs before and after 65."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import SsEarnings
from steward.engine import social_security as ss
from steward.engine.inputs import Person
from steward.engine.tax import rules
from steward.services.plan_inputs import SUGGESTED_HEALTH_PREMIUM_CENTS, latest_facts

AT = 67


def _record(db: Session, person: str) -> tuple[tuple[int, int], ...]:
    return tuple(db.execute(select(SsEarnings.year, SsEarnings.earnings_cents)
                            .where(SsEarnings.person == person).order_by(SsEarnings.year)).all())


def _born(facts, person: str) -> int | None:
    f = facts.get(f"{person}.dob")
    try:
        return date.fromisoformat(f.value).year if f else None
    except ValueError:
        return None


def _yes(facts, key: str) -> bool:
    return key in facts and facts[key].value == "yes"


def _pia(born: int, record) -> int:
    return ss.person_pia_cents(Person(born, "male", tuple(record)), start_year=0, yearly_cents=0, stop_age=0)


def benefits_out(db: Session, today: date) -> dict:
    facts = latest_facts(db)
    jr_born, sp_born = _born(facts, "jr"), _born(facts, "spouse")
    salary = int(facts["jr.salary_cents"].value) if "jr.salary_cents" in facts else None
    jr_rec = _record(db, "jr")
    jr_source = "record" if jr_rec else "estimate" if _yes(facts, "jr.ss_estimate") else "none"
    if jr_source == "estimate" and jr_born is not None and salary is not None:
        jr_rec = ss.estimated_record(jr_born, salary, today.year)
    jr_pia = _pia(jr_born, jr_rec) if jr_born is not None and jr_rec else None
    sp_rec = _record(db, "spouse")
    sp_source = "record" if sp_rec else "estimate" if _yes(facts, "spouse.ss_estimate") else "none"
    if sp_source == "record" and sp_born is not None:
        sp_67 = ss.monthly_benefit_cents(_pia(sp_born, sp_rec), AT, sp_born)
    elif sp_source == "estimate" and sp_born is not None and jr_pia is not None:
        sp_67 = ss.spousal_benefit_cents(jr_pia, AT, sp_born)        # P24: the spousal benefit alone
    else:
        sp_67 = None
    medicare = rules.table("medicare", today.year)

    def person(source, rec, at_67):
        years = [y for y, _ in rec] if source != "none" else []
        return {"source": source, "years": len(years), "first": years[0] if years else None,
                "last": years[-1] if years else None, "at_67_cents": at_67}

    premium = facts.get("health.premium_cents")
    return {
        "jr": person(jr_source, jr_rec, ss.monthly_benefit_cents(jr_pia, AT, jr_born) if jr_pia is not None else None),
        "spouse": person(sp_source, sp_rec if sp_source == "record" else (), sp_67),
        "health": {"premium_cents": int(premium.value) if premium else None,
                   "suggested_cents": SUGGESTED_HEALTH_PREMIUM_CENTS,
                   "part_b_monthly_cents": round(medicare["part_b_monthly"] * 100), "rules_year": medicare.year},
    }
