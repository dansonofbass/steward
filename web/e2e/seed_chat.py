"""Chat people for the e2e suite (spec 11.5): per Playwright project, Cass and Dee, managers of Ours who have seen Set
up Steward. Fresh people per project, because the disclosure shows once per person per book and both projects share
the one demo server."""
from sqlalchemy.orm import Session

from steward import deps
from steward.auth.users import create_user
from steward.books.people import attach_people
from steward.books.registry import open_books
from steward.books.service import add_membership
from steward.db.models import UserSetup
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
made = []
with Session(books.directory) as ddb:
    for project in ("phone", "desktop"):
        for name, display in (("cass", "Cass"), ("dee", "Dee")):
            u = create_user(ddb, f"{name}-{project}", f"{name}-{project}@example.com", display, "pw-chat-demo-2026")
            add_membership(ddb, u.id, ours.id, "manager", by=None, note="e2e")
            made.append(u.id)
    ddb.commit()
with Session(books.engine_for(ours)) as db:
    attach_people(db, lambda: books.people(ours.id))
    now = deps.now()
    for uid in made:
        db.add(UserSetup(user_id=uid, seen_at=now, confirmed_at=now))
    db.commit()
books.dispose()
