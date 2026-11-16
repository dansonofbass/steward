"""Figures derived from the vault's transactions (spec 2.5): the spending basis, the take-home surplus, the
yearly gift and consulting income. Cash accounts only (checking, savings, credit and the business ones); transfers
and the business share of a row never count."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from datetime import date

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from steward.db.models import Account, AccountType, Owner, ReimburseSettlement, Transaction

PERSONAL_OWNERS = (Owner.jr.value, Owner.spouse.value, Owner.joint.value)
BUSINESS_TYPES = (AccountType.business_checking, AccountType.business_credit)
# Personal cash-flow accounts. Investment and loan rows (401(k) payroll deferrals, dividends and reinvests) are
# modelled by the engine already, so counting them as money in or spending would double-count (narrows ruling 5).
CASH_FLOW_TYPES = (AccountType.checking, AccountType.savings, AccountType.credit)
WINDOW_MONTHS = 12
REPAYMENT = "reimbursement"   # reimbursable spec: a repayment's category


def month_add(first: date, n: int) -> date:
    idx = first.year * 12 + (first.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def months_between(a: date, b: date) -> int:
    return (b.year * 12 + b.month) - (a.year * 12 + a.month)


def window(today: date) -> tuple[date, date]:
    end = today.replace(day=1)
    return month_add(end, -WINDOW_MONTHS), end


def personal_clauses() -> tuple:
    """Rows with a personal share on the household's cash accounts. Business accounts are in too (final review ruling
    I1): their rows are business by default, so only a person's Personal or a split's personal share reaches here, and
    every row counts once, in the personal share, the business share or both split between them. Reimbursable spec,
    rule 1: a reimbursable charge (or a refund marked with it) and a repayment are the employer's money, not the
    household's, so neither reaches here and every figure built on these clauses leaves both out at once."""
    return (Account.type.in_(CASH_FLOW_TYPES + BUSINESS_TYPES), Transaction.is_business.is_(False),
            Transaction.is_transfer.is_(False), Transaction.reimburser_id.is_(None),
            Transaction.category != REPAYMENT)


def business_clauses() -> tuple:
    """Rows with a business share (business_pct above 0) on the household's cash accounts, with personal_clauses'
    exclusions, so the two sides of a book's cash flow by business count the same rows: no transfers, no reimbursable
    charges or their repayments, nothing on an investment or loan account."""
    return (Account.type.in_(CASH_FLOW_TYPES + BUSINESS_TYPES), Transaction.business_pct > 0,
            Transaction.is_transfer.is_(False), Transaction.reimburser_id.is_(None),
            Transaction.category != REPAYMENT)


def account_clauses(account_id: int) -> tuple:
    """One account's own rows, whatever its type (a business account too), at their whole amounts, with the Cash flow
    page's exclusions: no transfers, no reimbursable charges or their repayments (reimbursable spec, rule 1)."""
    return (Transaction.account_id == account_id, Transaction.is_transfer.is_(False),
            Transaction.reimburser_id.is_(None), Transaction.category != REPAYMENT)


