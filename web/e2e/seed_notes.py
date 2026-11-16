"""e2e: three PayPal $13.99 charges and one $9.99 one on the demo household's checking account, sorted as
Subscriptions (so Review's queue and the Flexible targets are untouched), for the note form's "Also the 2 PayPal $13.99
ones" and a name that spreads (polish round, item 5). Fictional. Run after seed_same_account.py."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.books.people import attach_people
from steward.books.registry import open_books
from steward.db.models import Account, AccountType, CategorySource, Transaction
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
today = deps.today()
with Session(books.engine_for(ours)) as db:
    attach_people(db, lambda: books.people(ours.id))
    chk = db.scalar(select(Account).where(Account.type == AccountType.checking).order_by(Account.id))
    for i, (days, cents, raw) in enumerate(((3, -1399, "PAYPAL *DISNEYPLUS"), (33, -1399, "PAYPAL *DISNEYPLUS"),
                                            (63, -1399, "PAYPAL *DISNEYPLUS"), (10, -999, "PAYPAL *EBAY"))):
        db.add(Transaction(account_id=chk.id, posted_at=today - timedelta(days=days), amount_cents=cents, raw_description=raw,
                           merchant="PayPal", category="subscriptions", category_source=CategorySource.correction,
                           external_id=f"e2e-notes-{i}"))
    db.commit()
books.dispose()
print("note fixtures seeded")
