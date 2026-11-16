"""Matching (spec, Matching payments): the window edges, ±25%, the closest wins, late, refused never re-offered,
a hand match outside the window, one payment never matched twice, and a summary event after a sync or an import."""
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from steward.db.models import EventLog, SetAside, SetAsideMatch, SimplefinLink, Transaction
from steward.services import setasides as sa
from tests.factories import make_account, make_txn
from tests.setaside_fixtures import AT, FIRST, TODAY, household


def test_adding_a_set_aside_matches_its_past_payments_from_history(db):
    h = household(db)
    got = sa.match_set_aside(db, h["proptax"], TODAY)
    db.commit()
    assert [(m.due_on, m.how, m.late) for m in got] == [
        (date(2025, 4, 10), "auto", False), (date(2025, 11, 1), "auto", True), (date(2026, 4, 10), "auto", False)]
    # Apr 9, 2025 paid a day early; Nov 3, 2025 two days late; nothing yet for Nov 1, 2026.
    assert sa.standings(db, TODAY)[h["proptax"].id].next_due == date(2026, 11, 1)
    assert sa.match_set_aside(db, h["proptax"], TODAY) == []            # again: nothing new
    assert db.scalars(select(EventLog).where(EventLog.kind == "setaside")).all() == []   # an add folds it into its own event


