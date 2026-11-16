"""Home's "this month so far" strip by Spending's rules (a follow-up to phase 11b): its Spending and Income, and its
12 bars, are Spending's money out and income for each month, so Home and Spending never disagree about a month."""
from datetime import date

from steward.db.models import SpendingTarget
from steward.services import spending as sp
from steward.services.cashflow import cashflow
from tests.factories import make_account, make_txn
from tests.spending_fixtures import AT, TODAY, household

OCT = date(2026, 10, 1)


def _with_business(db) -> dict:
    """The Spending household, plus October's business-account rows: a personal lunch on the business account, a
    phone bill that is 40% personal, and a business-only cost."""
    accounts = household(db)
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    make_txn(db, biz, date(2026, 10, 18), -9_000, "TEAM LUNCH", category="dining", business_pct=0)
    make_txn(db, accounts["checking"], date(2026, 10, 19), -10_000, "MOBILE ONE", category="utilities", business_pct=40)
    make_txn(db, biz, date(2026, 10, 19), -7_000, "CLOUDHOST", category="business_expense")
    db.commit()
    return accounts


def test_home_and_spending_agree_on_a_month_with_a_card_payment_a_refund_and_taxes(db):
    """The month that started it. October has a $500 card payment the feed didn't pair, a $13.84 refund at Noodle
    House, $4,210 of property tax, a $5 credit not sorted yet and business rows. The old strip (cashflow()) counted
    the card payment and the refund's gross spending, and took the refund and the credit as income; the strip now
    reads Spending's money out (everyday, not sorted, fixed and paid once in a while) and Spending's income."""
    _with_business(db)
    old = cashflow(db, TODAY, 1)[-1]
    strip = sp.flow_view(db, TODAY, 12)["months"][-1]
    assert strip == {"month": "2026-10", "in_cents": 1_025_400, "out_cents": 950_799, "net_cents": 74_601}
    head = sp.month_view(db, TODAY, OCT)["head"]
    assert (head["money_in_cents"], head["money_out_cents"]) == (strip["in_cents"], strip["out_cents"])
    # Spending's own parts add up to it: the plan figure (everyday with Not sorted yet, and fixed costs) and taxes.
    assert head["spent_cents"] + head["occasional_cents"] == strip["out_cents"]
    assert (head["spent_cents"], head["occasional_cents"]) == (529_799, 421_000)
    # What the old strip got wrong, and nothing else: taxes and the business share were in both.
    assert old["out_cents"] - strip["out_cents"] == 50_000 + 1_384           # the card payment; the refund netted
    assert old["in_cents"] - strip["in_cents"] == 1_384 + 500               # the refund and the unsorted credit


def test_every_bar_is_its_months_spending(db):
    """Each of the 12 bars is Spending's month: money out, income and their difference; months before the book's
    history are $0."""
    _with_business(db)
    view = sp.flow_view(db, TODAY, 12)
    assert view["as_of"] == "2026-10-25"
    months = view["months"]
    assert [m["month"] for m in months] == [f"2025-{m}" for m in ("11", "12")] + [f"2026-{m:02d}" for m in range(1, 11)]
    for m in months:
        if m["month"] < "2026-04":
            assert (m["in_cents"], m["out_cents"], m["net_cents"]) == (0, 0, 0)
            continue
        head = sp.month_view(db, TODAY, sp.first_of(m["month"]))["head"]
        assert (m["in_cents"], m["out_cents"]) == (head["money_in_cents"], head["money_out_cents"])
        assert m["net_cents"] == m["in_cents"] - m["out_cents"]
    assert months[-2] == {"month": "2026-09", "in_cents": 512_000, "out_cents": 544_000, "net_cents": -32_000}


def test_a_refund_bigger_than_its_spending_takes_nothing_from_the_rest_and_the_rest_is_money_in(db):
    """Shoes nets to $0 spent (never below), so the dining stays $25 out; the $60 the return came to past $0 is money
    in, with the paycheck less its correction."""
    chk = make_account(db)
    make_txn(db, chk, date(2026, 10, 3), -4_000, "SHOE STORE", category="shopping")
    make_txn(db, chk, date(2026, 10, 9), 10_000, "SHOE STORE RETURN", category="shopping")
    make_txn(db, chk, date(2026, 10, 9), -2_500, "DINER", category="dining")
    make_txn(db, chk, date(2026, 10, 10), 30_000, "PAYROLL", category="income")
    make_txn(db, chk, date(2026, 10, 11), -1_000, "PAYROLL CORRECTION", category="income")
    (m,) = sp.flow_view(db, TODAY, 1)["months"]
    assert m == {"month": "2026-10", "in_cents": 35_000, "out_cents": 2_500, "net_cents": 32_500}
    head = sp.month_view(db, TODAY, OCT)["head"]
    assert (head["income_cents"], head["money_in_cents"]) == (29_000, 35_000)     # Income's section: income only


