from collections.abc import Mapping
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, BalanceSnapshot, Fact, ImportBatch, Institution, Source


def manual_institution(db: Session) -> Institution:
    query = select(Institution).where(Institution.source == Source.manual)
    inst = db.scalars(query).one_or_none()
    if inst is None:
        inst = Institution(name="Manual", source=Source.manual)
        db.add(inst)
        try:
            db.flush()
        except IntegrityError:
            # A concurrent request created it first; the unique index guarantees one row.
            db.rollback()
            inst = db.scalars(query).one()
    return inst


def record_balance(db: Session, account_id: int, as_of: date, balance_cents: int) -> None:
    snap = db.get(BalanceSnapshot, (account_id, as_of))
    if snap is None:
        db.add(BalanceSnapshot(account_id=account_id, as_of=as_of, balance_cents=balance_cents))
    else:
        snap.balance_cents = balance_cents
    db.flush()


def latest_balance(db: Session, account_id: int) -> tuple[date, int] | None:
    snap = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account_id)
                     .order_by(BalanceSnapshot.as_of.desc()).limit(1))
    return (snap.as_of, snap.balance_cents) if snap else None


def import_kinds(db: Session) -> dict[int, str]:
    """Each account's newest import that wasn't undone, as a kind only: statement (a PDF statement's batch has pages)
    or file (CSV or OFX). Ask's accounts tool reads this, never the batch, so no file name or date reaches it (P12,
    install gate INS-17)."""
    rows = db.execute(select(ImportBatch.account_id, ImportBatch.pages).where(ImportBatch.rolled_back_at.is_(None))
                      .order_by(ImportBatch.imported_at, ImportBatch.id))
    return {aid: "statement" if pages is not None else "file" for aid, pages in rows}


def staleness_days(latest_as_of: date | None, today: date) -> int | None:
    return None if latest_as_of is None else (today - latest_as_of).days


def account_out(db: Session, a: Account, today: date, labels: Mapping[str, str]) -> dict:
    """`labels`: BookContext.owner_labels(), so the owner reads as a member's name or a role, never its key (#31)."""
    lb = latest_balance(db, a.id)
    return {
        "id": a.id, "name": a.name, "type": a.type.value, "owner": a.owner, "owner_label": labels.get(a.owner, a.owner),
        "source": a.source.value, "institution": a.institution.name, "is_active": a.is_active,
        "rate_bp": a.rate_bp, "advisory_fee_bp": a.advisory_fee_bp, "loan_id": a.loan_id,
        "balance_cents": lb[1] if lb else None, "as_of": lb[0].isoformat() if lb else None,
        "stale_days": staleness_days(lb[0] if lb else None, today),
    }


MORTGAGE_RATE_FACT = "mortgage.rate_bp"


def debt_rate_bp(a: Account, facts: Mapping[str, Fact]) -> float | None:
    """A card's or loan's yearly rate in basis points: the account's own rate (entered on the Plan screen) first, then,
    for a mortgage, the mortgage.rate_bp fact from Set up (final review minor a). None: not entered."""
    if a.rate_bp is not None:
        return float(a.rate_bp)
    f = facts.get(MORTGAGE_RATE_FACT)
    if a.type != AccountType.mortgage or f is None:
        return None
    try:
        return float(f.value)
    except ValueError:
        return None


def mortgage_rate_bp(db: Session, facts: Mapping[str, Fact]) -> float | None:
    """The household's mortgage rate: the first active mortgage account with a rate, else the fact."""
    for a in db.scalars(select(Account).where(Account.is_active.is_(True), Account.type == AccountType.mortgage)
                        .order_by(Account.id)):
        if a.rate_bp is not None:
            return float(a.rate_bp)
    f = facts.get(MORTGAGE_RATE_FACT)
    try:
        return float(f.value) if f is not None else None
    except ValueError:
        return None
