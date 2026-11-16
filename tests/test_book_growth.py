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
    make_txn(db, chk, date(2026, 10, 3), -1_200, "CAFE")                               # this month: doesn't count
    assert G.first_month_sorted(db, TODAY) is False
    make_txn(db, chk, date(2026, 9, 3), -1_200, "CAFE", category="dining")
    left = make_txn(db, chk, date(2026, 9, 9), -900, "A SHOP")
    make_txn(db, chk, date(2026, 9, 12), -50_000, "TO SAVINGS", is_transfer=True)       # a transfer never waits
    assert G.first_month_sorted(db, TODAY) is False
    left.reviewed_at = AT                                                                 # Ignore: looked at
    db.commit()
    assert G.first_month_sorted(db, TODAY) is True


def test_sorted_month_is_named_while_current_month_still_waits_in_review(db):
    """Issue #33: a month-level milestone must not imply an empty Review queue."""
    from steward.services.review import waiting_filter

    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 9, 3), -100, "PAST", category="dining")
    pending = make_txn(db, chk, date(2026, 10, 3), -200, "CURRENT")
    view = G.growth_view(db, TODAY, None)
    assert list(db.scalars(select(Transaction.id).where(waiting_filter(AT)))) == [pending.id]
    assert view["milestones"][0] == {"key": "first_month", "met": True, "month": "2026-09"}
    assert view["stage"] == 1 and view["seen"] is False
    assert G.growth_view(db, TODAY, 1)["seen"] is True
    assert _facts(db) == ["1"]


def test_sorted_month_uses_earliest_qualifying_month_not_insertion_order(db):
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 9, 3), -100, "LATER", category="dining")
    make_txn(db, chk, date(2026, 7, 3), -100, "EARLIER", category="dining")
    make_txn(db, chk, date(2026, 6, 3), -100, "UNRESOLVED")
    assert G.milestones(db, TODAY)[0]["month"] == "2026-07"


def test_sorted_month_requires_resolved_nontransfer_data(db):
    chk = make_account(db, "Checking")
    assert G.milestones(db, TODAY)[0] == {"key": "first_month", "met": False}
    make_txn(db, chk, date(2026, 8, 3), -100, "TRANSFER", is_transfer=True)
    row = make_txn(db, chk, date(2026, 9, 3), -100, "WAITING")
    row.snoozed_until = datetime(2026, 11, 1, tzinfo=timezone.utc)
    db.commit()
    assert G.milestones(db, TODAY)[0] == {"key": "first_month", "met": False}
    row.reviewed_at = AT  # Ignore resolves the row; snoozing alone does not.
    db.commit()
    assert G.growth_view(db, TODAY, None)["milestones"][0]["month"] == "2026-09"
    row.reviewed_at = None
    db.commit()
    view = G.growth_view(db, TODAY, None)
    assert view["milestones"][0] == {"key": "first_month", "met": False}
    assert view["stage"] == 1
    assert _facts(db) == ["1"]


def test_sorted_month_keeps_the_year_across_january(db):
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2026, 12, 31), -100, "DECEMBER", category="dining")
    make_txn(db, chk, date(2027, 1, 1), -100, "JANUARY")
    assert G.milestones(db, date(2027, 1, 3))[0]["month"] == "2026-12"


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
    assert [m["met"] for m in G.milestones(db, TODAY)][3:] == [False, False]             # 364 days
    make_txn(db, chk, date(2025, 10, 30), -100, "OLDER")
    assert [m["met"] for m in G.milestones(db, TODAY)][3:] == [True, False]              # 365 days
    make_txn(db, chk, date(2021, 10, 31), -100, "ANCIENT")
    assert [m["met"] for m in G.milestones(db, TODAY)][3:] == [True, False]              # 1,825 days
    make_txn(db, chk, date(2021, 10, 30), -100, "OLDEST")
    assert [m["met"] for m in G.milestones(db, TODAY)][3:] == [True, True]               # five years, with 2024's leap day


def test_the_milestones_are_five_keys_in_order(db):
    assert [m["key"] for m in G.milestones(db, TODAY)] == ["first_month", "covered", "checklist", "year", "five_years"]


def test_the_stage_is_written_only_when_it_rises_and_never_shrinks(db):
    chk = make_account(db, "Checking")
    old = make_txn(db, chk, date(2025, 6, 1), -100, "OLD", category="dining")   # June 2025: a sorted month, and a year
    assert G.growth_view(db, TODAY, None)["stage"] == 2
    assert G.growth_view(db, TODAY, None)["stage"] == 2
    assert _facts(db) == ["2"]                                                           # once, though asked twice
    db.execute(delete(Transaction).where(Transaction.id == old.id))
    db.commit()
    view = G.growth_view(db, TODAY, None)
    assert view["stage"] == 2 and not any(m["met"] for m in view["milestones"])           # the high-water mark holds
    assert _facts(db) == ["2"]
    make_txn(db, chk, date(2026, 9, 1), -100, "NEW", category="dining")                  # one met again: under the mark
    assert G.growth_view(db, TODAY, None)["stage"] == 2
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
    assert G.growth_view(db, TODAY, None)["seen"] is True                                # stage 0: nothing to show
    chk = make_account(db, "Checking")
    make_txn(db, chk, date(2025, 6, 1), -100, "OLD")
    assert G.growth_view(db, TODAY, None)["seen"] is False
    assert G.growth_view(db, TODAY, 0)["seen"] is False
    assert G.growth_view(db, TODAY, 1)["seen"] is True
    assert G.growth_view(db, TODAY, 5)["seen"] is True