def personal_amount():
    """A row's personal share (business plan ruling 1): the whole amount for a personal row, the amount less its
    business share for a split. Equal to steward.business.tagging.personal_share to the cent. Rows that are all
    business never get here (personal_clauses leaves them out)."""
    a, p = Transaction.amount_cents, Transaction.business_pct
    business = case((a >= 0, (a * p + 50) // 100), else_=-((-a * p + 50) // 100))
    return a - business


def settlements_by_month(db: Session, start: date, end: date) -> dict[str, dict[str, int]]:
    """Reimbursable spec, rule 2: each settled leftover is money out in its category, in the household month it was
    settled, over [start, end): {"2026-09": {"travel": 6000}}. The table holds a handful of rows, so it is read whole and
    bucketed here."""
    from steward import clock
    out: dict[str, dict[str, int]] = {}
    for at, category, cents in db.execute(select(ReimburseSettlement.settled_at, ReimburseSettlement.category,
                                                 ReimburseSettlement.amount_cents)):
        d = at.astimezone(clock.household_tz()).date()
        if start <= d < end:
            month = out.setdefault(f"{d.year:04d}-{d.month:02d}", {})
            month[category] = month.get(category, 0) + cents
    return out


def first_complete_month(db: Session) -> date | None:
    """First day of the first complete month of personal history (a book that starts on the 14th starts the next
    month); None for a book with no rows."""
    earliest = db.scalar(select(func.min(Transaction.posted_at))
                         .join(Account, Account.id == Transaction.account_id).where(*personal_clauses()))
    if earliest is None:
        return None
    return earliest if earliest.day == 1 else month_add(earliest.replace(day=1), 1)


def counted_start(db: Session, today: date) -> date | None:
    """First day of the first complete month of personal history inside the window; None if there is none."""
    start, end = window(today)
    first = first_complete_month(db)
    if first is None:
        return None
    first = max(first, start)
    return first if first < end else None


def complete_months(db: Session, today: date) -> int:
    start = counted_start(db, today)
    return 0 if start is None else months_between(start, window(today)[1])


ESCROW_YEARLY_SHARE = 0.02      # taxes and insurance run well under 2% of a home's value a year


@dataclass(frozen=True)
class Flows:
    months: int                  # complete months behind the figures, 0-12
    start: date | None           # first day counted
    end: date                    # first day of the current month (exclusive)
    money_in_cents: int          # over the counted months, the gift left out
    money_out_cents: int         # over the counted months: other Taxes left out, matched property tax kept, payments matched to a one-off left out, mortgage debits still in
    mortgage_paid_cents: int     # principal and interest over the counted months
    spending_basis_cents: int    # yearly
    surplus_cents: int           # yearly; may be negative
    gift_12mo_cents: int
    consulting_12mo_cents: int


def _sum(expr):
    return func.coalesce(func.sum(expr), 0)


def derive_flows(db: Session, today: date, mortgage_monthly_cents: int = 0, payoff: date | None = None,
                  home_value_cents: int | None = None) -> Flows:
    w_start, end = window(today)
    in_window = (Transaction.posted_at >= w_start, Transaction.posted_at < end)
    pa = personal_amount()
    gift = db.scalar(select(_sum(pa)).join(Account, Account.id == Transaction.account_id)
                     .where(*in_window, *personal_clauses(), Transaction.amount_cents > 0, Transaction.category == "gifts"))
    consulting = db.scalar(select(_sum(Transaction.amount_cents)).join(Account, Account.id == Transaction.account_id)
                           .where(*in_window, Account.type.in_(BUSINESS_TYPES), Transaction.amount_cents > 0,
                                  Transaction.business_pct > 0, Transaction.category == "business_income"))
    start = counted_start(db, today)
    if start is None:
        return Flows(0, None, end, 0, 0, 0, 0, 0, int(gift), int(consulting))
    months = months_between(start, end)
    from steward.services.setasides import history_ids          # setasides imports this module; the cycle is broken here
    kept_tax, one_off = history_ids(db)
    out_rows = [Transaction.amount_cents < 0]
    # Phase 11c (decisions 9 and 17): taxes are the engine's to work out, except property tax matched to a set-aside;
    # a payment matched to a one-off is the Plan's in its own year, not history.
    out_rows.append(or_(Transaction.category != "taxes", Transaction.id.in_(kept_tax)) if kept_tax else Transaction.category != "taxes")
    if one_off:
        out_rows.append(Transaction.id.not_in(one_off))
    money_in, money_out = db.execute(
        select(_sum(case((and_(Transaction.amount_cents > 0, Transaction.category.not_in(("gifts", REPAYMENT))), pa), else_=0)),
               _sum(case((and_(*out_rows), -pa), else_=0)))
        .join(Account, Account.id == Transaction.account_id)
        .where(Transaction.posted_at >= start, Transaction.posted_at < end, *personal_clauses())).one()
    # Rule 2: a settled leftover is the household's spending in the month it was settled.
    money_out = int(money_out) + sum(c for m in settlements_by_month(db, start, end).values() for c in m.values())
    pi_end = end if payoff is None else min(end, payoff.replace(day=1))
    mortgage_paid = mortgage_monthly_cents * max(0, months_between(start, pi_end))
    peer, peer_account = aliased(Transaction), aliased(Account)
    sent = db.execute(
        select(-Transaction.amount_cents, Transaction.is_business)
        .join(Account, Account.id == Transaction.account_id)
        .join(peer, peer.id == Transaction.transfer_peer_id)
        .join(peer_account, peer_account.id == peer.account_id)
        .where(Transaction.posted_at >= start, Transaction.posted_at < pi_end, Transaction.is_transfer.is_(True),
               Transaction.amount_cents < 0, Account.owner.in_(PERSONAL_OWNERS),
               Account.type.not_in(BUSINESS_TYPES), peer_account.type == AccountType.mortgage)).all()
    # A transfer over 3 times principal and interest is a payoff, not a payment: no escrow, and not counted as paid.
    sent = [(c, biz) for c, biz in sent if c <= 3 * mortgage_monthly_cents]
    # A business row isn't in money_out, so it isn't subtracted again as paid, and it carries no escrow into spending.
    paired = sum(c for c, _ in sent)
    unpaired = max(0, mortgage_paid - paired)
    sent = [c for c, biz in sent if not biz]
    # Escrow is what a payment carries beyond principal and interest. A one-off extra is capped at the household's
    # typical escrow, and the total at 2% of the home's value a year.
    excess = [max(0, c - mortgage_monthly_cents) for c in sent]
    usual = [e for e in excess if e > 0]
    typical = int(median(usual)) if usual else 0
    escrow = sum(min(e, typical) for e in excess)
    if home_value_cents:
        escrow = min(escrow, int(home_value_cents * ESCROW_YEARLY_SHARE * months / 12))
    basis = max(0, int(money_out) - unpaired + escrow)
    surplus = int(money_in) - basis - mortgage_paid
    return Flows(months, start, end, int(money_in), int(money_out), mortgage_paid,
                 int(round(basis * 12 / months)), int(round(surplus * 12 / months)), int(gift), int(consulting))
