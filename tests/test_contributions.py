"""Leftovers #12 (cash-flow and tax spec section 6): only tagged transfers into an account count as money put in.
Dividends, interest, sale proceeds and fees never do; a rollover or a Roth conversion is not new money."""
from datetime import date

from steward.services.contributions import contributions
from tests.factories import make_account, make_txn

YEAR = (date(2026, 1, 1), date(2027, 1, 1))


def pair(db, a, b):
    a.transfer_peer_id, b.transfer_peer_id = b.id, a.id
    db.commit()


def test_only_transfers_count_as_contributions(db):
    chk = make_account(db, "Checking", type="checking")
    roth = make_account(db, "Roth IRA", type="roth_ira", owner="jr")
    out = make_txn(db, chk, date(2026, 3, 1), -50_000, "TRANSFER TO ROTH", category="transfer", is_transfer=True)
    inn = make_txn(db, roth, date(2026, 3, 1), 50_000, "TRANSFER FROM CHECKING", category="transfer", is_transfer=True)
    pair(db, out, inn)
    make_txn(db, roth, date(2026, 4, 1), 70_000, "IRA CONTRIBUTION", category="transfer", is_transfer=True)  # unpaired
    make_txn(db, roth, date(2026, 5, 1), 12_345, "DIVIDEND VTI", category="income")
    make_txn(db, roth, date(2026, 6, 1), 900_000, "SOLD VTI", category="uncategorized")
    make_txn(db, roth, date(2026, 6, 2), 4_321, "INTEREST", category="interest")
    make_txn(db, roth, date(2026, 7, 1), -2_000, "FEE", category="fees")
    assert contributions(db, [roth.id], *YEAR) == 120_000


def test_rollovers_and_conversions_are_not_contributions(db):
    trad = make_account(db, "Traditional IRA", type="traditional_ira", owner="jr")
    roth = make_account(db, "Roth IRA", type="roth_ira", owner="jr")
    k401 = make_account(db, "Old 401(k)", type="k401", owner="jr")
    a = make_txn(db, trad, date(2026, 2, 1), -600_000, "CONVERSION", category="transfer", is_transfer=True)
    b = make_txn(db, roth, date(2026, 2, 1), 600_000, "CONVERSION", category="transfer", is_transfer=True)
    pair(db, a, b)
    c = make_txn(db, k401, date(2026, 3, 1), -2_000_000, "ROLLOVER", category="transfer", is_transfer=True)
    d = make_txn(db, trad, date(2026, 3, 1), 2_000_000, "ROLLOVER", category="transfer", is_transfer=True)
    pair(db, c, d)
    assert contributions(db, [roth.id], *YEAR) == 0
    assert contributions(db, [trad.id], *YEAR) == 0


def test_the_window_starts_inclusive_and_ends_exclusive(db):
    hsa = make_account(db, "HSA", type="hsa", owner="jr")
    make_txn(db, hsa, date(2025, 12, 31), 10_000, "HSA CONTRIBUTION", category="transfer", is_transfer=True)
    make_txn(db, hsa, date(2026, 1, 1), 20_000, "HSA CONTRIBUTION", category="transfer", is_transfer=True)
    make_txn(db, hsa, date(2026, 10, 14), 40_000, "HSA CONTRIBUTION", category="transfer", is_transfer=True)
    assert contributions(db, [hsa.id], date(2026, 1, 1), date(2026, 10, 14)) == 20_000


def test_no_history_is_none_not_zero(db):
    roth = make_account(db, "Roth IRA", type="roth_ira", owner="jr")
    assert contributions(db, [], *YEAR) is None
    assert contributions(db, [roth.id], *YEAR) is None
    make_txn(db, roth, date(2026, 5, 1), 12_345, "DIVIDEND VTI", category="income")
    assert contributions(db, [roth.id], *YEAR) == 0


def test_a_move_between_two_taxable_brokerage_accounts_is_not_new_money(db):
    """Final review minor d."""
    chk = make_account(db, "Checking", type="checking")
    old = make_account(db, "Old brokerage", type="brokerage_taxable", owner="joint")
    new = make_account(db, "New brokerage", type="brokerage_taxable", owner="joint")
    a = make_txn(db, old, date(2026, 4, 1), -1_000_000, "ACAT OUT", category="transfer", is_transfer=True)
    b = make_txn(db, new, date(2026, 4, 1), 1_000_000, "ACAT IN", category="transfer", is_transfer=True)
    pair(db, a, b)
    c = make_txn(db, chk, date(2026, 5, 1), -250_000, "TRANSFER TO BROKERAGE", category="transfer", is_transfer=True)
    d = make_txn(db, new, date(2026, 5, 1), 250_000, "TRANSFER FROM CHECKING", category="transfer", is_transfer=True)
    pair(db, c, d)
    assert contributions(db, [old.id, new.id], *YEAR) == 250_000
