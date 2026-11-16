"""e2e: history for Setting aside in the demo household (phase 11c). Two Big Mutual payments a year apart (a yearly
suggestion), four HOA payments six months apart (twice a year), one county tax payment (the county rule), a savings
account to link, and a plumber's bill last month to match by hand. Nothing is set aside: the first visit's notice
shows. Fictional amounts only. Run after seed_spending.py."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.books.people import attach_people
from steward.books.registry import open_books
from steward.db.models import Account, AccountType, BalanceSnapshot, CategorySource, Institution, Owner, Source, Transaction
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
today = deps.today()
with Session(books.engine_for(ours)) as db:
    attach_people(db, lambda: books.people(ours.id))
    chk = db.scalar(select(Account).where(Account.type == AccountType.checking).order_by(Account.id))
    manual = db.scalar(select(Institution).where(Institution.source == Source.manual))
    if manual is None:
        manual = Institution(name="Manual", source=Source.manual)
        db.add(manual)
        db.flush()
    house = Account(institution_id=manual.id, name="House Fund", type=AccountType.savings, owner=Owner.joint, source=Source.manual)
    db.add(house)
    db.flush()
    db.add(BalanceSnapshot(account_id=house.id, as_of=today, balance_cents=410_000))
    rows = [(today - timedelta(days=380), -138_000, "BIG MUTUAL INS", "Big Mutual", "insurance"),
            (today - timedelta(days=15), -138_000, "BIG MUTUAL INS", "Big Mutual", "insurance"),
            (today - timedelta(days=40), -421_000, "COUNTY TAX COLLECTOR", "County Tax Collector", "taxes"),
            (today - timedelta(days=35), -235_000, "DALES PLUMBING", "Dale's Plumbing", "home")]
    rows += [(today - timedelta(days=d), -45_000, "MAPLE COURT HOA", "Maple Court HOA", "housing") for d in (15, 197, 380, 562)]
    for i, (d, cents, raw, merchant, category) in enumerate(rows):
        db.add(Transaction(account_id=chk.id, posted_at=d, amount_cents=cents, raw_description=raw, merchant=merchant,
                           category=category, category_source=CategorySource.rule, external_id=f"e2e-setaside-{i}"))
    db.commit()
books.dispose()
print("set-aside fixtures seeded")
