"""What people enter for Taxes (ruling 21): checked first, nothing written when a value is refused."""
from datetime import date, datetime, timezone

import pytest

from steward.taxes import store
from steward.taxes.store import ReturnFigures, StoreError, Withholding

AT = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 13)


def test_return_figures_round_trip_and_blank_clears(db):
    assert store.read_return(db, 2025) is None
    figs = store.write_return(db, 2025, {"federal_tax_cents": 1_500_000, "federal_agi_cents": 16_000_000,
                                         "state_tax_cents": None, "state_agi_cents": None}, 1, AT)
    db.commit()
    assert figs == ReturnFigures(1_500_000, 16_000_000, None, None) == store.read_return(db, 2025)
    store.write_return(db, 2025, {}, 1, AT)
    db.commit()
    assert store.read_return(db, 2025) is None


@pytest.mark.parametrize("body", [{"federal_tax_cents": -1}, {"federal_tax_cents": True}, {"federal_tax_cents": "12"},
                                  {"federal_tax_cents": 10_000_000_001}, {"other": 1}, []])
def test_bad_return_figures_are_refused_and_nothing_is_written(db, body):
    store.write_return(db, 2025, {"federal_tax_cents": 100}, 1, AT)
    db.commit()
    with pytest.raises(StoreError):
        store.write_return(db, 2025, body, 1, AT)
    db.rollback()
    assert store.read_return(db, 2025) == ReturnFigures(federal_tax_cents=100)


def test_withholding_round_trip_and_its_date_rules(db):
    w = store.write_withholding(db, 2026, {"federal_ytd_cents": 1_200_000, "state_ytd_cents": 400_000,
                                           "as_of": "2026-09-30"}, today=TODAY, user_id=1, at=AT)
    db.commit()
    assert w == Withholding(1_200_000, 400_000, date(2026, 9, 30)) == store.read_withholding(db, 2026)
    for bad in ("2025-12-31", "2026-10-14", "not a date"):
        with pytest.raises(StoreError):
            store.write_withholding(db, 2026, {"federal_ytd_cents": 1, "state_ytd_cents": 1, "as_of": bad},
                                    today=TODAY, user_id=1, at=AT)
    with pytest.raises(StoreError):
        store.write_withholding(db, 2026, {"federal_ytd_cents": 1, "as_of": "2026-09-30"}, today=TODAY, user_id=1, at=AT)


def test_a_pay_stub_dated_after_the_tax_year_is_refused_and_the_saved_row_stays(db):
    # January 5, 2027: the card still shows 2026 and its January 15 payment. A 2027 stub carries 2027's pay only
    # (wages and withholding are reported by pay date), so it can never be 2026's withholding (final review I1).
    jan = date(2027, 1, 5)
    saved = store.write_withholding(db, 2026, {"federal_ytd_cents": 1_600_000, "state_ytd_cents": 500_000,
                                               "as_of": "2026-12-18"}, today=jan, user_id=1, at=AT)
    db.commit()
    with pytest.raises(StoreError) as e:
        store.write_withholding(db, 2026, {"federal_ytd_cents": 60_000, "state_ytd_cents": 20_000,
                                           "as_of": "2027-01-02"}, today=jan, user_id=1, at=AT)
    assert str(e.value) == "Enter the pay date from a 2026 pay stub, not in the future."
    db.rollback()
    assert store.read_withholding(db, 2026) == saved
    w = store.write_withholding(db, 2026, {"federal_ytd_cents": 1_700_000, "state_ytd_cents": 520_000,
                                           "as_of": "2026-12-31"}, today=jan, user_id=1, at=AT)
    assert w.as_of == date(2026, 12, 31)


def test_payment_marks_email_switches_and_sent_marks(db):
    store.mark_payment(db, 7, False, 1, AT)
    store.mark_payment(db, 8, False, 1, AT)
    store.mark_payment(db, 8, True, 1, AT)
    assert store.not_estimates(db) == {7}
    assert store.email_on(db, 3) is False and store.email_users(db) == []      # off by default
    store.set_email(db, 3, True, AT)
    store.set_email(db, 4, True, AT)
    store.set_email(db, 4, False, AT)
    assert store.email_on(db, 3) is True and store.email_users(db) == [3]
    assert store.sent_mark(db, date(2027, 1, 15)) is None
    store.put_sent_mark(db, date(2027, 1, 15), {"status": "sent", "tries": 1, "sent_to": [3]}, AT)
    db.commit()
    assert store.sent_mark(db, date(2027, 1, 15)) == {"status": "sent", "tries": 1, "sent_to": [3]}
