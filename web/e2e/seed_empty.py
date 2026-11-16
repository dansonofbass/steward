"""An empty household for the Set up Steward e2e (onboarding ruling 15): fictional people and nothing else.

alex, Person 1 as in the demo household, has seen the welcome (the profile spec starts on Profile, not on the first
run), while kit and robin have not, so welcome.spec starts on the first run as kit and checks Later as robin, whose
mark nothing else touches (guided setup plan D4)."""
from sqlalchemy.orm import Session

from steward.auth.users import create_user
from steward.books.registry import open_books
from steward.books.service import add_membership
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
with Session(books.directory) as ddb:
    for username, email, name, pw, welcomed in (("alex", "alex@example.com", "Alex", "pw-demo-alex-2026", True),
                                                ("kit", "kit@example.com", "Kit", "pw-demo-kit-2026", False),
                                                ("robin", "robin@example.com", "Robin", "pw-demo-robin-2026", False)):
        u = create_user(ddb, username, email, name, pw)
        add_membership(ddb, u.id, ours.id, "manager", by=None, note="e2e", welcomed=welcomed)
    ddb.commit()
books.dispose()
print("empty household seeded")
