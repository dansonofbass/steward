"""Reimbursable spec, How the money counts: a reimbursable charge and a repayment leave every personal figure at once
(rule 1), and a settled leftover counts as spending in its category and household month (rule 2), pinned against each
consumer: Spending's month, Home's strip, the Cash flow page, the Plan's derive_flows and Ask's tools."""
from datetime import date, datetime, timezone

import pytest

from steward.db.models import ReimburseSettlement, Reimburser
from steward.services import spending as sp
from steward.services.cashflow import cashflow
from steward.services.vault_flows import derive_flows, settlements_by_month
from steward_boundary import tools as T
from tests.advisor.helpers import call
from tests.factories import make_account, make_txn, make_user

TODAY = date(2026, 10, 13)
SEP, OCT = date(2026, 9, 1), date(2026, 10, 1)


@pytest.fixture
def book(db):
    acme = Reimburser(name="Acme")
    db.add(acme)
    db.commit()
    chk, card = make_account(db, "Checking"), make_account(db, "Card", type="credit")
    make_txn(db, chk, date(2026, 9, 1), 500_000, "PAYROLL", category="income")
    make_txn(db, card, date(2026, 9, 5), -10_000, "GREENLEAF MARKET", category="groceries")
    hotel = make_txn(db, card, date(2026, 9, 8), -40_000, "HILTON CHICAGO IL", category="travel")
    back = make_txn(db, chk, date(2026, 9, 25), 30_000, "ACME CORP EXP", category="reimbursement")
    hotel.reimburser_id = back.reimburser_id = acme.id
    # 05:00 UTC on Oct 1 is 10 pm on Sep 30 at home: September's.
    db.add(ReimburseSettlement(reimburser_id=acme.id, amount_cents=6_000, category="travel",
                               settled_at=datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)))
    db.commit()
    return acme


def test_settlements_count_in_the_households_month(db, book):
    assert settlements_by_month(db, SEP, OCT) == {"2026-09": {"travel": 6_000}}
    assert settlements_by_month(db, OCT, date(2026, 11, 1)) == {}


def test_spendings_month_leaves_out_the_charge_and_the_repayment_and_counts_the_settlement(db, book):
    sums = sp.category_months(db, SEP, OCT)["2026-09"]
    assert "reimbursement" not in sums and sums["travel"] == sp.Flow(0, 6_000, 0)
    assert sums["groceries"].out_cents == 10_000 and sums["income"].in_cents == 500_000
    head = sp.month_view(db, TODAY, SEP)["head"]
    assert (head["money_out_cents"], head["income_cents"]) == (16_000, 500_000)


def test_homes_strip_agrees(db, book):
    sep = next(m for m in sp.flow_view(db, TODAY, 2)["months"] if m["month"] == "2026-09")
    assert (sep["in_cents"], sep["out_cents"]) == (500_000, 16_000)


def test_the_cash_flow_page_leaves_both_out_and_has_no_settlement(db, book):
    """Engineering choice 24: settlements are not transactions (cashflow() is Care's month by month)."""
    sep = next(m for m in cashflow(db, TODAY, 2) if m["month"] == "2026-09")
    assert (sep["in_cents"], sep["out_cents"]) == (500_000, 10_000)
    assert {c["category"] for c in sep["categories"]} == {"income", "groceries"}


def test_the_plan_counts_the_settlement_and_never_the_repayment(db, book):
    f = derive_flows(db, TODAY)
    assert (f.months, f.money_in_cents, f.money_out_cents) == (1, 500_000, 16_000)


def test_derive_flows_skips_a_repayment_even_with_no_payer_yet(db):
    """Rule 1's pin in derive_flows itself: a Reimbursement row with no payer (two payers, none chosen) is still not
    money in."""
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 9, 1), 500_000, "PAYROLL", category="income")
    make_txn(db, chk, date(2026, 9, 25), 30_000, "ACME CORP EXP", category="reimbursement")
    assert derive_flows(db, TODAY).money_in_cents == 500_000


def test_asks_tools_leave_both_out(db, book, books, ours, engine):
    make_user(db)
    people = books.people(ours.id)
    ask = lambda name, inp: call(engine, ours, people, people[0].id, name, inp, TODAY)
    out = ask("spending_by_category", {"start": "2026-09-01", "end": "2026-09-30", "compare_previous": False})
    assert out["error"] is None
    assert out["content"]["period"]["total_out_cents"] == 10_000
    assert [c["category"] for c in out["content"]["period"]["categories"]] == ["groceries"]
    sep = next(m for m in ask("cash_flow", {"months": 2, "by": "category"})["content"]["months"] if m["month"] == "2026-09")
    # cash_flow is Spending's month: the settled $60 leftover counts as Travel spending, as it does on Spending.
    assert (sep["in_cents"], sep["out_cents"]) == (500_000, 16_000)
    assert {g["category"]: g["out_cents"] for g in sep["groups"]} == {"groceries": 10_000, "travel": 6_000, "income": 0}


def test_the_tools_say_what_they_leave_out():
    for name in ("cash_flow", "spending_by_category"):
        assert "reimbursable work expenses and their repayments are left out" in T.BY_NAME[name].description.lower()
    assert "settled" in T.BY_NAME["spending_by_category"].description
