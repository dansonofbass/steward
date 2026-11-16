from datetime import date

from steward.db.models import CategorySource
from steward.deps import now
from steward.services.ingest import ingest_rows
from steward.services.importers.base import ParsedRow
from steward.services.transfers import pair_transfers, unpair_peers
from tests.factories import make_account, make_txn


def test_pairs_closest_date_across_accounts_only(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -100000, "TRANSFER TO SAVINGS")
    far = make_txn(db, sav, date(2026, 10, 8), 100000, "TRANSFER FROM CHECKING")
    near = make_txn(db, sav, date(2026, 10, 6), 100000, "TRANSFER FROM CHECKING")
    same = make_txn(db, chk, date(2026, 10, 5), 100000, "REVERSAL")  # same account: never a peer
    assert pair_transfers(db, [out.id]) == 1
    db.commit()
    for t in (out, near, far, same):
        db.refresh(t)
    assert out.transfer_peer_id == near.id and near.transfer_peer_id == out.id
    assert out.is_transfer and near.is_transfer and out.category == near.category == "transfer"
    assert not far.is_transfer and not same.is_transfer


def test_outside_window_or_already_paired_not_matched(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -100000, "X")
    late = make_txn(db, sav, date(2026, 10, 11), 100000, "Y")     # 6 days: outside the 5-day window (phase 12 decision 9)
    assert pair_transfers(db, [out.id]) == 0
    other = make_txn(db, sav, date(2026, 10, 5), 100000, "Z", is_transfer=True, category="transfer")
    other.transfer_peer_id = late.id  # already paired with something else
    db.commit()
    assert pair_transfers(db, [out.id]) == 0


def test_card_payment_pair(db):
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    pay = make_txn(db, chk, date(2026, 10, 20), -54321, "PAYMENT TO REWARDS CARD")
    thanks = make_txn(db, card, date(2026, 10, 21), 54321, "PAYMENT THANK YOU")
    assert pair_transfers(db, [thanks.id]) == 1


def test_description_flagged_unpaired_row_is_a_candidate(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    (s_row,) = ingest_rows(db, sav, [ParsedRow(date(2026, 10, 5), 100000, "TRANSFER FROM CHECKING", None)],
                           batch=None, now=now(), model=None)
    assert s_row.is_transfer and s_row.transfer_peer_id is None
    (c_row,) = ingest_rows(db, chk, [ParsedRow(date(2026, 10, 5), -100000, "TRANSFER TO SAVINGS", None)],
                           batch=None, now=now(), model=None)
    db.commit()
    assert c_row.transfer_peer_id == s_row.id and s_row.transfer_peer_id == c_row.id
    assert s_row.category == "transfer" and s_row.category_source == CategorySource.rule


def test_corrected_row_is_never_a_candidate(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -100, "X")
    fixed = make_txn(db, sav, date(2026, 10, 5), 100, "Y", category="income",
                     category_source=CategorySource.correction)
    fixed.reviewed_at = now(); db.commit()
    stamp = fixed.reviewed_at
    assert pair_transfers(db, [out.id]) == 0
    db.refresh(fixed)
    assert not fixed.is_transfer and fixed.category == "income" and fixed.reviewed_at == stamp


def test_pairing_leaves_candidate_reviewed_at_alone(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -100, "X")
    peer = make_txn(db, sav, date(2026, 10, 5), 100, "Y")
    assert pair_transfers(db, [out.id]) == 1
    assert peer.reviewed_at is None and out.reviewed_at is None


def test_a_category_a_person_set_is_never_paired_over(db):
    """The user's decision outranks pairing on either side: a row they sorted as something else never pairs."""
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    mine = make_txn(db, chk, date(2026, 10, 5), -4500, "DINNER WITH THE SMITHS", category="dining",
                    category_source=CategorySource.correction)
    other = make_txn(db, sav, date(2026, 10, 5), 4500, "DEPOSIT")
    assert pair_transfers(db, [mine.id]) == 0
    assert pair_transfers(db, [other.id]) == 0
    db.commit()
    db.refresh(mine)
    assert (mine.category, mine.is_transfer, mine.transfer_peer_id) == ("dining", False, None)


def test_a_loan_payment_a_person_sorted_still_pairs_and_keeps_its_category(db):
    """Final review 5: after JR sorts the car payment as a Loan payment, the loan account's side of each payment is
    still a transfer (not a monthly Review row); his row keeps the category he chose, in either order of arrival."""
    chk = make_account(db, "Checking")
    car = make_account(db, "Car", type="unknown", institution_name="Lender")
    for first_mine in (True, False):
        day = date(2026, 10, 5) if first_mine else date(2026, 11, 5)
        mine = make_txn(db, chk, day, -45000, "HARTWELL CAR CREDIT", category="loan_payments",
                        category_source=CategorySource.correction)
        theirs = make_txn(db, car, day, 45000, "PAYMENT RECEIVED")
        assert pair_transfers(db, [mine.id if first_mine else theirs.id]) == 1
        db.commit()
        db.refresh(mine)
        db.refresh(theirs)
        assert (mine.category, mine.is_transfer, mine.transfer_peer_id) == ("loan_payments", False, theirs.id)
        assert (theirs.category, theirs.is_transfer, theirs.transfer_peer_id) == ("transfer", True, mine.id)


def test_money_a_loan_pays_in_is_a_transfer_not_a_loan_payment(db):
    """Final review 1: a loan's funding (or a refund) arriving in checking would otherwise count as money in."""
    chk = make_account(db, "Checking")
    loan = make_account(db, "Student loan", type="loan", institution_name="Lender")
    funded = make_txn(db, chk, date(2026, 9, 1), 1_000_000, "LOAN PROCEEDS")
    out = make_txn(db, loan, date(2026, 9, 1), -1_000_000, "DISBURSEMENT")
    assert pair_transfers(db, [funded.id]) == 1
    db.commit()
    db.refresh(funded)
    db.refresh(out)
    assert (funded.category, funded.is_transfer) == ("transfer", True)
    assert (out.category, out.is_transfer) == ("transfer", True)


def test_a_payment_to_a_loan_account_is_a_loan_payment_and_the_loan_side_a_transfer(db):
    """JR, Oct 28: a connected car loan's payment is spending (a fixed cost, like the mortgage), counted once."""
    chk = make_account(db, "Checking")
    car = make_account(db, "Car loan", type="loan", institution_name="Lender")
    out = make_txn(db, chk, date(2026, 10, 5), -45000, "ONLINE PMT CAR LOAN")
    into = make_txn(db, car, date(2026, 10, 6), 45000, "PAYMENT RECEIVED")
    assert pair_transfers(db, [out.id]) == 1
    db.commit()
    db.refresh(out)
    db.refresh(into)
    assert (out.category, out.is_transfer, out.transfer_peer_id) == ("loan_payments", False, into.id)
    assert (into.category, into.is_transfer, into.transfer_peer_id) == ("transfer", True, out.id)


def test_setting_an_account_to_loan_turns_its_paired_payments_into_loan_payments_and_back(client, db):
    from tests.factories import make_user
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})
    chk = make_account(db, "Checking")
    car = make_account(db, "Acct 9999", type="unknown", institution_name="Lender")
    out = make_txn(db, chk, date(2026, 10, 5), -45000, "ONLINE PMT")
    into = make_txn(db, car, date(2026, 10, 6), 45000, "PAYMENT RECEIVED")
    pair_transfers(db, [out.id])
    db.commit()
    db.refresh(out)
    assert out.category == "transfer"            # an account with no type yet: a plain transfer
    assert client.patch(f"/api/b/ours/accounts/{car.id}", json={"type": "loan"}).status_code == 200
    db.commit()   # end the test session's read so it sees what the request wrote
    db.refresh(out)
    db.refresh(into)
    assert (out.category, out.is_transfer, into.category) == ("loan_payments", False, "transfer")
    assert client.patch(f"/api/b/ours/accounts/{car.id}", json={"type": "credit"}).status_code == 200
    db.commit()   # end the test session's read so it sees what the request wrote
    db.refresh(out)
    assert (out.category, out.is_transfer) == ("transfer", True)


