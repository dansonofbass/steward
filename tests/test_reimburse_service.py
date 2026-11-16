"""Reimbursable spec: payers made on first use, the owed balance (charges, R2 refunds, repayments and settlements, and
below $0), repayments filling trips and single charges oldest first, Settle's default category, the switch's reach, and
marking."""
from datetime import date, datetime, timezone

import pytest

from steward.db.models import ReimburseSettlement, Trip
from steward.services import reimburse as rb
from tests.factories import make_account, make_txn

AT = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)


def _payer(db, name="Acme"):
    p, _ = rb.add_payer(db, name, AT)
    db.commit()
    return p


def _marked(db, acct, d, cents, raw, payer, category="travel", trip=None):
    t = make_txn(db, acct, d, cents, raw, category=category)
    t.reimburser_id, t.trip_id, t.reimburse_source = payer.id, trip.id if trip else None, "manual"
    db.commit()
    return t


def test_a_payer_is_made_once_whatever_the_case_or_spaces(db):
    p, made = rb.add_payer(db, "  Acme   Corp ", AT)
    again, made_again = rb.add_payer(db, "acme corp", AT)
    assert (p.name, made) == ("Acme Corp", True) and (again.id, made_again) == (p.id, False)
    for bad in ("", "   ", "x" * 61, None, 7):
        with pytest.raises(rb.ReimburseError, match="1 to 60"):
            rb.add_payer(db, bad, AT)


def test_a_rename_cannot_take_another_payers_name(db):
    a, b = _payer(db, "Acme"), _payer(db, "Globex")
    with pytest.raises(rb.ReimburseError, match="already has that name"):
        rb.rename_payer(db, b, "ACME")
    assert rb.rename_payer(db, a, "Acme Inc").name == "Acme Inc"
    assert rb.rename_payer(db, a, "acme inc").name == "acme inc"       # its own name in another case is fine


def test_payer_for_never_guesses(db):
    with pytest.raises(rb.ReimburseError, match="Say who pays you back first"):
        rb.payer_for(db)
    a = _payer(db, "Acme")
    assert rb.payer_for(db).id == a.id
    b = _payer(db, "Globex")
    with pytest.raises(rb.ReimburseError, match="Choose who pays you back"):
        rb.payer_for(db)
    assert rb.payer_for(db, b.id).id == b.id
    for bad in (999, True, "1"):
        with pytest.raises(rb.ReimburseError, match="No such payer"):
            rb.payer_for(db, bad)


def test_owed_is_charges_less_refunds_repayments_and_settlements_and_can_go_below_zero(db):
    acme = _payer(db)
    card, chk = make_account(db, "Card", type="credit"), make_account(db, "Checking")
    _marked(db, card, date(2026, 9, 8), -40_000, "HILTON CHICAGO IL", acme)
    _marked(db, card, date(2026, 9, 9), -12_000, "UNITED AIRLINES", acme)
    _marked(db, card, date(2026, 9, 12), 2_000, "HILTON CHICAGO IL", acme)                 # R2: a refund marked with it
    make_txn(db, card, date(2026, 9, 10), -9_999, "GREENLEAF MARKET", category="groceries")    # not marked
    _marked(db, chk, date(2026, 9, 25), 30_000, "ACME CORP EXP", acme, category="reimbursement")
    _marked(db, chk, date(2026, 9, 27), -1_000, "ACME CORP EXP REV", acme, category="reimbursement")   # a reversal
    db.add(ReimburseSettlement(reimburser_id=acme.id, amount_cents=5_000, category="travel", settled_at=AT))
    db.commit()
    o = rb.owed_by(db)[acme.id]
    # The reversal counts once, against the repayments, never as a charge (engineering choice 1).
    assert (o.marked_cents, o.refunds_cents, o.repaid_cents, o.settled_cents) == (52_000, 2_000, 29_000, 5_000)
    assert o.owed_cents == 16_000 and o.cleared_cents == 36_000
    assert (o.since, o.last_repaid_on) == (date(2026, 9, 8), date(2026, 9, 25))
    _marked(db, chk, date(2026, 10, 2), 20_000, "ACME CORP EXP", acme, category="reimbursement")
    assert rb.owed_map(db) == {acme.id: -4_000}          # paid more than has been marked


def test_a_payer_with_nothing_owes_nothing(db):
    acme = _payer(db)
    assert rb.owed_by(db) == {acme.id: rb.Owed(acme.id)}


