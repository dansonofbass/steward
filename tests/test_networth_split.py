"""The net worth split (investment views spec, Net worth): Investable, Home and cars, What you owe, Business, and the
accounts nobody typed yet, so the lines always add up to net worth."""
from datetime import date

from steward.db.models import AccountType
from steward.services.accounts import record_balance
from steward.services.networth import SPLIT, history_with_investable, net_worth_on, split_on
from tests.factories import make_account


def test_the_split_adds_up_to_net_worth_with_business_and_an_untyped_account(db):
    """Review Focus 5."""
    day = date(2026, 10, 1)
    rows = {"Checking": ("checking", 10_000_00), "Brokerage": ("brokerage_taxable", 50_000_00), "401(k)": ("k401", 100_000_00),
            "529": ("plan529", 5_000_00), "Home": ("property", 500_000_00), "Subaru": ("vehicle", 20_000_00),
            "Mortgage": ("mortgage", -300_000_00), "Car loan": ("loan", -9_800_00), "Card": ("credit", -1_000_00),
            "Biz checking": ("business_checking", 3_000_00), "Biz card": ("business_credit", -500_00),
            "New account": ("unknown", 2_000_00)}
    ids = {}
    for name, (t, cents) in rows.items():
        a = make_account(db, name, type=t)
        ids[name] = a.id
        record_balance(db, a.id, day, cents)
    db.commit()
    s = split_on(db, date(2026, 10, 13))
    assert {k: v["cents"] for k, v in s.items()} == {"investable": 165_000_00, "home_and_cars": 520_000_00,
                                                      "owed": -310_800_00, "business": 2_500_00, "unset": 2_000_00}
    assert sum(v["cents"] for v in s.values()) == net_worth_on(db, date(2026, 10, 13))
    assert s["home_and_cars"]["account_ids"] == sorted([ids["Home"], ids["Subaru"]])


def test_every_account_type_is_in_exactly_one_line():
    seen = [t for types in SPLIT.values() for t in types]
    assert len(seen) == len(set(seen)) and set(seen) == set(AccountType)


def test_the_history_carries_the_investable_part(db):
    chk = make_account(db, "Checking")
    home = make_account(db, "Home", type="property")
    brk = make_account(db, "Brokerage", type="brokerage_taxable")
    record_balance(db, chk.id, date(2026, 10, 1), 10_000_00)
    record_balance(db, home.id, date(2026, 10, 1), 500_000_00)
    record_balance(db, brk.id, date(2026, 10, 2), 5_000_00)
    db.commit()
    assert history_with_investable(db, date(2026, 10, 1), date(2026, 10, 2)) == [
        (date(2026, 10, 1), 510_000_00, 10_000_00), (date(2026, 10, 2), 515_000_00, 15_000_00)]


def test_the_summary_has_the_split_and_this_years_change(frozen, signed_in, db):
    chk = make_account(db, "Checking")
    record_balance(db, chk.id, date(2025, 12, 31), 8_000_00)
    record_balance(db, chk.id, date(2026, 10, 1), 10_000_00)
    db.commit()
    s = signed_in.get("/api/b/ours/summary").json()
    assert (s["change_year_cents"], s["year_start"]) == (2_000_00, "2026-01-01")
    assert s["split"]["investable"] == {"cents": 10_000_00, "account_ids": [chk.id]}
    assert s["split"]["business"] == {"cents": 0, "account_ids": []}
    h = signed_in.get("/api/b/ours/summary/history?days=2").json()["points"]
    assert h[-1] == {"date": "2026-10-13", "net_worth_cents": 10_000_00, "investable_cents": 10_000_00}


def test_without_a_balance_from_last_year_there_is_no_change_this_year(frozen, signed_in, db):
    chk = make_account(db, "Checking")
    record_balance(db, chk.id, date(2026, 3, 1), 10_000_00)
    db.commit()
    assert signed_in.get("/api/b/ours/summary").json()["change_year_cents"] is None
