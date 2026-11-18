"""Growth toward an oak (phase 17 spec 3.4): five milestones from the book's own data, and the stage as a high-water
mark in the fact growth.stage, written only when it rises. Today is 2026-10-30 (the fake clock)."""
from datetime import date, datetime, timezone

from sqlalchemy import delete, select

from steward.db.models import BalanceSnapshot, Fact, SetAside, Transaction
from steward.services import book_growth as G
from tests.factories import add_fact, make_account, make_ready_household, make_txn

TODAY = date(2026, 10, 30)
AT = datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc)


def _facts(db) -> list[str]:
    db.rollback()
    return list(db.scalars(select(Fact.value).where(Fact.key == G.STAGE_KEY).order_by(Fact.id)))


def test_a_month_before_this_one_with_every_row_sorted_or_looked_at(db):
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 10, 3), -1_200, "CAFE", category="dining")             # this month: doesn't count
    assert G.sorted_month(db, TODAY, AT) is None
    make_txn(db, chk, date(2026, 9, 3), -1_200, "CAFE", category="dining")
    left = make_txn(db, chk, date(2026, 9, 9), -900, "A SHOP")
    make_txn(db, chk, date(2026, 9, 12), -50_000, "TO SAVINGS", is_transfer=True)       # a transfer never waits
    assert G.sorted_month(db, TODAY, AT) is None
    left.reviewed_at = AT                                                                 # Ignore: looked at
    db.commit()
    assert G.sorted_month(db, TODAY, AT) == "2026-09"


def test_the_first_month_waits_while_any_row_waits_in_review_and_names_the_newest_sorted_month(db):
    """#33: a sorted September and a row waiting in October's Review: Home would say "fully sorted" beside "1 to sort
    in Review", so the milestone holds until Review is empty."""
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 8, 3), -1_200, "CAFE", category="dining")
    make_txn(db, chk, date(2026, 9, 3), -1_200, "CAFE", category="dining")
    waiting = make_txn(db, chk, date(2026, 10, 3), -900, "A SHOP")
    assert G.sorted_month(db, TODAY, AT) is None
    assert G.milestones(db, TODAY, AT)[0] == {"key": "first_month", "met": False, "month": None}
    waiting.snoozed_until = datetime(2026, 11, 2, tzinfo=timezone.utc)                   # snoozed: not in Review now
    db.commit()
    assert G.sorted_month(db, TODAY, AT) == "2026-09"
    waiting.snoozed_until = None
    waiting.category = "shopping"
    db.commit()
    assert G.milestones(db, TODAY, AT)[0] == {"key": "first_month", "met": True, "month": "2026-09"}


def test_covered_is_a_linked_set_aside_covering_its_next_installment_before_it_is_due(db):
    fund = make_account(db, "Car fund", type="savings")
    sa = SetAside(name="Car insurance", kind="yearly", amount_cents=120_000, due_month=12, due_day=1,
                  first_month=date(2026, 10, 1), account_id=fund.id)
    db.add_all([sa, BalanceSnapshot(account_id=fund.id, as_of=TODAY, balance_cents=50_000)])
    db.commit()
    assert G.set_aside_covered(db, TODAY) is False                                                  # $500 of $1,200
    db.execute(delete(BalanceSnapshot).where(BalanceSnapshot.account_id == fund.id))
    db.add(BalanceSnapshot(account_id=fund.id, as_of=TODAY, balance_cents=130_000))
    db.commit()
    assert G.set_aside_covered(db, TODAY) is True
    sa.account_id = None                                                                  # unlinked: nothing covers it
    db.commit()
    assert G.set_aside_covered(db, TODAY) is False


