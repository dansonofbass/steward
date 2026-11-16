"""Money put into an account (leftovers #12; cash-flow and tax spec section 6).

Only transactions tagged as transfers count (paired by steward.services.transfers, or tagged by a rule or a person, such
as the built-in "IRA CONTRIBUTION" rule), so dividends, interest, sale proceeds, fees and an employer's own deposits
never look like contributions. A transfer whose other side is another retirement or HSA account is a rollover or a
Roth conversion, not new money, and doesn't count either; nor does a move between two taxable brokerage accounts
(final review minor d)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from steward.db.models import Account, AccountType, Transaction

TAX_ADVANTAGED: tuple[AccountType, ...] = (AccountType.k401, AccountType.traditional_ira, AccountType.roth_ira,
                                           AccountType.hsa)


def contributions(db: Session, ids: list[int], start: date, end: date) -> int | None:
    """Transfers into these accounts over [start, end), in cents; None when the accounts have no transactions at all."""
    if not ids or not db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id.in_(ids))):
        return None
    peer = aliased(Transaction)
    peer_account = aliased(Account)
    own = aliased(Account)
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .select_from(Transaction)
        .join(own, own.id == Transaction.account_id)
        .outerjoin(peer, peer.id == Transaction.transfer_peer_id)
        .outerjoin(peer_account, peer_account.id == peer.account_id)
        .where(Transaction.account_id.in_(ids), Transaction.posted_at >= start, Transaction.posted_at < end,
               Transaction.amount_cents > 0, Transaction.is_transfer.is_(True),
               or_(peer_account.id.is_(None),
                   and_(peer_account.type.not_in(TAX_ADVANTAGED),
                        or_(own.type != AccountType.brokerage_taxable,
                            peer_account.type != AccountType.brokerage_taxable)))))
    return int(total)
