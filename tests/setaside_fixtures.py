"""A household for the set-aside tests, seen on October 25, 2026 (web/mockups/setasides.js): Property tax twice a
year from House fund ••2210 (with Water heater and Roof on the same account), Summer camps from Kids fund, Holidays,
Car registration and Car insurance with no account. The county's three past payments are in the book; the April one
counts from May. Figures are made up."""
from datetime import date, datetime, timezone

from steward.db.models import BalanceSnapshot, SetAside
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 25)
AT = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)
FIRST = date(2026, 11, 1)
HEATER_ESTIMATE = ('{"item": "water_heater", "installed_year": 2014, "model_year": null, "miles": null, '
                   '"lifespan": [10, 15], "cost_range": [150000, 300000], "planned_year": 2028, '
                   '"replacement_cents": 220000, "sale_cents": 0, "confirmed": false}')


def household(db) -> dict:
    chk = make_account(db, "Checking")
    house = make_account(db, "House fund", type="savings")
    kids = make_account(db, "Kids fund", type="savings")
    db.add_all([BalanceSnapshot(account_id=house.id, as_of=date(2026, 10, 24), balance_cents=410_000),
                BalanceSnapshot(account_id=kids.id, as_of=date(2026, 10, 24), balance_cents=60_000)])
    for d, cents in ((date(2025, 4, 9), 418_000), (date(2025, 11, 3), 421_000), (date(2026, 4, 10), 421_000)):
        make_txn(db, chk, d, -cents, "COUNTY TAX COLLECTOR", merchant="County Tax Collector", category="taxes")
    make_txn(db, chk, date(2026, 6, 15), -240_000, "CAMP SUNRISE", merchant="Camp Sunrise", category="kids")
    rows = {
        "proptax": SetAside(name="Property tax", kind="twice_yearly", amount_cents=421_000, due_month=11, due_day=1,
                            second_month=4, second_day=10, first_month=FIRST, account_id=house.id,
                            payee_key="COUNTY TAX COLLECTOR", category="taxes"),
        "holidays": SetAside(name="Holidays", kind="yearly", amount_cents=150_000, due_month=12, due_day=1, first_month=FIRST),
        "carreg": SetAside(name="Car registration", kind="yearly", amount_cents=41_200, due_month=3, due_day=1, first_month=FIRST),
        "camps": SetAside(name="Summer camps", kind="yearly", amount_cents=240_000, due_month=6, due_day=1, first_month=FIRST,
                          account_id=kids.id),
        "carins": SetAside(name="Car insurance", kind="yearly", amount_cents=186_000, due_month=8, due_day=14, first_month=FIRST,
                           payee_key="SAFEGUARD INSURANCE", category="insurance"),
        "heater": SetAside(name="Water heater", kind="one_off", amount_cents=220_000, due_year=2028, due_month=12, first_month=FIRST,
                           account_id=house.id, estimate=HEATER_ESTIMATE),
        "roof": SetAside(name="Roof", kind="one_off", amount_cents=1_800_000, due_year=2032, due_month=12, first_month=FIRST,
                         account_id=house.id, estimate=HEATER_ESTIMATE.replace('"water_heater"', '"roof"').replace("2028", "2032")),
    }
    for sa in rows.values():
        sa.created_at = sa.updated_at = AT
        sa.updated_by = 1
    db.add_all(rows.values())
    db.commit()
    return {"accounts": {"checking": chk, "house": house, "kids": kids}, **rows}