def test_covered_before_it_is_due_means_not_on_the_due_day_itself(db):
    fund = make_account(db, "Car fund", type="savings")
    db.add_all([SetAside(name="Car insurance", kind="yearly", amount_cents=120_000, due_month=10, due_day=30,
                         first_month=date(2026, 1, 1), account_id=fund.id),
                BalanceSnapshot(account_id=fund.id, as_of=TODAY, balance_cents=130_000)])
    db.commit()
    assert G.set_aside_covered(db, TODAY) is False                                        # due today: the page shows no moment
    assert G.set_aside_covered(db, date(2026, 10, 29)) is True


def test_the_plan_checklist_complete(db):
    assert G.checklist_done(db, TODAY) is False
    make_ready_household(db)
    assert G.checklist_done(db, TODAY) is True


def test_a_year_and_five_years_of_history_count_from_the_earliest_transaction(db):
    chk = make_account(db, "Checking")
    assert G.history_days(db, TODAY) == 0
    make_txn(db, chk, date(2025, 10, 31), -100, "OLD")
    assert [m["met"] for m in G.milestones(db, TODAY, AT)][3:] == [False, False]             # 364 days
    make_txn(db, chk, date(2025, 10, 30), -100, "OLDER")
    assert [m["met"] for m in G.milestones(db, TODAY, AT)][3:] == [True, False]              # 365 days
    make_txn(db, chk, date(2021, 10, 31), -100, "ANCIENT")
    assert [m["met"] for m in G.milestones(db, TODAY, AT)][3:] == [True, False]              # 1,825 days
    make_txn(db, chk, date(2021, 10, 30), -100, "OLDEST")
    assert [m["met"] for m in G.milestones(db, TODAY, AT)][3:] == [True, True]               # five years, with 2024's leap day


def test_the_milestones_are_five_keys_in_order(db):
    assert [m["key"] for m in G.milestones(db, TODAY, AT)] == ["first_month", "covered", "checklist", "year", "five_years"]


def test_the_stage_is_written_only_when_it_rises_and_never_shrinks(db):
    chk = make_account(db, "Checking")
    old = make_txn(db, chk, date(2025, 6, 1), -100, "OLD", category="dining")   # June 2025: a sorted month, and a year
    assert G.growth_view(db, TODAY, AT, None)["stage"] == 2
    assert G.growth_view(db, TODAY, AT, None)["stage"] == 2
    assert _facts(db) == ["2"]                                                           # once, though asked twice
    db.execute(delete(Transaction).where(Transaction.id == old.id))
    db.commit()
    view = G.growth_view(db, TODAY, AT, None)
    assert view["stage"] == 2 and not any(m["met"] for m in view["milestones"])           # the high-water mark holds
    assert _facts(db) == ["2"]
    make_txn(db, chk, date(2026, 9, 1), -100, "NEW", category="dining")                  # one met again: under the mark
    assert G.growth_view(db, TODAY, AT, None)["stage"] == 2
    assert _facts(db) == ["2"]


def test_raise_stage_writes_once_for_two_requests_at_the_same_height(db):
    assert G.raise_stage(db, 3, TODAY) == 3
    assert G.raise_stage(db, 3, TODAY) == 3
    assert _facts(db) == ["3"]
    assert G.raise_stage(db, 1, TODAY) == 3


def test_a_growth_stage_fact_that_isnt_a_clean_number_is_ignored(db):
    for v in ("9", "x", "-1", "2", " 4"):
        add_fact(db, G.STAGE_KEY, v)
    assert G.stored_stage(db) == 2
    assert G.raise_stage(db, 3, TODAY) == 3                                               # junk never blocks a real rise


def test_seen_is_the_persons_mark_and_a_stage_of_nothing_is_always_seen(db):
    assert G.growth_view(db, TODAY, AT, None)["seen"] is True                                # stage 0: nothing to show
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2025, 6, 1), -100, "OLD")
    assert G.growth_view(db, TODAY, AT, None)["seen"] is False
    assert G.growth_view(db, TODAY, AT, 0)["seen"] is False
    assert G.growth_view(db, TODAY, AT, 1)["seen"] is True
    assert G.growth_view(db, TODAY, AT, 5)["seen"] is True
