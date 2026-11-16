"""The Plan's side of set-asides (spec, The Plan): one_off_costs from the active, unpaid one-offs, summed by year;
the note for the page; and GET /plan carrying it."""
from datetime import date

from steward.db.models import SetAside, SetAsideMatch
from steward.engine.inputs import OneOffCost
from steward.services import setasides as sas
from steward.services.plan_inputs import build_inputs
from tests.factories import make_ready_household, make_txn, make_user
from tests.setaside_fixtures import AT, household

TODAY = date(2026, 10, 13)


def test_one_off_costs_are_the_active_unpaid_one_offs_summed_by_year(db):
    h = household(db)
    assert sas.one_off_costs(db, 2026) == (OneOffCost(2028, 220_000), OneOffCost(2032, 1_800_000))
    db.add(SetAside(name="Car", kind="one_off", amount_cents=2_156_000, due_year=2032, due_month=12, first_month=date(2026, 11, 1),
                    created_at=AT, updated_at=AT))
    db.commit()
    assert sas.one_off_costs(db, 2026) == (OneOffCost(2028, 220_000), OneOffCost(2032, 3_956_000))
    assert sas.one_off_costs(db, 2030) == (OneOffCost(2030, 220_000), OneOffCost(2032, 3_956_000))   # the heater is overdue: it counts in the plan year
    h["roof"].archived_at = AT
    bill = make_txn(db, h["accounts"]["checking"], date(2026, 10, 1), -230_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    db.add(SetAsideMatch(transaction_id=bill.id, set_aside_id=h["heater"].id, due_on=date(2028, 12, 1), how="hand", late=False, created_at=AT))
    db.commit()
    assert sas.one_off_costs(db, 2026) == (OneOffCost(2032, 2_156_000),)                 # archived and paid are gone
    note = sas.plan_one_offs(db, 2026)
    assert note == [{"id": sas.active(db)[-1].id, "name": "Car", "year": 2032, "due_year": 2032, "due_month": 12, "overdue": False, "cents": 2_156_000, "monthly_cents": 29_135, "is_estimate": False}]


def test_build_inputs_carries_the_one_offs_and_the_note(db):
    make_user(db)
    make_ready_household(db)
    pi = build_inputs(db, TODAY)
    assert pi.household.one_off_costs == () and pi.set_asides.one_offs == () and pi.set_asides.updated_at is None
    db.add(SetAside(name="Water heater", kind="one_off", amount_cents=225_000, due_year=2028, due_month=12, first_month=date(2026, 11, 1),
                    estimate='{"item": "water_heater", "installed_year": 2014, "model_year": null, "miles": null, "lifespan": [10, 15], '
                             '"cost_range": [150000, 300000], "planned_year": 2028, "replacement_cents": 225000, "sale_cents": 0, "confirmed": false}',
                    created_at=AT, updated_at=AT, updated_by=1))
    db.add(SetAside(name="Car insurance", kind="yearly", amount_cents=186_000, due_month=8, due_day=14, first_month=date(2026, 11, 1),
                    created_at=AT, updated_at=AT, updated_by=1))
    db.commit()
    pi = build_inputs(db, TODAY)
    assert pi.household.one_off_costs == (OneOffCost(2028, 225_000),)
    assert pi.set_asides.yearly_count == 1 and pi.set_asides.updated_at == AT.isoformat() and pi.set_asides.updated_by == "JR"
    assert pi.set_asides.one_offs == ({"id": pi.set_asides.one_offs[0]["id"], "name": "Water heater", "year": 2028, "due_year": 2028, "due_month": 12, "overdue": False, "cents": 225_000,
                                       "monthly_cents": 8_654, "is_estimate": True},)


def test_get_plan_exposes_the_big_costs(frozen, signed_in, db):
    make_ready_household(db)
    db.add(SetAside(name="Roof", kind="one_off", amount_cents=1_800_000, due_year=2032, due_month=12, first_month=date(2026, 11, 1),
                    created_at=AT, updated_at=AT, updated_by=1))
    db.commit()
    body = signed_in.get("/api/b/ours/plan").json()
    assert body["inputs"]["set_asides"] == {"updated_at": AT.isoformat(), "updated_by": "JR", "yearly_count": 0,
                                            "one_offs": [{"id": 1, "name": "Roof", "year": 2032, "due_year": 2032, "due_month": 12, "overdue": False, "cents": 1_800_000, "monthly_cents": 24_324, "is_estimate": False}]}
    assert body["result"]["engine_version"] == "2026.10.5"


def test_an_overdue_unpaid_one_off_carries_into_the_plan_year(db):
    db.add_all([SetAside(name="Roof", kind="one_off", amount_cents=1_800_000, due_year=2025, due_month=3, first_month=date(2025, 1, 1),
                         created_at=AT, updated_at=AT),
                SetAside(name="Fence", kind="one_off", amount_cents=100_000, due_year=2026, due_month=12, first_month=date(2025, 1, 1),
                         created_at=AT, updated_at=AT)])
    db.commit()
    assert sas.one_off_costs(db, 2026) == (OneOffCost(2026, 1_900_000),)                 # summed with the cost already due that year
    rows = sas.plan_one_offs(db, 2026)
    assert [(r["name"], r["year"], r["due_year"], r["due_month"], r["overdue"]) for r in rows] == [("Roof", 2026, 2025, 3, True), ("Fence", 2026, 2026, 12, False)]
