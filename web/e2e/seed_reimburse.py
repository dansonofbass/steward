"""e2e: made-up work trips on the demo household's Rewards Card for the reimbursable spec, one per Playwright project
(Denver for the phone, Austin for the desktop, months apart so neither shows in the other's list). Each has a flight
booked weeks ahead, a hotel, a ride, a dinner, and a grocery run at a home merchant the household uses every month, and
a repayment deposit from Acme (fictional) into Checking. Dates are relative to today. Run after seed_setasides.py."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.books.registry import open_books
from steward.db.models import Account, CategorySource, Transaction
from steward.services.vault_flows import month_add
from steward.settings import Settings

TRIPS = {"DENVER CO": 45, "AUSTIN TX": 160}       # days back to each trip's first day

books = open_books(Settings())
ours = books.book("ours")
today = deps.today()
with Session(books.engine_for(ours)) as db:
    card = db.scalar(select(Account).where(Account.name == "Rewards Card"))
    chk = db.scalars(select(Account).where(Account.name == "Checking")).first()
    rows: list[tuple] = []
    first = today.replace(day=1)
    for i in range(1, 13):                        # the home merchant: the 12th of each of the last 12 months
        rows.append((card, month_add(first, -i).replace(day=12), -6_400, "MAPLE GROCER", "groceries"))
    for place, back in TRIPS.items():
        start, city = today - timedelta(days=back), place.split()[0]
        rows += [
            (card, start - timedelta(days=30), -42_000, f"UNITED AIRLINES {city}", "travel"),
            (card, start, -61_200, f"HOTEL TEATRO {place}", "travel"),
            (card, start + timedelta(days=1), -2_840, "UBER TRIP", "transport"),
            (card, start + timedelta(days=1), -6_400, "MAPLE GROCER", "groceries"),
            (card, start + timedelta(days=2), -5_580, f"LITTLE PIE SHOP {place}", "dining"),
            (chk, today - timedelta(days=back - 10), 105_000, f"ACME CORP EXPENSES {city}", "uncategorized"),
        ]
    for n, (account, day, cents, raw, category) in enumerate(rows):
        db.add(Transaction(account_id=account.id, posted_at=day, amount_cents=cents, raw_description=raw,
                           category=category, external_id=f"e2e-reimburse-{n}",
                           category_source=CategorySource.none if category == "uncategorized" else CategorySource.rule))
    db.commit()
books.dispose()
print("reimbursable fixtures seeded")
