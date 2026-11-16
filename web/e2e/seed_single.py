"""e2e: a household of one beside the demo (spec 2026-11-05, section 7, "A single-person household test"). One
fictional person, Casey Moreau, is the only member, and manager, of the household book "Solo"; nobody else is in it
and Casey is in no other book, so no other spec sees either. Run after seed_home.py.

An install has one household book and Steward refuses a second (the demo's "ours" is it), so "Solo" is made as an
older install might hold one: a book made the normal way, then marked household in the directory. Being a later
household book, it gives Casey no install authority (deps.install_manager counts the lowest id only)."""
from sqlalchemy.orm import Session

from steward.auth.users import create_user
from steward.books.owners import HOUSEHOLD_OWNER_NAMES, to_json
from steward.books.registry import open_books
from steward.books.service import create_book
from steward.db.directory_models import Book
from steward.settings import Settings

books = open_books(Settings())
with Session(books.directory) as ddb:
    u = create_user(ddb, "casey", "casey@example.com", "Casey Moreau", "pw-solo-demo-2026")
    ddb.commit()
    info = create_book(books, ddb, name="Solo", kind="parent", owner_labels=["Casey Moreau"], managers=[u.id])
    row = ddb.get(Book, info.id)
    row.kind, row.owner_names = "household", to_json(HOUSEHOLD_OWNER_NAMES)
    ddb.commit()
books.dispose()
print("one-person household seeded")