def test_a_card_payment_four_days_apart_pairs(db):
    """Phase 12 decision 9: a card payment can post four or five days after it left checking."""
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE CREDIT CRD AUTOPAY")
    back = make_txn(db, card, date(2026, 10, 10), 40000, "AUTOPAY PAYMENT - THANK YOU")
    assert pair_transfers(db, [out.id]) == 1
    db.commit()
    db.refresh(back)
    assert back.transfer_peer_id == out.id


def test_pairing_clears_the_guess_on_both_rows(db):
    chk = make_account(db, "Checking")
    sav = make_account(db, "Savings", type="savings", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -100000, "TRANSFER TO SAVINGS")
    inn = make_txn(db, sav, date(2026, 10, 6), 100000, "TRANSFER FROM CHECKING")
    for t in (out, inn):
        t.guess_category, t.guess_pct = "home", 45
    db.commit()
    assert pair_transfers(db, [out.id]) == 1
    db.commit()
    for t in (out, inn):
        db.refresh(t)
        assert (t.guess_category, t.guess_pct) == (None, None)


def test_an_unpaired_side_goes_back_as_never_asked_so_the_catch_up_sees_it(db):
    """An undone import or a removed row: the other side is pending again, not "Steward looked and couldn't tell"."""
    from datetime import datetime, timezone
    from steward.services.catchup import pending_count
    chk = make_account(db, "Checking")
    card = make_account(db, "Card", type="credit", institution_name="Other")
    out = make_txn(db, chk, date(2026, 10, 5), -40000, "CHASE EPAY 0042")
    back = make_txn(db, card, date(2026, 10, 7), 40000, "PAYMENT RECEIVED")
    back.model_asked_at = datetime(2026, 10, 7, tzinfo=timezone.utc)      # asked at its import, then paired
    assert pair_transfers(db, [out.id]) == 1
    assert back.is_transfer
    unpair_peers(db, [out.id])
    db.commit()
    db.refresh(back)
    assert (back.category, back.category_source, back.is_transfer, back.transfer_peer_id, back.model_asked_at) == (
        "uncategorized", CategorySource.none, False, None, None)
    at = datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert pending_count(db, at) == 1           # back; out keeps its transfer (it is the row being removed)
