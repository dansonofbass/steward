"""Extra fixtures for e2e: lockout and password users (one per Playwright project), viewers for the books spec (in
no book yet), a seeded parent book per project with a pending viewer invite whose token the spec knows (the invite
email can't be read from a test), a second pending invite per project, to wren-<project> as a manager of the same
parent book, for the partner welcome spec (its token is built at run time), three actionable events, a possible duplicate pair, and everyone in ours marked as
having seen Set up Steward; a seeded parent book per project, Margaret Ellis, with the synthetic parent's inventory
and flags (vee-<project> views it)."""
import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.auth.users import create_user
from steward.books.people import attach_people
from steward.books.registry import open_books
from steward.books.service import add_membership, create_book
from steward.demo_care import seed_care
from steward.demo_parent import seed_parent
from steward.demo_watching import seed_watching
from steward.inventory.suggestions import refresh
from steward.db.directory_models import Membership, PendingInvite, User
from steward.db.models import (
    Account, AccountType, CategorySource, Institution, Plan, Source, Transaction, UserSetup,
)
from steward.engine.version import ENGINE_VERSION
from steward.events import log_event
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
today = deps.today()   # the household's day, as the server counts it (not this machine's date)
with Session(books.directory) as ddb:
    for name in ("locky-phone", "locky-desktop"):
        u = create_user(ddb, name, f"{name}@example.com", "Locky", "pw-locky-demo-2026")
        add_membership(ddb, u.id, ours.id, "manager", by=None, note="e2e")
    for name in ("pw-phone", "pw-desktop"):
        u = create_user(ddb, name, f"{name}@example.com", "Pat", "pw-change-demo-2026")
        add_membership(ddb, u.id, ours.id, "manager", by=None, note="e2e")
    ddb.flush()
    jr_id = ddb.scalar(select(User.id).where(User.username == "alex"))     # Person 1 (owner key jr)
    for project in ("phone", "desktop"):
        vee = create_user(ddb, f"vee-{project}", f"vee-{project}@example.com", "Vee", "pw-viewer-demo-2026")
        seeded = create_book(books, ddb, name=f"Dad (Seed {project})", kind="parent",
                             owner_labels=["Robert (husband)", "Joint"], by=jr_id)
        with Session(books.engine_for(seeded)) as bdb:
            acct = Account(institution=Institution(name="Fictional Credit Union", source=Source.manual),
                           name="Dad checking", type=AccountType.checking, owner="robert-husband", source=Source.manual)
            bdb.add(acct)
            bdb.flush()
            bdb.add(Transaction(account_id=acct.id, posted_at=today - timedelta(days=2), amount_cents=-4250,
                                raw_description="HARDWARE STORE 0042", merchant="Hardware Store",
                                category="uncategorized", category_source=CategorySource.none))
            bdb.commit()
        now = deps.now()
        ddb.add(PendingInvite(book_id=seeded.id, user_id=vee.id, role="viewer", invited_by=jr_id,
                              token_hash=hashlib.sha256(f"e2e-invite-token-{project}".encode()).hexdigest(),
                              created_at=now, expires_at=now + timedelta(days=7)))
        wren = create_user(ddb, f"wren-{project}", f"wren-{project}@example.com", "Wren", "pw-partner-demo-2026")
        ddb.add(PendingInvite(book_id=seeded.id, user_id=wren.id, role="manager", invited_by=jr_id,
                              token_hash=hashlib.sha256("-".join(["e2e", "partner", "token", project]).encode()).hexdigest(),
                              created_at=now, expires_at=now + timedelta(days=7)))
        margaret = create_book(books, ddb, name=f"Margaret Ellis (Seed {project})", kind="parent",
                               owner_labels=["Margaret", "Robert (husband)", "Joint"], by=jr_id)
        add_membership(ddb, vee.id, margaret.id, "viewer", by=jr_id, note="e2e")
        with Session(books.engine_for(margaret)) as mdb:
            attach_people(mdb, lambda b=margaret: books.people(b.id))
            seed_parent(mdb, today, by=jr_id)
            refresh(mdb, today)
            seed_watching(mdb, today, by=jr_id)        # Margaret's flags (README "Margaret's flags")
            seed_care(mdb, today)
            mdb.commit()
    ddb.commit()
    ours_people = list(ddb.scalars(select(Membership.user_id).where(Membership.book_id == ours.id)))
with Session(books.engine_for(ours)) as db:
    attach_people(db, lambda: books.people(ours.id))
    new_acct = log_event(db, "info", "system",
                         "New account 'Acct 9999' from Big Bank needs its type and owner set in Settings", actionable=True)
    new_acct.at = deps.now() - timedelta(days=1)  # oldest, so the Dismiss test (newest first) leaves it
    for bank in ("Big Bank", "Savings Bank"):
        log_event(db, "warn", "sync", f"{bank} needs you to sign in again at SimpleFIN", actionable=True)
    seen = deps.now()
    for uid in ours_people:  # the existing specs start on Home, not in Set up Steward (onboarding ruling 15)
        db.add(UserSetup(user_id=uid, seen_at=seen, confirmed_at=seen))
    bank_row = db.scalar(select(Transaction).where(Transaction.raw_description == "BEAN & LEAF 0031",
                                                     Transaction.external_id.is_not(None))
                          .order_by(Transaction.posted_at.desc()))
    db.add(Transaction(account_id=bank_row.account_id, posted_at=bank_row.posted_at + timedelta(days=1),
                       amount_cents=bank_row.amount_cents, raw_description=bank_row.raw_description,
                       merchant=bank_row.merchant, category=bank_row.category, category_source=bank_row.category_source,
                       external_id=None))  # the same coffee, typed in from a file: a possible duplicate
    # An earlier saved plan (3 days ago), so the Overview's change line has something to compare with after a save today
    # (plan subpages, Engineering choice 8). inputs_summary is NULL, as for a plan saved before 0026.
    db.add(Plan(saved_at=deps.now() - timedelta(days=3), saved_by=jr_id,
                levers='{"assumed": {}, "try": {}, "pinned": []}', engine_version=ENGINE_VERSION,
                comfortable_age=66, likely_age=64))
    db.commit()
books.dispose()
print("extra fixtures seeded")
