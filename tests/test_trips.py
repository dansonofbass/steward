"""Reimbursable spec, The review list: groups and reasons around a trip's dates on a card the household shares; home
merchants on 3 of the 6 months before, outside other trips; flights and hotels booked within 60 days ahead; refunds
(R2); the trip's own rows and a person's choice; and a trip's fields."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from steward.db.models import Reimburser, Trip
from steward.services import trips
from steward.services.reimburse import ReimburseError
from tests.factories import make_account, make_txn

AT = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def h(db):
    acme = Reimburser(name="Acme", created_at=AT)
    db.add(acme)
    db.commit()
    card = make_account(db, "Sapphire", type="credit")
    for m in (4, 5, 6, 7, 8, 9):                       # groceries at home, every month
        make_txn(db, card, date(2026, m, 12), -8_000, "KROGER #123 COLUMBUS OH", category="groceries")
    for m in (5, 7, 9):                                # coffee on the home town's Chicago Ave: 3 of the 6 months
        make_txn(db, card, date(2026, m, 3), -650, "STARBUCKS CHICAGO AVE", category="dining")
    make_txn(db, card, date(2026, 8, 20), -4_000, "ACE HARDWARE 44", category="home")
    make_txn(db, card, date(2026, 9, 2), -1_100, "CORNER MART", category="shopping")
    trip = Trip(name="Chicago trip", start=date(2026, 10, 6), end=date(2026, 10, 9), city="Chicago, IL",
                reimburser_id=acme.id, created_at=AT)
    db.add(trip)
    db.commit()
    return SimpleNamespace(acme=acme, card=card, trip=trip)


def test_groups_and_reasons_on_a_shared_card(db, h):
    def add(d, cents, raw, category="uncategorized"):
        return make_txn(db, h.card, d, cents, raw, category=category)
    add(date(2026, 8, 20), -42_000, "UNITED AIRLINES 0162", "travel")       # 47 days ahead: booked
    add(date(2026, 7, 20), -42_000, "DELTA AIR LINES", "travel")            # 78 days ahead: not listed
    add(date(2026, 9, 30), -9_000, "TARGET 0042", "shopping")                # before the day before: not listed
    add(date(2026, 10, 6), -61_200, "PALMER HOUSE HOTEL", "travel")
    add(date(2026, 10, 7), -2_840, "UBER TRIP", "transport")
    add(date(2026, 10, 7), -5_580, "PORTILLOS CHICAGO IL", "dining")
    add(date(2026, 10, 7), -650, "STARBUCKS CHICAGO AVE", "dining")          # a home merchant, but it says Chicago
    add(date(2026, 10, 7), -8_000, "KROGER #123 COLUMBUS OH", "groceries")   # the same day, at home
    add(date(2026, 10, 8), -1_500, "LITTLE PIE SHOP", "dining")
    add(date(2026, 10, 8), -3_000, "ACE HARDWARE 44", "home")
    add(date(2026, 10, 8), -2_500, "BRIGHT KIDS DAYCARE", "childcare_education")
    add(date(2026, 10, 8), -1_100, "CORNER MART", "shopping")
    add(date(2026, 10, 10), -3_300, "IL STATE TOLLWAY", "transport")         # the day after: says IL
    add(date(2026, 10, 11), -3_300, "GAS STATION 9", "transport")            # two days after: not listed
    rows = trips.review(db, h.trip)
    assert {r.txn.raw_description: (r.group, r.reason, r.ticked) for r in rows} == {
        "UNITED AIRLINES 0162": ("booked", {"why": "booked"}, True),
        "PALMER HOUSE HOTEL": ("likely", {"why": "hotel"}, True),
        "UBER TRIP": ("likely", {"why": "ride"}, True),
        "PORTILLOS CHICAGO IL": ("likely", {"why": "says", "place": "Chicago"}, True),
        "STARBUCKS CHICAGO AVE": ("likely", {"why": "says", "place": "Chicago"}, True),
        "LITTLE PIE SHOP": ("likely", {"why": "new"}, True),
        "IL STATE TOLLWAY": ("likely", {"why": "says", "place": "IL"}, True),
        "KROGER #123 COLUMBUS OH": ("home", {"why": "regular"}, False),
        "ACE HARDWARE 44": ("home", {"why": "home_only", "category": "home"}, False),
        "BRIGHT KIDS DAYCARE": ("home", {"why": "home_only", "category": "childcare_education"}, False),
        "CORNER MART": ("unsure", {"why": "unsure"}, False),
    }
    order = [trips.GROUPS.index(r.group) for r in rows]
    assert order == sorted(order)


def test_two_months_is_not_a_home_merchant_and_rows_on_or_during_another_trip_are_left_out(db, h):
    for d in (date(2026, 6, 3), date(2026, 8, 3)):
        make_txn(db, h.card, d, -900, "BAGEL BARN", category="dining")
    other = Trip(name="Denver trip", start=date(2026, 7, 14), end=date(2026, 7, 16), reimburser_id=h.acme.id,
                 created_at=AT)
    db.add(other)
    db.commit()
    make_txn(db, h.card, date(2026, 7, 15), -900, "BAGEL BARN", category="dining")     # during another trip: not home
    bagel = make_txn(db, h.card, date(2026, 10, 7), -900, "BAGEL BARN", category="dining")
    taken = make_txn(db, h.card, date(2026, 10, 8), -4_000, "PALMER HOUSE HOTEL", category="travel")
    taken.trip_id = other.id
    db.commit()
    rows = {r.txn.id: r for r in trips.review(db, h.trip)}
    assert (rows[bagel.id].group, rows[bagel.id].reason) == ("unsure", {"why": "unsure"})
    assert taken.id not in rows


def test_a_refund_from_a_likely_merchant_is_listed_and_ticked(db, h):
    make_txn(db, h.card, date(2026, 10, 6), -61_200, "PALMER HOUSE HOTEL", category="travel")
    back = make_txn(db, h.card, date(2026, 10, 10), 4_000, "PALMER HOUSE HOTEL", category="travel")
    home = make_txn(db, h.card, date(2026, 10, 8), 2_000, "KROGER #123 COLUMBUS OH", category="groceries")
    rows = {r.txn.id: r for r in trips.review(db, h.trip)}
    assert (rows[back.id].group, rows[back.id].reason, rows[back.id].ticked) == ("likely", {"why": "refund"}, True)
    assert home.id not in rows


def test_the_trips_own_rows_stay_ticked_and_a_row_a_person_unmarked_stays_unticked(db, h):
    pie = make_txn(db, h.card, date(2026, 10, 8), -1_500, "LITTLE PIE SHOP", category="dining")
    kroger = make_txn(db, h.card, date(2026, 10, 7), -8_000, "KROGER #123 COLUMBUS OH", category="groceries")
    early = make_txn(db, h.card, date(2026, 10, 2), -900, "MUSEUM SHOP", category="shopping")
    kroger.reimburser_id, kroger.trip_id = h.acme.id, h.trip.id         # a person ticked it on this trip before
    pie.reimburse_source = "manual"                                    # a person said it isn't reimbursed
    early.reimburser_id, early.trip_id = h.acme.id, h.trip.id          # on the trip, outside its dates now
    db.commit()
    rows = {r.txn.id: r for r in trips.review(db, h.trip)}
    assert (rows[kroger.id].group, rows[kroger.id].ticked) == ("home", True)
    assert (rows[pie.id].group, rows[pie.id].ticked) == ("likely", False)
    assert (rows[early.id].group, rows[early.id].ticked) == ("unsure", True)


def test_transfers_repayments_business_rows_and_business_accounts_are_never_listed(db, h):
    xfer = make_txn(db, h.card, date(2026, 10, 7), -50_000, "PAYMENT THANK YOU", category="transfer", is_transfer=True)
    biz = make_txn(db, h.card, date(2026, 10, 7), -5_000, "COWORK CHICAGO", category="business_expense",
                   business_pct=100)
    bcard = make_account(db, "Business card", type="business_credit", owner="business")
    on_biz = make_txn(db, bcard, date(2026, 10, 7), -5_000, "PORTILLOS CHICAGO IL", category="dining", is_business=False)
    repay = make_txn(db, make_account(db), date(2026, 10, 8), 50_000, "ACME CORP EXP", category="reimbursement")
    assert not {r.txn.id for r in trips.review(db, h.trip)} & {xfer.id, biz.id, on_biz.id, repay.id}


@pytest.mark.parametrize("city, place", [
    ("Chicago", trips.Place("CHICAGO", None, "Chicago")),
    ("Chicago, IL", trips.Place("CHICAGO", "IL", "Chicago")),
    (" st. louis , mo ", trips.Place("ST. LOUIS", "MO", "st. louis")),
    ("IL", trips.Place(None, "IL", None)),
    ("Saint Paul, XX", trips.Place("SAINT PAUL", None, "Saint Paul")),
    ("", trips.Place(None, None, None)),
    (None, trips.Place(None, None, None)),
])
def test_a_city_is_a_city_a_city_and_state_or_a_state_alone(city, place):
    assert trips.place_of(city) == place


def test_says_needs_whole_words():
    assert trips.says("PORTILLOS CHICAGO IL", trips.place_of("Chicago")) == "Chicago"
    assert trips.says("CHICAGOLAND SPEEDWAY", trips.place_of("Chicago")) is None
    assert trips.says("ST LOUIS BREAD CO", trips.place_of("St. Louis, MO")) == "St. Louis"
    assert trips.says("MOUNTAIN MO 22", trips.place_of("Branson, MO")) == "MO"
    assert trips.says("MOJO CAFE", trips.place_of("Branson, MO")) is None


def test_trip_fields_default_the_name_and_refuse_bad_ones(db, h):
    assert trips.trip_fields(db, {"start": "2026-10-06", "end": "2026-10-09", "city": "  Chicago,  IL "}) == {
        "name": "Chicago trip", "start": date(2026, 10, 6), "end": date(2026, 10, 9), "city": "Chicago, IL",
        "reimburser_id": h.acme.id}
    for body, words in (({"start": "2026-10-09", "end": "2026-10-06", "name": "X"}, "ends before it starts"),
                        ({"start": "2026-10-01", "end": "2026-12-30", "name": "X"}, "at most 90 days"),
                        ({"start": "soon", "end": "2026-10-06", "name": "X"}, "starts and ends"),
                        ({"start": "2026-10-06", "end": "2026-10-09"}, "a name"),
                        ({"start": "2026-10-06", "end": "2026-10-09", "name": "x" * 81}, "a name"),
                        ({"start": "2026-10-06", "end": "2026-10-09", "name": "X", "city": "c" * 61}, "a city")):
        with pytest.raises(ReimburseError, match=words):
            trips.trip_fields(db, body)
