"""A tag is a percent (ruling 1): shares add up to the amount, is_business means 100%, a person's choice is manual,
and a tag never touches the category (spec 5)."""
from datetime import date

import pytest

from steward.business.tagging import NOT_FOR_TRANSFERS, TagError, personal_share, set_business, share
from steward.db.models import CategorySource
from tests.factories import make_account, make_txn


@pytest.mark.parametrize("amount", [-1, -3, -999, -1_001, -12_345, 1, 7, 10_001, -2_900])
@pytest.mark.parametrize("pct", [0, 1, 33, 50, 67, 99, 100])
def test_shares_add_up_to_the_amount(amount, pct):
    business = share(amount, pct)
    personal = personal_share(amount, pct)
    assert business + personal == amount
    assert share(amount, 100) == amount and share(amount, 0) == 0
    assert (business <= 0) if amount < 0 else (business >= 0)


def test_split_rounding_is_half_away_from_zero():
    assert share(-1_001, 50) == -501 and share(1_001, 50) == 501 and share(-1, 50) == -1


def test_set_business_keeps_the_category_and_is_business_means_all(db):
    t = make_txn(db, make_account(db), date(2026, 10, 1), -10_000, "COWORK SPACE LLC", merchant="Cowork Space",
                 category="business_expense", category_source=CategorySource.rule)
    set_business(t, 40, source="manual", line="office")
    assert (t.business_pct, t.is_business, t.business_source, t.business_line) == (40, False, "manual", "office")
    set_business(t, 100, source="rule")
    assert (t.is_business, t.business_line, t.business_source) == (True, "office", "rule")   # KEEP keeps the line
    set_business(t, 0, source="manual")
    assert (t.business_pct, t.is_business, t.business_line, t.business_source) == (0, False, None, "manual")
    set_business(t, 0, source="rule")
    assert t.business_source == "none"         # a rule that says personal leaves no mark
    assert (t.category, t.category_source, t.reviewed_at) == ("business_expense", CategorySource.rule, None)


def test_bad_values_and_transfers(db):
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 1), -5_000, "X")
    for bad in (-1, 101):
        with pytest.raises(TagError):
            set_business(t, bad, source="manual")
    with pytest.raises(TagError):
        set_business(t, 50, source="manual", line="yacht")
    x = make_txn(db, a, date(2026, 10, 1), -5_000, "TRANSFER TO SAVINGS", category="transfer", is_transfer=True)
    with pytest.raises(TagError) as e:
        set_business(x, 100, source="manual")
    assert str(e.value) == NOT_FOR_TRANSFERS
    set_business(x, 0, source="manual")        # saying a transfer is personal is harmless
