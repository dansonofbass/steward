from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from steward.db.models import COLLEGE_COST_LEVELS, PROFILE_SECTIONS, STEP_STATUSES, Child, SetupStep, UserSetup
from tests.factories import make_user

T = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def test_the_section_keys_levels_and_answers():
    assert PROFILE_SECTIONS == ("you", "kids", "home", "benefits", "banks")
    assert COLLEGE_COST_LEVELS == ("two_year", "in_state_public", "out_of_state_public", "private", "not_sure")
    assert STEP_STATUSES == ("done", "skipped", "doesnt_apply")


def test_rows_round_trip(db):
    uid = make_user(db).id
    db.add(SetupStep(step="home", status=None, user_id=uid, at=T, resume_step="mortgages"))
    db.add(UserSetup(user_id=uid, seen_at=T, later_until=T))
    db.add(Child(label="Ava", birth_year=2015, cost_level="two_year", monthly_contribution_cents=0))
    db.commit()
    db.expunge_all()
    row = db.get(SetupStep, "home")
    assert (row.status, row.resume_step) == (None, "mortgages")
    assert db.get(UserSetup, uid).later_until == T
    kid = db.query(Child).one()
    assert (kid.share_pct, kid.covers_living, kid.removed_at) == (100, True, None)


@pytest.mark.parametrize("row", [
    SetupStep(step="about", status="done", user_id=1, at=T),
    SetupStep(step="kids", status="maybe", user_id=1, at=T),
    Child(label="A", birth_year=2015, cost_level="ivy", monthly_contribution_cents=0),
    Child(label="A", birth_year=2015, cost_level="private", monthly_contribution_cents=0, share_pct=55),
    Child(label="A", birth_year=2015, cost_level="private", monthly_contribution_cents=0, share_pct=110),
])
def test_check_constraints_refuse_unknown_values(db, row):
    db.add(row)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
