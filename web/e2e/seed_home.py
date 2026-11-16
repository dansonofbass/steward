"""e2e: Since you last looked for alex in the demo household (Home spec, e2e). alex's last full look was three days ago,
and after it Steward received a paycheck, a Bill and a large charge, so Home's Since lists them whatever day the suite
runs. The large charge is in Taxes (Once in a while), so no Flexible target moves and spending.spec's over line still
names only Gifts. Fictional names and amounts. Run after seed_notes.py."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.books.people import attach_people
from steward.books.registry import open_books
from steward.db.directory_models import User
from steward.db.models import Account, AccountType, CategorySource, HomeVisit, Transaction
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
today = deps.today()
with Session(books.directory) as ddb:
    alex_id = ddb.scalar(select(User.id).where(User.username == "alex"))
with Session(books.engine_for(ours)) as db:
    attach_people(db, lambda: books.people(ours.id))
    chk = db.scalar(select(Account).where(Account.type == AccountType.checking).order_by(Account.id))
    db.add(HomeVisit(user_id=alex_id, seen_at=deps.now() - timedelta(days=3)))
    # The permit payee matches none of the county, IRS or franchise-tax patterns, so the Taxes page's suggestions and
    # payments (setasides.spec, taxes.spec) are unchanged, and no e2e search (q=Dale, q=Maple, ...) finds it.
    for i, (cents, raw, merchant, category) in enumerate((
            (421_200, "NORTHWIND PAYROLL", "Northwind payroll", "income"),
            (-48_600, "CITY POWER", "City Power", "utilities"),
            (-190_000, "BRIARWOOD CITY PERMITS", "Briarwood city permits", "taxes"))):
        db.add(Transaction(account_id=chk.id, posted_at=today - timedelta(days=1), amount_cents=cents, raw_description=raw,
                           merchant=merchant, category=category, category_source=CategorySource.rule,
                           external_id=f"e2e-home-{i}"))
    db.commit()
books.dispose()
print("home fixtures seeded")