def _flexible(v: dict) -> dict:
    """What a Flexible row says against its target: spent, state, how far over and the today mark."""
    return {r["category"]: (r["target_cents"], r["spent_cents"], r["state"], r["over_cents"], r["over_level"],
                            r["usual_by_today_cents"]) for r in v["everyday"]}


def test_a_big_gift_past_zero_is_money_in_and_leaves_the_flexible_targets_as_they_were(db):
    """JR's call on #58's "money in past $0 counts nowhere": a $2,000 family gift sorted to Gifts, with no Gifts
    spending this month, raises the month's money in by $2,000 (Home's figure, its strip and Spending's out · in line),
    and money out, the plan figure and every Flexible row against its target stay as they were. Gifts' row reads $0
    spent, on track, as gift money netting against Gifts always has."""
    chk = household(db)["checking"]
    db.add(SpendingTarget(category="gifts", kind="everyday", monthly_cents=10_000, updated_at=AT, updated_by=1))
    db.commit()
    before, strip_before = sp.month_view(db, TODAY, OCT), sp.flow_view(db, TODAY, 12)["months"]
    targets_before, trends_before = sp.targets_view(db, TODAY), sp.trends_view(db, TODAY, 12)
    make_txn(db, chk, date(2026, 10, 18), 200_000, "ZELLE FROM MOM", category="gifts")
    make_txn(db, chk, date(2026, 9, 18), 200_000, "ZELLE FROM MOM", category="gifts")      # a window month too
    after, strip_after = sp.month_view(db, TODAY, OCT), sp.flow_view(db, TODAY, 12)["months"]

    assert after["head"]["money_in_cents"] - before["head"]["money_in_cents"] == 200_000
    assert {k: v for k, v in after["head"].items() if k != "money_in_cents"} == {
        k: v for k, v in before["head"].items() if k != "money_in_cents"}
    assert _flexible(after) == _flexible(before)
    assert _flexible(after)["gifts"] == (10_000, 0, "on_track", 0, "on", 8_065)
    assert after["fixed"] == before["fixed"] and after["income"] == before["income"]
    for b, a in zip(strip_before[-2:], strip_after[-2:]):               # September and October
        assert (a["in_cents"] - b["in_cents"], a["out_cents"] - b["out_cents"]) == (200_000, 0)
        assert a["net_cents"] - b["net_cents"] == 200_000
    assert strip_after[:-2] == strip_before[:-2]
    # The typical month, the suggestions, Over time and the target check read spending only.
    assert sp.targets_view(db, TODAY) == targets_before
    assert sp.trends_view(db, TODAY, 12) == trends_before
    assert after["target_check"] == before["target_check"]


def test_a_refund_past_zero_on_a_targeted_category_nets_as_it_always_has(db):
    """A $2,000 refund on Shopping ($512 spent this month, a $400 target): Shopping reads $0 spent and on track, as
    today's netting has it; money out drops by the $512 it netted and money in rises by the $1,488 past $0, so the
    month's net rises by the whole $2,000."""
    card = household(db)["card"]
    before = sp.month_view(db, TODAY, OCT)
    make_txn(db, card, date(2026, 10, 19), 200_000, "MEGAMART RETURN", merchant="Megamart", category="shopping")
    after = sp.month_view(db, TODAY, OCT)
    assert _flexible(after)["shopping"] == (40_000, 0, "on_track", 0, "on", 32_258)
    assert {c: r for c, r in _flexible(after).items() if c != "shopping"} == {
        c: r for c, r in _flexible(before).items() if c != "shopping"}
    b, a = before["head"], after["head"]
    assert (a["money_out_cents"] - b["money_out_cents"], a["money_in_cents"] - b["money_in_cents"]) == (-51_200, 148_800)
    assert a["income_cents"] == b["income_cents"]


def test_an_empty_book_has_months_of_nothing(db):
    assert sp.flow_view(db, TODAY, 2)["months"] == [
        {"month": "2026-09", "in_cents": 0, "out_cents": 0, "net_cents": 0},
        {"month": "2026-10", "in_cents": 0, "out_cents": 0, "net_cents": 0}]