def test_a_payment_45_days_early_is_in_and_a_set_aside_with_neither_payee_nor_category_matches_nothing(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    ins = h["carins"]                                                    # $1,860 due Aug 14; payee SAFEGUARD INSURANCE
    make_txn(db, chk, date(2026, 6, 30), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")   # 45 days before: in
    assert [(m.due_on, m.late) for m in sa.match_set_aside(db, ins, TODAY)] == [(date(2026, 8, 14), False)]
    db.commit()
    make_txn(db, chk, date(2026, 12, 1), -150_000, "GIFT SHOP", merchant="Gift Shop", category="gifts")
    assert sa.candidates(db, h["holidays"], date(2026, 12, 1)) == []    # Holidays has no payee and no category (decision 15)


def test_the_window_edges_in_days(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    ins = h["carins"]
    due = date(2026, 8, 14)
    early = make_txn(db, chk, date(2026, 6, 29), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")   # 46 days before: out
    late = make_txn(db, chk, date(2026, 9, 26), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")    # 43 days after: out
    assert sa.candidates(db, ins, due) == []
    on_edge = make_txn(db, chk, date(2026, 9, 25), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")  # 42 days after: in
    assert [t.id for t, _ in sa.candidates(db, ins, due)] == [on_edge.id]
    assert early.id != late.id


def test_amount_within_25_percent_and_the_closest_payment_wins(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    ins = h["carins"]
    due = date(2026, 8, 14)
    make_txn(db, chk, date(2026, 8, 1), -139_499, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")    # 25.0001% under: out
    make_txn(db, chk, date(2026, 8, 2), -232_501, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")    # over 25% over: out
    far = make_txn(db, chk, date(2026, 8, 3), -139_500, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")    # exactly 25% under: in
    near = make_txn(db, chk, date(2026, 8, 13), -232_500, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")  # exactly 25% over, closer: wins
    assert sorted(t.id for t, _ in sa.candidates(db, ins, due)) == sorted([far.id, near.id])
    got = sa.match_set_aside(db, ins, TODAY)
    assert [(m.transaction_id, m.late) for m in got] == [(near.id, False)]


def _insurance(db, chk, d):
    return make_txn(db, chk, d, -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")


def test_the_closest_payment_wins_even_when_a_later_one_posted(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    early = _insurance(db, chk, date(2026, 8, 10))                 # 4 days before the Aug 14 due date
    _insurance(db, chk, date(2026, 8, 25))                         # 11 days after: further, though posted later
    got = sa.match_set_aside(db, h["carins"], TODAY)
    assert [(m.transaction_id, m.late) for m in got] == [(early.id, False)]


def test_two_payments_the_same_distance_away_the_earlier_posted_wins(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    before = _insurance(db, chk, date(2026, 8, 10))                # 4 days before
    _insurance(db, chk, date(2026, 8, 18))                         # 4 days after
    got = sa.match_set_aside(db, h["carins"], TODAY)
    assert [(m.transaction_id, m.late) for m in got] == [(before.id, False)]


def test_a_hand_match_with_no_unpaid_installment_left_says_so_in_plain_words(db, monkeypatch):
    h = household(db)
    chk = h["accounts"]["checking"]
    t = make_txn(db, chk, date(2026, 9, 2), -100_000, "ZELLE", category="uncategorized")
    monkeypatch.setattr(sa, "due_dates", lambda *a, **k: [])
    with pytest.raises(sa.MatchError, match="already paid"):
        sa.match_by_hand(db, t, h["proptax"], TODAY, by=1)


def _county(db, chk, d, cents=-421_000):
    return make_txn(db, chk, d, cents, "COUNTY TAX COLLECTOR", merchant="County Tax Collector", category="taxes")


def _no_county(db):
    for t in db.scalars(select(Transaction).where(Transaction.category == "taxes")):
        db.delete(t)
    db.commit()


def test_one_installment_takes_one_payment_and_the_closest_wins(db):
    """Review Focus 1: the April installment paid early (Mar 28) leaves the Apr 12 payment unmatched."""
    h = household(db)
    chk = h["accounts"]["checking"]
    _no_county(db)
    march = _county(db, chk, date(2026, 3, 28))
    april = _county(db, chk, date(2026, 4, 12))
    got = sa.match_set_aside(db, h["proptax"], TODAY)
    assert [(m.transaction_id, m.due_on, m.late) for m in got] == [(april.id, date(2026, 4, 10), True)]   # 2 days beats 13 days
    db.commit()
    assert db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == march.id)) is None
    assert sa.standings(db, TODAY)[h["proptax"].id].next_due == date(2026, 11, 1)


def test_an_installment_paid_early_does_not_take_a_second_payment_near_its_date(db):
    """Review Focus 1, the other order: April is paid early by Mar 28 with no closer candidate. A payment near Apr 10
    that comes later is not taken for April (it already has its payment), and the next due date stays Nov 1."""
    h = household(db)
    chk = h["accounts"]["checking"]
    _no_county(db)
    march = _county(db, chk, date(2026, 3, 28))
    got = sa.match_set_aside(db, h["proptax"], TODAY)
    db.commit()
    assert [(m.transaction_id, m.due_on, m.late) for m in got] == [(march.id, date(2026, 4, 10), False)]
    second = _county(db, chk, date(2026, 4, 11))
    assert sa.match_set_aside(db, h["proptax"], TODAY) == []
    assert db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == second.id)) is None
    assert sa.standings(db, TODAY)[h["proptax"].id].next_due == date(2026, 11, 1)


def test_a_refund_on_the_payee_is_never_a_candidate(db):
    """Review Focus 4: money in from the payee, a transfer, a card payment and an all-business row are never candidates."""
    h = household(db)
    chk = h["accounts"]["checking"]
    ins = h["carins"]
    make_txn(db, chk, date(2026, 8, 10), 186_000, "SAFEGUARD INSURANCE REFUND", merchant="Safeguard Insurance", category="insurance")
    make_txn(db, chk, date(2026, 8, 10), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="transfer")
    make_txn(db, chk, date(2026, 8, 10), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance", is_transfer=True)
    make_txn(db, chk, date(2026, 8, 10), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance", is_business=True)
    assert sa.candidates(db, ins, date(2026, 8, 14)) == []
    split = make_txn(db, chk, date(2026, 8, 11), -372_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance", business_pct=50)
    assert [(t.id, c) for t, c in sa.candidates(db, ins, date(2026, 8, 14))] == [(split.id, 186_000)]   # the personal share counts


def test_by_category_when_no_payee_is_set_but_never_for_a_one_off(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    camps = h["camps"]                                                   # $2,400 due Jun 1, no payee: by category
    camps.category = "kids"
    db.commit()
    assert [m.due_on for m in sa.match_set_aside(db, camps, TODAY)] == [date(2026, 6, 1)]     # Camp Sunrise, Jun 15: late
    plumber = make_txn(db, chk, date(2026, 10, 20), -220_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    heater = h["heater"]
    heater.category = "home"
    db.commit()
    assert sa.match_set_aside(db, heater, date(2028, 12, 5)) == []                             # a one-off needs a payee or a hand
    heater.payee_key = "DALES PLUMBING"
    db.commit()
    assert sa.match_set_aside(db, heater, date(2028, 12, 5)) == []                             # and the window: Oct 2026 is not near Dec 2028
    assert plumber.id


def test_a_refusal_is_never_offered_again_and_the_installment_goes_back_to_unpaid(db):
    h = household(db)
    sa.match_set_aside(db, h["proptax"], TODAY)
    db.commit()
    april = db.scalar(select(SetAsideMatch).where(SetAsideMatch.due_on == date(2026, 4, 10)))
    m = sa.refuse(db, april.transaction_id, by=1)
    db.commit()
    assert (m.how, m.set_aside_id, m.due_on) == ("refused", h["proptax"].id, date(2026, 4, 10))
    assert sa.match_set_aside(db, h["proptax"], TODAY) == []                                   # not offered again
    st = sa.standings(db, TODAY)[h["proptax"].id]
    assert st.counted_from == date(2025, 11, 1) and st.missed == ()                           # April is unpaid, before the first month
    with pytest.raises(sa.MatchError, match="isn't matched"):
        sa.refuse(db, 999_999, by=1)


def test_a_refused_payment_leaves_automatic_matching_entirely(db):
    """Even with a fresh set-aside on the same payee that would take it, a refused payment stays out of play."""
    h = household(db)
    sa.match_set_aside(db, h["proptax"], TODAY)
    db.commit()
    april = db.scalar(select(SetAsideMatch).where(SetAsideMatch.due_on == date(2026, 4, 10)))
    sa.refuse(db, april.transaction_id, by=1)
    db.commit()
    other = SetAside(name="County again", kind="yearly", amount_cents=421_000, due_month=4, due_day=10, first_month=FIRST,
                     payee_key="COUNTY TAX COLLECTOR", created_at=AT, updated_at=AT)
    db.add(other)
    db.commit()
    assert sa.candidates(db, other, date(2026, 4, 10)) == []
    assert sa.match_all(db, TODAY) == []


def test_a_hand_match_skips_the_window_and_the_amount_and_takes_the_nearest_unpaid_installment(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    t = make_txn(db, chk, date(2026, 9, 2), -100_000, "ZELLE PAYMENT TO COUNTY", category="uncategorized")   # far from Nov 1, a quarter of it
    m = sa.match_by_hand(db, t, h["proptax"], TODAY, by=1)
    db.commit()
    assert (m.due_on, m.how, m.late) == (date(2026, 11, 1), "hand", False)                    # Sep 2 is 60 days from Nov 1, 145 from Apr 10
    assert sa.standings(db, TODAY)[h["proptax"].id].next_due == date(2027, 4, 10)
    with pytest.raises(sa.MatchError, match="already matched"):
        sa.match_by_hand(db, t, h["camps"], TODAY, by=1)                                       # one payment, one match
    refund = make_txn(db, chk, date(2026, 9, 3), 5_000, "REFUND", category="uncategorized")
    with pytest.raises(sa.MatchError, match="money out"):
        sa.match_by_hand(db, refund, h["camps"], TODAY, by=1)


def test_a_hand_match_refuses_a_business_payment(db):
    """Final review: an all-business row never reaches Spending, so a hand match to it would show on the transaction
    and nowhere else. It is refused in plain words; a split row's personal share is household money and matches."""
    h = household(db)
    chk = h["accounts"]["checking"]
    biz = make_txn(db, chk, date(2026, 10, 20), -240_000, "CAMP SUNRISE", category="kids", is_business=True)
    with pytest.raises(sa.MatchError, match="^That payment is business"):
        sa.match_by_hand(db, biz, h["camps"], TODAY, by=1)
    assert db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == biz.id)) is None
    split = make_txn(db, chk, date(2026, 10, 21), -240_000, "CAMP SUNRISE", category="kids", business_pct=50)
    assert sa.match_by_hand(db, split, h["camps"], TODAY, by=1).how == "hand"


def test_a_hand_match_to_a_one_off_has_no_horizon(db):
    """Controller ruling: a Roof due Dec 2032 takes a payment made today, however far away its date is."""
    h = household(db)
    chk = h["accounts"]["checking"]
    t = make_txn(db, chk, date(2026, 10, 20), -500_000, "ROOFERS INC", category="home")
    m = sa.match_by_hand(db, t, h["roof"], TODAY, by=1)
    db.commit()
    assert (m.set_aside_id, m.due_on, m.how, m.late) == (h["roof"].id, date(2032, 12, 1), "hand", False)
    st = sa.standings(db, TODAY)[h["roof"].id]
    assert st.paid is not None and st.paid.id == m.id and st.next_due is None and st.should == 0


def test_a_refused_payment_can_be_matched_by_hand_elsewhere(db):
    h = household(db)
    sa.match_set_aside(db, h["proptax"], TODAY)
    db.commit()
    april = db.scalar(select(SetAsideMatch).where(SetAsideMatch.due_on == date(2026, 4, 10)))
    sa.refuse(db, april.transaction_id, by=1)
    t = db.get(Transaction, april.transaction_id)
    m = sa.match_by_hand(db, t, h["camps"], TODAY, by=1)
    db.commit()
    assert (m.id, m.set_aside_id, m.how, m.due_on) == (april.id, h["camps"].id, "hand", date(2026, 6, 1))   # the same row, rewritten
    assert db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == t.id, SetAsideMatch.how == "refused")) is None


def test_a_paid_one_off_takes_nothing_more(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    bill = make_txn(db, chk, date(2028, 3, 14), -235_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    m = sa.match_by_hand(db, bill, h["heater"], date(2028, 3, 20), by=1)
    db.commit()
    assert (m.due_on, m.how) == (date(2028, 12, 1), "hand")
    st = sa.standings(db, date(2028, 3, 20))[h["heater"].id]
    assert st.paid is not None and st.paid.id == m.id and st.next_due is None and st.state == "on_track"
    again = make_txn(db, chk, date(2028, 3, 15), -5_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    with pytest.raises(sa.MatchError, match="already paid"):
        sa.match_by_hand(db, again, h["heater"], date(2028, 3, 20), by=1)


def test_it_was_not_due_settles_the_installment(db):
    h = household(db)
    sa.match_set_aside(db, h["proptax"], TODAY)
    db.commit()
    dec14 = date(2026, 12, 14)
    assert sa.standings(db, dec14)[h["proptax"].id].missed == (date(2026, 11, 1),)
    m = sa.skip_due(db, h["proptax"], date(2026, 11, 1), by=1)
    db.commit()
    assert (m.how, m.transaction_id, m.due_on) == ("skipped", None, date(2026, 11, 1))
    st = sa.standings(db, dec14)[h["proptax"].id]
    assert st.missed == () and st.next_due == date(2027, 4, 10) and st.counted_from == date(2026, 11, 1)
    with pytest.raises(sa.MatchError, match="not one of"):
        sa.skip_due(db, h["proptax"], date(2026, 11, 2), by=1)
    with pytest.raises(sa.MatchError, match="already"):
        sa.skip_due(db, h["proptax"], date(2026, 11, 1), by=1)


def test_match_all_logs_one_summary_event(db):
    h = household(db)
    chk = h["accounts"]["checking"]
    make_txn(db, chk, date(2026, 8, 14), -186_000, "SAFEGUARD INSURANCE", merchant="Safeguard Insurance", category="insurance")
    got = sa.match_all(db, TODAY)
    db.commit()
    assert len(got) == 4
    messages = [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside"))]
    assert messages == ["Steward matched 4 payments to set-asides: Property tax (Apr 10, 2025), Property tax (Nov 1, 2025), "
                        "Property tax (Apr 10, 2026), Car insurance (Aug 14, 2026)."]
    assert sa.match_all(db, TODAY) == [] and len(db.scalars(select(EventLog)).all()) == 1   # nothing new: no event


def test_match_all_can_leave_the_event_to_its_caller(db):
    h = household(db)
    assert len(sa.match_all(db, TODAY, log=False)) == 3
    assert db.scalars(select(EventLog).where(EventLog.kind == "setaside")).all() == []
    assert h["proptax"].id


def test_a_parent_books_sync_runs_no_matching(books, margaret, mdb):
    """Review Focus 5, through the real post-sync path: a parent book (the scheduled job works the flag out from the
    book kind, so a wrong call site is caught here) never matches, even with a set-aside and a payment that would match."""
    from steward.books import jobs
    from tests.fake_simplefin import make_fake
    from tests.test_sync import E, NOW
    fake, state = make_fake()
    state.add_account("big", "Big Bank", "bigbank", "chk", 1450_00, E(2026, 10, 12), txns=[
        ("t7", E(2026, 8, 14), -1860_00, "SAFEGUARD INSURANCE")])
    acct = make_account(mdb, "Checking", type="checking", source="simplefin", institution_name="Big Bank")
    acct.external_id = "sfin:chk"
    acct.institution.simplefin_org_id = "big"
    mdb.add_all([SetAside(name="Car insurance", kind="yearly", amount_cents=186_000, due_month=8, due_day=14, first_month=FIRST,
                          payee_key="SAFEGUARD INSURANCE", created_at=AT, updated_at=AT),
                 SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=NOW)])
    mdb.commit()
    with TestClient(fake) as http:
        out = jobs.sync_all_books(books, http, None, NOW, ("testserver",), only=margaret.slug)
    assert out[margaret.slug].transactions_new == 1
    mdb.rollback()
    assert mdb.scalar(select(Transaction).where(Transaction.external_id == "t7")) is not None   # the sync itself ran
    assert mdb.scalars(select(SetAsideMatch)).all() == []
    assert mdb.scalars(select(EventLog).where(EventLog.kind == "setaside")).all() == []


def test_a_matching_failure_does_not_fail_the_sync(db, monkeypatch):
    from steward.services.simplefin.sync import sync_now
    from tests.fake_simplefin import make_fake
    from tests.test_sync import H, NOW, _household, _link

    def boom(*a, **k):
        raise RuntimeError("matching broke")

    monkeypatch.setattr(sa, "match_all", boom)
    app, state = make_fake()
    _household(state)
    with TestClient(app) as http:
        _link(db, http)
        res = sync_now(db.get_bind(), http, None, NOW, H)
    db.rollback()
    assert res.transactions_new == 3 and db.scalars(select(Transaction)).all()
    assert "Couldn't match payments to set-asides after this sync." in [e.message for e in db.scalars(select(EventLog))]


# ---- An import runs matching too (api/imports.commit) ----

def _login(client, db):
    from tests.factories import make_user
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def _check_set_aside(db):
    from steward.watch.payees import payee
    return SetAside(name="Checks", kind="yearly", amount_cents=25_000, due_month=10, due_day=1, first_month=FIRST,
                    payee_key=payee("CHECK 1042", None).key, created_at=AT, updated_at=AT)


SAMPLE = Path(__file__).parent / "samples" / "chase_checking.csv"


def _upload_checking(client, db):
    from tests.import_helpers import import_file
    a = make_account(db, "Checking")
    db.add(_check_set_aside(db))
    db.commit()
    return lambda: import_file(client, "chase_checking.csv", a.id, raw=SAMPLE.read_bytes())


def test_an_import_matches_new_payments_and_says_so(client, db, frozen):
    _login(client, db)
    r = _upload_checking(client, db)()
    assert r.status_code == 201
    db.rollback()
    m = db.scalar(select(SetAsideMatch))
    assert (m.how, m.due_on, m.late) == ("auto", date(2026, 10, 1), False)           # the Sep 30 check, a day early
    msgs = [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside"))]
    assert msgs == ["Steward matched 1 payment to set-asides: Checks (Oct 1, 2026)."]


def test_a_matching_failure_does_not_fail_the_import(client, db, frozen, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("matching broke")

    monkeypatch.setattr("steward.api.imports.match_all", boom)
    _login(client, db)
    r = _upload_checking(client, db)()
    assert r.status_code == 201 and r.json()["imported"] == 3
    db.rollback()
    assert len(db.scalars(select(Transaction)).all()) == 3 and db.scalars(select(SetAsideMatch)).all() == []
    assert "Couldn't match payments to set-asides after this import." in [e.message for e in db.scalars(select(EventLog))]
