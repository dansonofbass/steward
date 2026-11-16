"""Phase 11c's rules (spec, Kinds; Put away, should be by now, and states; decisions 12-14), pinned at their edges."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from steward.db.models import SetAside, SetAsideMatch, Transaction
from steward.services import setasides as sa
from tests.factories import make_account, make_txn
from tests.setaside_fixtures import AT, FIRST, TODAY, household

NOV = date(2026, 11, 1)
LONG_AGO = datetime(2025, 1, 1, tzinfo=timezone.utc)


def yearly(amount=186_000, month=8, day=14, first=FIRST):
    return SimpleNamespace(kind="yearly", amount_cents=amount, due_month=month, due_day=day, second_month=None,
                           second_day=None, due_year=None, first_month=first, estimate=None, created_at=LONG_AGO)


def twice(amount=421_000, first=FIRST, added=LONG_AGO):
    return SimpleNamespace(kind="twice_yearly", amount_cents=amount, due_month=11, due_day=1, second_month=4,
                           second_day=10, due_year=None, first_month=first, estimate=None, created_at=added)


def once(amount=220_000, year=2028, month=12, first=FIRST):
    return SimpleNamespace(kind="one_off", amount_cents=amount, due_month=month, due_day=None, second_month=None,
                           second_day=None, due_year=year, first_month=first, estimate=None, created_at=LONG_AGO)


def test_the_monthly_amount_for_each_kind_rounds_half_up():
    assert sa.monthly_cents(yearly(186_000)) == 15_500              # $1,860 ÷ 12 = $155
    assert sa.monthly_cents(yearly(41_200)) == 3_433                # $412 ÷ 12 = $34.33
    assert sa.monthly_cents(twice(421_000)) == 70_167               # 2 × $4,210 ÷ 12 = $701.67
    assert sa.monthly_cents(once(220_000, 2028, 12)) == 8_462       # $2,200 ÷ 26 (Nov 2026 to Dec 2028, inclusive)
    assert sa.monthly_cents(once(1_800_000, 2032, 12)) == 24_324    # $18,000 ÷ 74
    assert sa.div_round(1, 2) == 1 and sa.div_round(5, 3) == 2 and sa.div_round(4, 3) == 1


def test_a_one_off_counts_its_months_inclusive_at_both_ends():
    assert sa.months_through(FIRST, 2026, 11) == 1                  # due in its first month
    assert sa.months_through(FIRST, 2026, 12) == 2
    assert sa.months_through(FIRST, 2028, 12) == 26
    assert sa.months_through(FIRST, 2026, 10) == 1                  # due before it starts: the whole cost at once, never 0
    assert sa.monthly_cents(once(100_000, 2026, 11)) == 100_000
    assert sa.first_month_after(TODAY) == NOV and sa.first_month_after(date(2026, 12, 31)) == date(2027, 1, 1)


def test_installment_and_yearly_figures():
    assert (sa.installment_cents(yearly()), sa.yearly_cents(yearly())) == (186_000, 186_000)
    assert (sa.installment_cents(twice()), sa.yearly_cents(twice())) == (421_000, 842_000)
    assert (sa.installment_cents(once()), sa.yearly_cents(once())) == (220_000, 0)


def test_due_dates_fall_on_their_month_and_day_each_year():
    assert sa.due_dates(twice(), date(2026, 1, 1), date(2027, 12, 31)) == [
        date(2026, 4, 10), date(2026, 11, 1), date(2027, 4, 10), date(2027, 11, 1)]
    assert sa.due_dates(yearly(), date(2026, 8, 15), date(2027, 8, 14)) == [date(2027, 8, 14)]
    assert sa.due_dates(once(), date(2026, 1, 1), date(2030, 1, 1)) == [date(2028, 12, 1)]
    assert sa.due_dates(once(), date(2029, 1, 1), date(2030, 1, 1)) == []


def test_a_leap_day_falls_back_to_the_28th():
    """Review Focus 2: Feb 29 is Feb 28 in a common year and Feb 29 in a leap one; the 31st is the 30th in April."""
    assert sa.safe_date(2027, 2, 29) == date(2027, 2, 28) and sa.safe_date(2028, 2, 29) == date(2028, 2, 29)
    assert sa.safe_date(2027, 4, 31) == date(2027, 4, 30)
    assert sa.due_dates(yearly(month=2, day=29), date(2027, 1, 1), date(2028, 12, 31)) == [date(2027, 2, 28), date(2028, 2, 29)]


def test_the_next_due_date_is_the_soonest_unpaid_one():
    assert sa.next_due(twice(), TODAY, set()) == date(2026, 11, 1)
    assert sa.next_due(yearly(), TODAY, set()) == date(2027, 8, 14)
    assert sa.next_due(yearly(month=10, day=25), TODAY, set()) == TODAY                     # due today is still next
    assert sa.next_due(once(), TODAY, set()) == date(2028, 12, 1)
    assert sa.next_due(once(), TODAY, {date(2028, 12, 1)}) is None                           # a paid one-off has no next


def test_an_installment_paid_early_moves_the_next_due_date_on():
    """Review Focus 1: the April installment paid in March counts as paid; next is November."""
    assert sa.next_due(twice(), date(2026, 3, 30), {date(2026, 4, 10)}) == date(2026, 11, 1)
    assert sa.next_due(twice(), date(2026, 3, 30), set()) == date(2026, 4, 10)


def test_a_one_off_has_no_horizon_on_its_next_due_date():
    """Controller ruling: a Roof one-off due Dec 2032 is not paid; its next due date is its due date, never None."""
    roof = once(1_800_000, 2032, 12)
    assert sa.next_due(roof, TODAY, set()) == date(2032, 12, 1)
    assert sa.next_due(roof, TODAY, {date(2032, 12, 1)}) is None


def test_an_unpaid_installment_stays_next_for_six_weeks_then_is_missed():
    nov1 = date(2026, 11, 1)
    assert sa.next_due(twice(), date(2026, 12, 13), set()) == nov1                            # 42 days on: still next
    assert sa.missed_dues(twice(), date(2026, 12, 13), set()) == []
    assert sa.next_due(twice(), date(2026, 12, 14), set()) == date(2027, 4, 10)               # 43 days on: moved on
    assert sa.missed_dues(twice(), date(2026, 12, 14), set()) == [nov1]
    assert sa.missed_dues(twice(), date(2026, 12, 14), {nov1}) == []                          # paid or skipped: not missed
    # Before the first month nothing is missed (engineering choice 3): added in October, April was never its concern.
    assert sa.missed_dues(twice(), TODAY, set()) == []
    assert sa.missed_dues(twice(first=date(2026, 1, 1)), TODAY, set()) == [date(2026, 4, 10)]


def test_should_be_by_now_counts_whole_months_from_the_month_after_the_last_payment():
    assert sa.should_be_cents(twice(), TODAY, date(2026, 4, 1)) == 6 * 70_167               # May to October
    assert sa.should_be_cents(twice(), TODAY, None) == 0                                      # first month is November
    assert sa.should_be_cents(twice(), date(2026, 11, 15), None) == 70_167
    assert sa.should_be_cents(yearly(240_000, 6, 1), TODAY, date(2026, 6, 1)) == 4 * 20_000   # July to October: $800
    assert sa.should_be_cents(once(), date(2028, 12, 20), None) == 220_000                    # 26 × $84.62 = $2,200.12, capped at the cost
    assert sa.should_be_cents(once(), date(2029, 6, 1), None) == 220_000                      # and it stops growing after the due month
    assert sa.should_be_cents(yearly(), date(2026, 12, 1), date(2026, 12, 1)) == 0            # paid this month: nothing yet


def test_one_account_is_shared_out_soonest_first_and_the_rest_goes_last():
    """Review Focus 3: three passes, soonest due first: should-be-by-now, then up to the next installment, then the last."""
    rows = [(1, date(2026, 11, 1), 421_200, 421_000), (2, date(2028, 12, 1), 0, 220_000), (3, date(2032, 12, 1), 0, 1_800_000)]
    assert sa.share_out(rows, 410_000) == {1: 410_000, 2: 0, 3: 0}
    assert sa.share_out(rows, 500_000) == {1: 421_200, 2: 78_800, 3: 0}                      # past should-be, the next installment is topped up
    assert sa.share_out(rows, 3_000_000) == {1: 421_200, 2: 220_000, 3: 2_358_800}           # more than every installment: the excess goes last
    nothing_yet = [(1, date(2026, 11, 1), 0, 421_000), (2, date(2028, 12, 1), 0, 220_000), (3, date(2032, 12, 1), 0, 1_800_000)]
    assert sa.share_out(nothing_yet, 410_000) == {1: 410_000, 2: 0, 3: 0}                    # nothing owed by now: the soonest still gets it
    assert sa.share_out([(1, date(2026, 11, 1), 0, 0), (2, date(2028, 12, 1), 0, 220_000)], 100_000) == {1: 0, 2: 100_000}   # a paid one-off needs 0
    paid = [(1, date(2026, 11, 1), 0, 421_000), (2, date(2028, 12, 1), 0, 0), (3, date(2032, 12, 1), 0, 1_800_000)]
    assert sa.share_out(paid, 3_000_000) == {1: 421_000, 2: 0, 3: 2_579_000}                 # a paid one-off takes nothing, even last in line
    assert sa.share_out([(1, date(2026, 11, 1), 0, 421_000), (2, date(2032, 12, 1), 0, 0)], 3_000_000) == {1: 3_000_000, 2: 0}
    assert sa.share_out([(7, None, 10_000, 10_000)], 25_000) == {7: 25_000}                  # one alone takes it all
    assert sa.share_out([(1, date(2027, 1, 1), 100, 100), (2, None, 100, 100)], 150) == {1: 100, 2: 50}  # no due date sorts last
    assert sa.share_out(rows, -5_000) == {1: 0, 2: 0, 3: 0}                                  # an overdrawn account puts nothing away
    assert sa.share_out([], 1_000) == {}


def test_states_at_their_thresholds():
    nov1 = date(2026, 11, 1)
    st = lambda **kw: sa.state_of(**{"linked": True, "today": TODAY, "next_due": nov1, "missed": False,       # noqa: E731
                                     "put_away": 410_000, "should": 421_200, "installment": 421_000, **kw})
    assert st() == "short"                                                                   # due in 6 days, $110 short
    assert st(put_away=421_000) == "on_track"                                                # at the installment is not short
    assert st(next_due=date(2026, 11, 24)) == "short"                                        # 30 days away: within
    assert st(next_due=date(2026, 11, 25)) == "on_track"                                     # 31 days: not yet (and $112 of $4,212 is under 5%)
    assert st(next_due=date(2026, 10, 15)) == "short"                                        # 10 days overdue, inside the 6 weeks: still short
    assert st(next_due=None, put_away=60_000, should=80_000) == "behind"                     # $200: over $25 and 25%
    assert st(next_due=None, put_away=97_500, should=100_000) == "on_track"                  # $25 exactly: not behind
    assert st(next_due=None, put_away=97_499, should=100_000) == "on_track"                  # $25.01 but 2.5%: not behind
    assert st(next_due=None, put_away=95_000, should=100_000) == "on_track"                  # 5% exactly: not behind
    assert st(next_due=None, put_away=94_999, should=100_000) == "behind"                    # 5.001%: behind
    assert st(next_due=None, put_away=950, should=1_000) == "on_track"                       # 5% but only 50 cents
    assert st(next_due=None, missed=True, put_away=100_000, should=100_000) == "not_paid"
    assert st(missed=True) == "short"                                                        # short outranks not paid
    assert st(next_due=None, put_away=0, should=0) == "on_track"                             # nothing due yet
    assert st(linked=False, put_away=0, should=0) == "no_account"
    assert st(linked=False, missed=True, put_away=0, should=0) == "not_paid"                 # no account, but a missed one still shows
    assert sa.STATES == ("short", "behind", "not_paid", "on_track", "no_account") and sa.NEEDS_LOOK == ("short", "behind", "not_paid")


def test_standings_for_the_household(db):
    h = household(db)
    # The county's April payment is matched (Task 4 does this automatically); here the rows are written by hand.
    paid = db.scalar(select(Transaction).where(Transaction.posted_at == date(2026, 4, 10)))
    db.add(SetAsideMatch(transaction_id=paid.id, set_aside_id=h["proptax"].id, due_on=date(2026, 4, 10), how="auto", late=False,
                         created_at=AT))
    camp = db.scalar(select(Transaction).where(Transaction.posted_at == date(2026, 6, 15)))
    db.add(SetAsideMatch(transaction_id=camp.id, set_aside_id=h["camps"].id, due_on=date(2026, 6, 1), how="hand", late=True, created_at=AT))
    db.commit()
    st = sa.standings(db, TODAY)
    p = st[h["proptax"].id]
    assert (p.next_due, p.should, p.put_away, p.state, p.installment, p.counted_from) == (
        date(2026, 11, 1), 421_002, 410_000, "short", 421_000, date(2026, 4, 1))
    assert p.balance == (date(2026, 10, 24), 410_000) and p.shared == ("Water heater", "Roof") and p.missed == ()
    c = st[h["camps"].id]
    assert (c.next_due, c.should, c.put_away, c.state) == (date(2027, 6, 1), 80_000, 60_000, "behind")
    assert (st[h["heater"].id].state, st[h["heater"].id].put_away, st[h["heater"].id].next_due) == ("on_track", 0, date(2028, 12, 1))
    assert st[h["roof"].id].shared == ("Property tax", "Water heater")
    assert (st[h["roof"].id].next_due, st[h["roof"].id].paid, st[h["roof"].id].state) == (date(2032, 12, 1), None, "on_track")
    assert st[h["holidays"].id].state == "no_account" and st[h["holidays"].id].next_due == date(2026, 12, 1)
    assert st[h["carins"].id].next_due == date(2027, 8, 14)
    assert sa.is_estimate(h["heater"]) and not sa.is_estimate(h["holidays"])
    assert sa.estimate_of(h["heater"])["planned_year"] == 2028


def test_a_set_aside_with_no_snapshot_has_nothing_put_away(db):
    acct = make_account(db, "Empty savings", type="savings")
    row = SetAside(name="Thing", kind="yearly", amount_cents=12_000, due_month=12, due_day=1, first_month=date(2026, 1, 1),
                   account_id=acct.id, created_at=AT, updated_at=AT)
    db.add(row); db.commit()
    s = sa.standings(db, TODAY)[row.id]
    assert (s.put_away, s.balance, s.should, s.state) == (0, None, 10 * 1_000, "behind")


def test_an_installment_paid_a_month_early_is_paid_and_should_be_counts_from_the_next_month(db):
    """Review Focus 1, pinned for real: the April installment is paid by a March 28 payment and nothing else is near.
    It counts as paid, the next due date moves on to Nov 1, and should-be counts from April."""
    chk = make_account(db, "Checking")
    row = SetAside(name="Property tax", kind="twice_yearly", amount_cents=421_000, due_month=11, due_day=1, second_month=4,
                   second_day=10, first_month=date(2026, 1, 1), account_id=chk.id, created_at=AT, updated_at=AT)
    db.add(row)
    pay = make_txn(db, chk, date(2026, 3, 28), -421_000, "COUNTY TAX COLLECTOR")
    db.commit()
    db.add(SetAsideMatch(transaction_id=pay.id, set_aside_id=row.id, due_on=date(2026, 4, 10), how="auto", late=False, created_at=AT))
    db.commit()
    today = date(2026, 6, 15)
    s = sa.standings(db, today)[row.id]
    assert s.next_due == date(2026, 11, 1) and s.missed == ()
    assert s.counted_from == date(2026, 3, 1)
    assert s.should == 3 * 70_167                                                             # April, May, June


def test_a_set_aside_added_after_an_installment_is_never_short_for_it(db):
    """An installment due before the set-aside was added is neither next nor missed."""
    chk = make_account(db, "Checking", type="savings")
    row = SetAside(name="Tax", kind="twice_yearly", amount_cents=100_000, due_month=10, due_day=10, second_month=4, second_day=10,
                   first_month=date(2026, 11, 1), account_id=chk.id, created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
                   updated_at=AT)
    db.add(row); db.commit()
    s = sa.standings(db, TODAY)[row.id]
    assert s.next_due == date(2027, 4, 10) and s.missed == () and s.state == "on_track"
    # The pure rules agree, even with a first month long before the day it was added.
    early = twice(first=date(2026, 1, 1), added=datetime(2026, 10, 20, tzinfo=timezone.utc))
    assert sa.next_due(early, TODAY, set()) == NOV and sa.missed_dues(early, TODAY, set()) == []


def test_one_set_aside_alone_gets_the_same_standing_as_in_the_list(db):
    h = household(db)
    full = sa.standings(db, TODAY)
    for key in ("heater", "proptax", "roof"):
        alone = sa.standings(db, TODAY, [h[key]])
        assert list(alone) == [h[key].id] and alone[h[key].id] == full[h[key].id]
    heater = sa.standings(db, TODAY, [h["heater"]])[h["heater"].id]
    assert heater.put_away == 0 and heater.shared == ("Property tax", "Roof")
    assert full[h["proptax"].id].put_away == 410_000 and full[h["roof"].id].put_away == 0     # nothing owed yet: the soonest due is topped up first


def test_a_paid_one_off_needs_nothing_more(db):
    chk = make_account(db, "Checking")
    acct = make_account(db, "House fund", type="savings")
    row = SetAside(name="Water heater", kind="one_off", amount_cents=220_000, due_year=2027, due_month=3, first_month=FIRST,
                   account_id=acct.id, created_at=AT, updated_at=AT)
    db.add(row)
    pay = make_txn(db, chk, date(2027, 3, 12), -215_000, "PLUMBER")
    db.commit()
    db.add(SetAsideMatch(transaction_id=pay.id, set_aside_id=row.id, due_on=date(2027, 3, 1), how="hand", late=True, created_at=AT))
    db.commit()
    s = sa.standings(db, date(2027, 6, 10))[row.id]
    assert (s.should, s.state, s.paid is not None) == (0, "on_track", True)
    assert sa.share_out([(row.id, s.next_due, s.should, 0)], 0) == {row.id: 0}


def test_the_schedule_never_shows_an_installment_before_the_set_aside_was_added_as_next(db):
    """Final review: an unpaid installment due before the set-aside was added is neither next nor missed, on the
    schedule as in the standing, so the schedule's next is the row's next_due. One matched to a payment still shows as
    paid."""
    added = datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc)
    row = SetAside(name="Car insurance", kind="yearly", amount_cents=186_000, due_month=9, due_day=20, first_month=FIRST,
                   created_at=added, updated_at=added)
    # Added Sep 1, due Sep 5: 50 days before Oct 25, so past next_due's six weeks, and before its first month (Oct).
    early = SetAside(name="Registration", kind="yearly", amount_cents=41_200, due_month=9, due_day=5, first_month=date(2026, 10, 1),
                     created_at=datetime(2026, 9, 1, 19, 0, tzinfo=timezone.utc), updated_at=added)
    db.add_all([row, early])
    db.commit()
    for r, nxt in ((row, date(2027, 9, 20)), (early, date(2027, 9, 5))):
        st = sa.standings(db, TODAY)[r.id]
        assert (st.next_due, st.missed) == (nxt, ())
        assert [(d["due_on"], d["status"]) for d in sa.dues_out(db, r, st, TODAY)] == [(nxt.isoformat(), "next")]
    chk = make_account(db, "Checking")
    pay = make_txn(db, chk, date(2026, 9, 18), -186_000, "SAFEGUARD INSURANCE")
    db.commit()
    db.add(SetAsideMatch(transaction_id=pay.id, set_aside_id=row.id, due_on=date(2026, 9, 20), how="hand", late=False, created_at=added))
    db.commit()
    st = sa.standings(db, TODAY)[row.id]
    assert [(d["due_on"], d["status"]) for d in sa.dues_out(db, row, st, TODAY)] == [("2026-09-20", "paid"), ("2027-09-20", "next")]


def test_the_day_it_was_added_is_the_households_day():
    """An evening in Los Angeles is the next day in UTC: the set-aside was added on the household's day, so an
    installment due that day is its own."""
    evening = yearly(month=10, day=1, first=date(2026, 11, 1))
    evening.created_at = datetime(2026, 10, 2, 2, 30, tzinfo=timezone.utc)                  # Oct 1, 7:30 pm in Los Angeles
    assert sa.added_on(evening) == date(2026, 10, 1)
    assert sa.next_due(evening, date(2026, 10, 10), set()) == date(2026, 10, 1)


def test_a_one_off_due_this_month_and_added_after_the_1st_is_next_then_missed():
    """A one-off is due on the 1st of its month: one added on Oct 25 for October counts from Oct 1, so it is next
    for six weeks and then missed, never neither."""
    fence = once(amount=300_000, year=2026, month=10, first=date(2026, 11, 1))
    fence.created_at = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)
    assert sa.next_due(fence, date(2026, 10, 25), set()) == date(2026, 10, 1)
    assert sa.missed_dues(fence, date(2026, 10, 25), set()) == []
    assert sa.next_due(fence, date(2026, 12, 20), set()) is None
    assert sa.missed_dues(fence, date(2026, 12, 20), set()) == [date(2026, 10, 1)]
    # A yearly cost added after its date still never claims it.
    late = yearly(month=10, day=1, first=date(2026, 11, 1))
    late.created_at = fence.created_at
    assert sa.next_due(late, date(2026, 10, 25), set()) == date(2027, 10, 1)
