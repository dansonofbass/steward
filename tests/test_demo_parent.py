from collections import Counter
from datetime import date

from sqlalchemy import func, select

from steward.db.models import InventoryItem, Transaction
from steward.demo_parent import seed_parent
from steward.inventory.overview import overview
from steward.inventory.views import load

TODAY = date(2026, 10, 18)
OWNERS = {"margaret": "Margaret", "robert-husband": "Robert (husband)", "joint": "Joint"}


def test_margaret_matches_the_mockups(margaret, mdb, mctx):
    ids = seed_parent(mdb, TODAY, by=mctx.user_id)
    assert len(ids) == 18
    statuses = Counter(mdb.scalars(select(InventoryItem.status)))
    assert statuses == {"confirmed": 15, "needs_checking": 2, "closed": 1}
    out = overview(mdb, load(mdb, OWNERS), TODAY)
    assert out["net_worth_cents"] == 118_046_225
    assert out["counted_line"] == "From 7 of Margaret's 8 accounts. The Westmark Life annuity has no balance yet."
    assert out["fresh_line"] == "Bank feed updated today, 6:10 AM · statements through Sep 30"
    assert [(t["key"], t["cents"], t["note"]) for t in out["totals"]] == [
        ("cash", 7_069_465, "3 accounts"), ("investments", 14_260_000, "1 account"),
        ("retirement", 18_835_000, "2 accounts, 1 with no balance"), ("property", 78_000_000, "House, estimate"),
        ("debts", -118_240, "1 credit card")]
    assert out["incoming"]["monthly_cents"] == 352_500 and out["outgoing"]["monthly_cents"] == 37_207
    assert out["needs_checking"]["labels"] == ["Westmark Life annuity", "Evergreen Mutual long-term care"]


def test_deposits_follow_the_2026_calendar(margaret, mdb):
    seed_parent(mdb, TODAY)
    ss = sorted(mdb.scalars(select(Transaction.posted_at).where(Transaction.raw_description == "SSA TREAS 310 XXSOC SEC")))
    assert ss[-3:] == [date(2026, 8, 3), date(2026, 9, 3), date(2026, 10, 2)]      # Oct 3 is a Saturday
    westmark = sorted(mdb.scalars(select(Transaction.posted_at).where(Transaction.raw_description.like("WESTMARK%"))))
    assert westmark == [date(2026, 7, 15), date(2026, 8, 14), date(2026, 9, 15), date(2026, 10, 15)]
    globe = sorted(mdb.scalars(select(Transaction.posted_at).where(Transaction.raw_description.like("GLOBE%"))))
    assert globe == [date(2026, 7, 15), date(2026, 8, 17), date(2026, 9, 15), date(2026, 10, 15)]
    assert mdb.scalar(select(func.count()).select_from(Transaction).where(Transaction.posted_at > TODAY)) == 0