def test_repayments_fill_trips_and_single_charges_oldest_first(db):
    acme = _payer(db)
    card, chk = make_account(db, "Card", type="credit"), make_account(db, "Checking")
    trip = Trip(name="Chicago trip", start=date(2026, 9, 8), end=date(2026, 9, 10), reimburser_id=acme.id,
                created_at=AT)
    db.add(trip)
    db.commit()
    _marked(db, card, date(2026, 9, 8), -40_000, "HILTON CHICAGO IL", acme, trip=trip)
    _marked(db, card, date(2026, 9, 9), -10_000, "UBER TRIP", acme, category="transport", trip=trip)
    _marked(db, card, date(2026, 9, 12), 1_000, "UBER TRIP", acme, category="transport", trip=trip)   # nets in its trip
    lunch = _marked(db, card, date(2026, 10, 1), -6_000, "PORTILLOS CHICAGO IL", acme, category="dining")
    late = _marked(db, card, date(2026, 10, 9), -3_000, "TAXI 22", acme, category="transport")
    _marked(db, chk, date(2026, 10, 5), 52_000, "ACME CORP EXP", acme, category="reimbursement")
    items = rb.statuses(db)[acme.id]
    assert [(i.kind, i.id, i.first_on, i.total_cents, i.covered_cents, i.status) for i in items] == [
        ("trip", trip.id, date(2026, 9, 8), 49_000, 49_000, "paid"),
        ("charge", lunch.id, date(2026, 10, 1), 6_000, 3_000, "partly"),
        ("charge", late.id, date(2026, 10, 9), 3_000, 0, "waiting")]
    assert rb.settle_category(db, acme.id, items) == "dining"       # $60 Eating out and $30 Getting around still open


def test_a_refund_on_no_trip_comes_back_like_a_repayment(db):
    acme = _payer(db)
    card = make_account(db, "Card", type="credit")
    hotel = _marked(db, card, date(2026, 9, 8), -40_000, "HILTON CHICAGO IL", acme)
    _marked(db, card, date(2026, 9, 12), 40_000, "HILTON CHICAGO IL", acme)
    assert [(i.id, i.status) for i in rb.statuses(db)[acme.id]] == [(hotel.id, "paid")]


def test_settle_defaults_to_travel_when_nothing_is_open(db):
    acme = _payer(db)
    assert rb.settle_category(db, acme.id, []) == "travel"


def test_the_switch_is_offered_for_money_out_and_for_a_refund_on_a_reimbursable_merchant_only(db):
    acme = _payer(db)
    card = make_account(db, "Card", type="credit")
    _marked(db, card, date(2026, 9, 8), -40_000, "HILTON CHICAGO IL 0042", acme)
    pats = rb.refundable_patterns(db)
    assert pats == {"HILTON CHICAGO IL"}
    out = make_txn(db, card, date(2026, 9, 9), -1_000, "DINER")
    refund = make_txn(db, card, date(2026, 9, 12), 2_000, "HILTON CHICAGO IL 0043", category="travel")
    other = make_txn(db, card, date(2026, 9, 12), 2_000, "DINER REFUND", category="dining")
    xfer = make_txn(db, card, date(2026, 9, 12), -5_000, "PAYMENT THANK YOU", category="transfer", is_transfer=True)
    repay = make_txn(db, card, date(2026, 9, 12), 5_000, "ACME CORP EXP", category="reimbursement")
    assert [rb.can_reimburse(t, pats) for t in (out, refund, other, xfer, repay)] == [True, True, False, False, False]
    assert rb.can_reimburse(out, pats, category="transfer") is False
    assert rb.can_reimburse(out, pats, category="reimbursement") is False


def test_marking_turns_business_off_and_not_reimbursed_takes_the_trip_too(db):
    acme = _payer(db)
    trip = Trip(name="Chicago trip", start=date(2026, 9, 8), end=date(2026, 9, 10), reimburser_id=acme.id,
                created_at=AT)
    db.add(trip)
    db.commit()
    t = make_txn(db, make_account(db, "Card", type="credit"), date(2026, 9, 8), -40_000, "HILTON", business_pct=100)
    rb.mark(t, acme, trip_id=trip.id)
    assert (t.reimburser_id, t.trip_id, t.reimburse_source, t.business_pct, t.is_business) == (
        acme.id, trip.id, "manual", 0, False)
    rb.mark(t, acme, source="rule")
    assert (t.trip_id, t.reimburse_source) == (trip.id, "rule")      # KEEP: the trip stays
    rb.unmark(t)
    assert (t.reimburser_id, t.trip_id, t.reimburse_source) == (None, None, "manual")
