from datetime import datetime, timezone

from steward.db.models import SsEarnings
from steward.engine import social_security as ss
from steward.engine.inputs import Person
from tests.factories import add_fact

T = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_each_persons_record_estimate_or_nothing_with_the_benefit_at_67(frozen, signed_in, db):
    add_fact(db, "jr.dob", "1982-05-01")
    add_fact(db, "spouse.dob", "1984-08-01")
    add_fact(db, "jr.salary_cents", "16000000")
    body = signed_in.get("/api/b/ours/profile/benefits").json()
    assert body["jr"] == {"source": "none", "years": 0, "first": None, "last": None, "at_67_cents": None}
    assert body["spouse"]["at_67_cents"] is None
    add_fact(db, "jr.ss_estimate", "yes")
    add_fact(db, "spouse.ss_estimate", "yes")
    body = signed_in.get("/api/b/ours/profile/benefits").json()
    assert (body["jr"]["source"], body["jr"]["first"], body["jr"]["last"], body["jr"]["years"]) == ("estimate", 2004, 2025, 22)
    pia = ss.person_pia_cents(Person(1982, "male", ss.estimated_record(1982, 16_000_000, 2026)),
                              start_year=0, yearly_cents=0, stop_age=0)
    assert body["jr"]["at_67_cents"] == ss.monthly_benefit_cents(pia, 67, 1982)          # earnings so far only (P25)
    assert (body["spouse"]["source"], body["spouse"]["years"]) == ("estimate", 0)
    assert body["spouse"]["at_67_cents"] == ss.spousal_benefit_cents(pia, 67, 1984)       # the spousal benefit alone
    db.add_all([SsEarnings(person="jr", year=y, earnings_cents=6_000_000, imported_at=T) for y in range(2000, 2026)])
    db.commit()
    jr = signed_in.get("/api/b/ours/profile/benefits").json()["jr"]
    assert (jr["source"], jr["years"], jr["first"], jr["last"]) == ("record", 26, 2000, 2025)   # a record replaces it


def test_health_carries_the_premium_the_estimate_and_part_b(frozen, signed_in, db):
    h = signed_in.get("/api/b/ours/profile/benefits").json()["health"]
    assert (h["premium_cents"], h["suggested_cents"], h["rules_year"]) == (None, 1_680_000, 2026)
    assert h["part_b_monthly_cents"] > 0
    add_fact(db, "health.premium_cents", "2400000")
    assert signed_in.get("/api/b/ours/profile/benefits").json()["health"]["premium_cents"] == 2_400_000
