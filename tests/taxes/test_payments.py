"""Estimated payments found in transactions (ruling 6)."""
from datetime import date, datetime, timezone

from steward.taxes import store
from steward.taxes.payments import counted, find_payments, window
from tests.factories import make_account, make_txn

AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)


def test_the_window_runs_from_last_years_january_date():
    assert window(2026) == (date(2026, 1, 15), date(2027, 1, 15))
    assert window(2027) == (date(2027, 1, 15), date(2028, 1, 18))


def _rows(db):
    chk = make_account(db, "Checking")
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    ids = {}
    for key, acct, posted, cents, raw, kw in (
        ("q1", chk, date(2026, 4, 14), -400_000, "IRS USATAXPYMT 2604", {}),
        ("ca1", chk, date(2026, 4, 14), -120_000, "FRANCHISE TAX BD PAYMENTS", {}),
        ("q3", biz, date(2026, 9, 12), -350_000, "USTREAS IRS ESTIMATED TAX", {"category": "taxes"}),
        ("old", chk, date(2026, 1, 10), -300_000, "IRS USATAXPYMT", {}),               # 2025's fourth payment
        ("refund", chk, date(2026, 5, 2), 90_000, "IRS TREAS 310 TAX REF", {}),        # money in
        ("xfer", chk, date(2026, 6, 1), -50_000, "IRS USATAXPYMT", {"is_transfer": True}),
        ("chair", chk, date(2026, 6, 2), -8_000, "CHAIRS AND MORE", {}),
        ("jan", chk, date(2027, 1, 15), -200_000, "CA FTB TAX PAYMENT", {}),
    ):
        ids[key] = make_txn(db, acct, posted, cents, raw, **kw).id
    return ids


def test_irs_and_ftb_payments_in_the_window(db):
    ids = _rows(db)
    found = find_payments(db, 2026, "CA")
    assert [(p.id, p.agency, p.amount_cents, p.counts) for p in found] == [
        (ids["q1"], "federal", 400_000, True), (ids["ca1"], "state", 120_000, True),
        (ids["q3"], "federal", 350_000, True), (ids["jan"], "state", 200_000, True)]
    assert found[0].description == "IRS USATAXPYMT 2604" and found[0].posted_at == date(2026, 4, 14)
    assert counted(found, "federal") == [(date(2026, 4, 14), 400_000), (date(2026, 9, 12), 350_000)]


def test_outside_california_ftb_payments_are_not_estimates(db):
    _rows(db)
    assert {p.agency for p in find_payments(db, 2026, "TX")} == {"federal"}


def test_a_payment_marked_not_an_estimate_stops_counting(db):
    ids = _rows(db)
    store.mark_payment(db, ids["q1"], False, 1, AT)
    db.commit()
    found = find_payments(db, 2026, "CA")
    assert [p.counts for p in found if p.id == ids["q1"]] == [False]
    assert counted(found, "federal") == [(date(2026, 9, 12), 350_000)]


def test_eftps_payments_from_a_business_account_start_as_not_estimates(db):
    # final review m8: an employer's payroll tax deposits go through EFTPS from the business account, a dozen or more
    # a year; they start uncounted and one tap counts one that was an estimate. Personal accounts are unchanged.
    chk = make_account(db, "Checking")
    biz = make_account(db, "Business checking", type="business_checking", owner="business")
    card = make_account(db, "Business card", type="business_credit")
    personal = make_txn(db, chk, date(2026, 4, 14), -400_000, "IRS USATAXPYMT 2604").id
    deposit = make_txn(db, biz, date(2026, 5, 15), -310_000, "IRS USATAXPYMT 2705").id
    eftps = make_txn(db, card, date(2026, 6, 15), -310_000, "EFTPS TAX PAYMENT").id
    estimate = make_txn(db, biz, date(2026, 9, 12), -350_000, "USTREAS IRS ESTIMATED TAX", category="taxes").id
    db.commit()
    found = {p.id: p.counts for p in find_payments(db, 2026, "CA")}
    assert found == {personal: True, deposit: False, eftps: False, estimate: True}
    store.mark_payment(db, deposit, True, 1, AT)
    db.commit()
    assert {p.id: p.counts for p in find_payments(db, 2026, "CA")}[deposit] is True
    store.mark_payment(db, deposit, False, 1, AT)
    db.commit()
    assert {p.id: p.counts for p in find_payments(db, 2026, "CA")}[deposit] is False
