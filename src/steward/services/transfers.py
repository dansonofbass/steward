from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, CategorySource, Transaction

WINDOW_DAYS = 5   # phase 12 decision 9: a card payment can take a working week to post
# A payment from checking to a loan is spending, like the mortgage under Housing (JR, Oct 28): the checking side is a
# Loan payment, the loan's own side a transfer, so the money is counted once.
LOAN_PAYMENT = "loan_payments"
PAIRABLE_CHOICES = ("transfer", LOAN_PAYMENT)


def _candidate(db: Session, t: Transaction) -> Transaction | None:
    lo, hi = t.posted_at - timedelta(days=WINDOW_DAYS), t.posted_at + timedelta(days=WINDOW_DAYS)
    rows = db.scalars(
        select(Transaction).where(
            Transaction.account_id != t.account_id,
            Transaction.amount_cents == -t.amount_cents,
            Transaction.posted_at >= lo, Transaction.posted_at <= hi,
            Transaction.transfer_peer_id.is_(None),
            # The user's decision outranks pairing: a row they sorted is a candidate only if they called it a transfer or
            # a loan payment, and then only its link is set, never its category (_mark).
            or_(Transaction.category_source != CategorySource.correction, Transaction.category.in_(PAIRABLE_CHOICES)),
        )
    ).all()
    if not rows:
        return None
    return min(rows, key=lambda c: (abs((c.posted_at - t.posted_at).days), c.id))


def pair_transfers(db: Session, txn_ids: list[int]) -> int:
    """Pair each given transaction with an opposite-amount one in another account; return pairs made. A row whose
    category a person set (or a rule they made by correcting one) keeps it: the user's decision outranks pairing on
    either side. Such a row pairs at all only when they called it a transfer or a loan payment."""
    made = 0
    for tid in txn_ids:
        t = db.get(Transaction, tid)
        if t is None or t.transfer_peer_id is not None or t.amount_cents == 0:
            continue
        if t.category_source == CategorySource.correction and t.category not in PAIRABLE_CHOICES:
            continue
        peer = _candidate(db, t)
        if peer is None:
            continue
        _mark(t, peer, t.amount_cents < 0 and _is_loan(db, peer.account_id) and not _is_loan(db, t.account_id))
        _mark(peer, t, peer.amount_cents < 0 and _is_loan(db, t.account_id) and not _is_loan(db, peer.account_id))
        db.flush()
        made += 1
    return made


def _is_loan(db: Session, account_id: int) -> bool:
    a = db.get(Account, account_id)
    return a is not None and a.type == AccountType.loan


def _mark(t: Transaction, peer: Transaction, pays_a_loan: bool = False) -> None:
    """Pair t with peer: a transfer, or when t pays a loan from another account, a Loan payment (spending). A row a
    person sorted gets only the link."""
    t.transfer_peer_id = peer.id
    if t.category_source == CategorySource.correction:
        return
    t.category_source = CategorySource.rule
    t.guess_category = t.guess_pct = None
    t.is_transfer, t.category = (False, LOAN_PAYMENT) if pays_a_loan else (True, "transfer")


def account_type_changed(db: Session, account: Account, was: AccountType) -> int:
    """An account became a loan, or stopped being one: the paired payments into it follow (a Loan payment while it's a
    loan, a transfer otherwise). Rows a person categorized are left as they are. Returns rows changed."""
    now_loan, was_loan = account.type == AccountType.loan, was == AccountType.loan
    if now_loan == was_loan:
        return 0
    loan_side = select(Transaction.id).where(Transaction.account_id == account.id, Transaction.transfer_peer_id.is_not(None))
    peers = select(Transaction.transfer_peer_id).where(Transaction.id.in_(loan_side))
    category, is_transfer = (LOAN_PAYMENT, False) if now_loan else ("transfer", True)
    result = db.execute(update(Transaction).where(
        Transaction.id.in_(peers), Transaction.category_source != CategorySource.correction,
        Transaction.category.in_(("transfer", LOAN_PAYMENT)), Transaction.amount_cents < 0,   # money paid to the loan
    ).values(category=category, is_transfer=is_transfer, category_source=CategorySource.rule))
    db.flush()
    return result.rowcount or 0


def unpair_peers(db: Session, ids: list[int]) -> None:
    """Rows whose transfer peer is in `ids` lose the link. One a person sorted keeps their category (their decision
    outranks pairing); the rest go back to unsorted, as if never paired, so Review shows them and the catch-up asks."""
    if not ids:
        return
    db.execute(update(Transaction).where(Transaction.transfer_peer_id.in_(ids),
                                         Transaction.category_source == CategorySource.correction)
               .values(transfer_peer_id=None))
    db.execute(update(Transaction).where(Transaction.transfer_peer_id.in_(ids))
               .values(is_transfer=False, category="uncategorized", category_source=CategorySource.none,
                       transfer_peer_id=None, reviewed_at=None, guess_category=None, guess_pct=None,
                       model_asked_at=None))
