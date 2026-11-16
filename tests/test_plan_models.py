from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from steward.db.models import AssetClass, Child, Plan, SsEarnings
from tests.factories import make_account, make_user

T = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def test_plan_rows_round_trip(db):
    u = make_user(db)
    db.add(Plan(saved_at=T, saved_by=u.id, levers='{"assumed": {}}', engine_version="2026.10.2", comfortable_age=61, likely_age=None))
    db.add(AssetClass(symbol="VTI", asset_class="us_stock"))
    db.commit()
    p = db.query(Plan).one()
    assert p.saved_at == T and p.likely_age is None and p.levers == '{"assumed": {}}'
    assert db.get(AssetClass, "VTI").source == "override"


def test_earnings_are_unique_per_person_and_year(db):
    db.add(SsEarnings(person="jr", year=2020, earnings_cents=5_000_000, imported_at=T))
    db.commit()
    db.expunge_all()
    db.add(SsEarnings(person="jr", year=2020, earnings_cents=1, imported_at=T))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("row", [
    lambda: SsEarnings(person="cousin", year=2020, earnings_cents=1, imported_at=T),
    lambda: AssetClass(symbol="GLD", asset_class="gold"),
    lambda: Child(label="Oldest", birth_year=2015, cost_level="ivy", monthly_contribution_cents=0),
])
def test_check_constraints_refuse_unknown_values(db, row):
    db.add(row())
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_529_belongs_to_one_child(db):
    a = make_account(db, "529", type="plan529")
    db.add(Child(label="Oldest", birth_year=2015, cost_level="private", account_id=a.id, monthly_contribution_cents=0))
    db.commit()
    db.add(Child(label="Middle", birth_year=2018, cost_level="private", account_id=a.id, monthly_contribution_cents=0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
