"""P21: the mortgage payment from the newest transfer pair into the mortgage account in the last 95 days."""
from datetime import date, timedelta

from steward.services.mortgage_payment import detected
from tests.factories import make_account, make_txn

TODAY = date(2026, 10, 13)


def pay(db, chk, mortgage, day, cents):
    out = make_txn(db, chk, day, -cents, "CHASE MTG PMT", is_transfer=True)
    into = make_txn(db, mortgage, day, cents, "PAYMENT RECEIVED", is_transfer=True)
    out.transfer_peer_id, into.transfer_peer_id = into.id, out.id
    db.commit()


def test_no_pair_leaves_the_field_empty(db):
    chk, m = make_account(db), make_account(db, "Mortgage", type="mortgage")
    make_txn(db, chk, TODAY - timedelta(days=3), -268_000, "CHASE MTG PMT")        # not paired: not a payment
    assert detected(db, m.id, TODAY) is None


def test_one_pair_is_the_payment(db):
    chk, m = make_account(db), make_account(db, "Mortgage", type="mortgage")
    pay(db, chk, m, date(2026, 10, 1), 268_000)
    assert detected(db, m.id, TODAY) == {"posted_at": "2026-10-01", "amount_cents": 268_000, "varied": None}


def test_three_within_a_dollar_did_not_vary(db):
    chk, m = make_account(db), make_account(db, "Mortgage", type="mortgage")
    for day, cents in ((date(2026, 8, 1), 268_050), (date(2026, 9, 1), 268_000), (date(2026, 10, 1), 268_100)):
        pay(db, chk, m, day, cents)
    assert detected(db, m.id, TODAY)["varied"] is None


def test_detection_takes_the_newest_and_names_the_range(db):
    """Review Focus 4: extra principal some months."""
    chk, m = make_account(db), make_account(db, "Mortgage", type="mortgage")
    for day, cents in ((date(2026, 8, 1), 268_000), (date(2026, 9, 1), 318_000), (date(2026, 10, 1), 268_000)):
        pay(db, chk, m, day, cents)
    assert detected(db, m.id, TODAY) == {"posted_at": "2026-10-01", "amount_cents": 268_000,
                                         "varied": {"lo": 268_000, "hi": 318_000}}


def test_a_pair_outside_95_days_is_not_used(db):
    chk, m = make_account(db), make_account(db, "Mortgage", type="mortgage")
    pay(db, chk, m, TODAY - timedelta(days=100), 268_000)
    assert detected(db, m.id, TODAY) is None
