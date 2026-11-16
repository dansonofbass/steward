"""Month by month (spec 4.4; ruling 14): recent months by category, what's expected in the next 60 days from the
regular charges and deposits watching knows, and a short line against cash above the floors."""
import json
from datetime import date

from steward.care import monthly as Mo
from steward.db.models import Account, WatchKnown
from steward.services.cashflow import cashflow
from steward.watch.payees import payee
from tests.care.helpers import NOW, TODAY, add_account, add_item
from tests.factories import make_txn


def _book(mdb, balance: int):
    chk_item, chk = add_account(mdb, "Joint checking", "checking", balance)
    chk_item.details = json.dumps({"type": "checking", "floor_cents": 20_000})
    ss = add_item(mdb, "income", "Social Security", {"source": "social_security", "amount_cents": 214_000,
                                                     "frequency": "monthly", "usual_day": 3})
    add_item(mdb, "insurance", "Long-term care", {"type": "long_term_care", "amount_cents": 21_200,
                                                  "frequency": "monthly", "usual_day": 10})
    add_item(mdb, "insurance", "Homeowners", {"type": "home", "amount_cents": 146_000, "frequency": "yearly",
                                              "renewal_on": "2025-11-20"})
    add_item(mdb, "insurance", "Medicare Part B", {"type": "medicare", "amount_cents": 18_500, "frequency": "monthly",
                                                   "usual_day": 3, "paid_from_id": ss.id})
    add_item(mdb, "income", "Bond interest", {"source": "other", "amount_cents": 5_000, "frequency": "quarterly"})
    make_txn(mdb, chk, date(2026, 9, 16), -9_000, "SOUTHERN CALIFORNIA EDISON", category="utilities")
    make_txn(mdb, chk, date(2026, 9, 3), 214_000, "SSA TREAS 310 XXSOC SEC", category="income")
    mdb.add(WatchKnown(payee_key=payee("SOUTHERN CALIFORNIA EDISON").key, payee_name="Southern California Edison",
                       check="monthly", added_by=1, added_at=NOW))
    mdb.flush()


def test_the_next_60_days_from_items_and_known_payees(mdb):
    _book(mdb, 50_000)
    m = Mo.month_by_month(mdb, TODAY)
    assert [(e.on, e.label, e.cents, e.source) for e in m.expected] == [
        (date(2026, 10, 16), "Southern California Edison", -9_000, "known"),
        (date(2026, 11, 3), "Social Security", 214_000, "item"),
        (date(2026, 11, 10), "Long-term care", -21_200, "item"),
        (date(2026, 11, 16), "Southern California Edison", -9_000, "known"),
        (date(2026, 11, 20), "Homeowners", -146_000, "item"),
        (date(2026, 12, 3), "Social Security", 214_000, "item"),
        (date(2026, 12, 10), "Long-term care", -21_200, "item")]
    assert (m.expected_in_cents, m.expected_out_cents) == (428_000, 206_400)
    assert (m.cash_cents, m.floors_cents, m.above_floor_cents) == (50_000, 20_000, 30_000)
    assert (m.short_month, m.short_cents, m.short_line) == (None, 0, None)
    assert m.undated == 1                               # the quarterly interest has no date to place it
    assert len(m.months) == 6 and m.months[-1]["month"] == "2026-10"
    assert m.months[-2]["out_cents"] == 9_000 and m.months[-2]["in_cents"] == 214_000


def test_short_this_month_when_out_is_more_than_in_and_the_cash_above_the_floor(mdb):
    _book(mdb, 10_000)                                  # $100 against a $200 floor
    m = Mo.month_by_month(mdb, TODAY)
    assert (m.short_month, m.short_cents) == (date(2026, 10, 1), 19_000)
    assert m.short_line == "Short this month by $190"


def test_short_in_a_later_month_names_it(mdb):
    _book(mdb, 50_000)
    add_item(mdb, "insurance", "Umbrella", {"type": "home", "amount_cents": 500_000, "frequency": "yearly",
                                              "renewal_on": "2026-12-05"})
    m = Mo.month_by_month(mdb, TODAY)
    # Oct leaves $210; Nov adds $378 net, $588; Dec: +$2,140 - $5,000 - $212 = -$3,072 -> short $2,484
    assert (m.short_month, m.short_cents, m.short_line) == (date(2026, 12, 1), 248_400, "Short in December by $2,484")


def test_transfers_stay_out_even_when_the_feed_did_not_pair_them(mdb):
    # I2: an unpaired card payment is categorized transfer; counting it would count the card's purchases twice
    _book(mdb, 50_000)
    chk = mdb.get(Account, add_account(mdb, "Other checking", "checking", 0)[1].id)
    make_txn(mdb, chk, date(2026, 9, 22), -40_000, "CITI CARD ONLINE PAYMENT", category="transfer")
    make_txn(mdb, chk, date(2026, 9, 25), -30_000, "TRANSFER TO SAVINGS", category="transfer", is_transfer=True)
    mdb.add(WatchKnown(payee_key=payee("CITI CARD ONLINE PAYMENT").key, payee_name="Citi card", check="monthly",
                       added_by=1, added_at=NOW))
    mdb.flush()
    m = Mo.month_by_month(mdb, TODAY)
    assert m.months[-2]["out_cents"] == 9_000
    assert "transfer" not in {c["category"] for row in m.months for c in row["categories"]}
    assert "Citi card" not in {e.label for e in m.expected}
    # the Cash flow screen still shows the unpaired payment
    assert cashflow(mdb, TODAY, 6)[-2]["out_cents"] == 49_000


def test_a_cd_is_not_cash_on_hand_for_the_short_line(mdb):
    # M2: money locked in a 12-month CD can't cover a short month in checking
    _book(mdb, 10_000)
    cd_item, _ = add_account(mdb, "12-month CD", "cd", 2_000_000)
    cd_item.details = json.dumps({"type": "cd", "floor_cents": 0})
    add_account(mdb, "Way2Save savings", "savings", 5_000)
    mdb.flush()
    m = Mo.month_by_month(mdb, TODAY)
    assert (m.cash_cents, m.floors_cents) == (15_000, 20_000)
    assert m.short_line == "Short this month by $140"


def test_occurrences_step_by_months_and_clip_to_the_month_end():
    assert Mo.occurrences(date(2026, 1, 31), 1, date(2026, 2, 1), date(2026, 4, 30)) == [
        date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    assert Mo.occurrences(date(2025, 11, 20), 12, date(2026, 10, 14), date(2026, 12, 12)) == [date(2026, 11, 20)]
    assert Mo.occurrences(date(2026, 3, 1), 3, date(2026, 10, 14), date(2026, 12, 12)) == [date(2026, 12, 1)]
