"""Last: every membership in the demo vault is welcomed, as d0008 leaves a live install, so the specs start on Home
(guided setup plan D4). The specs that need an unwelcomed person accept an invite at run time (seed_extra.py)."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from steward.books.registry import open_books
from steward.settings import Settings

books = open_books(Settings())
with Session(books.directory) as ddb:
    ddb.execute(text("UPDATE membership SET welcome_seen_at = created_at WHERE welcome_seen_at IS NULL"))
    ddb.commit()
books.dispose()
print("welcome marks set")
