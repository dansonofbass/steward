"""e2e: one same-account question per Playwright project, made by real syncs through the fake SimpleFIN, in-process
(Engineering choice 19). One login brings a joint account and a second brokerage (so Merge into… has a choice); Alex sets
both as Taxable brokerage, which sorts their rows out of Review. A second login then brings the joint account again,
with one transaction of its own, and sync holds it. The phone's is "Joint Taxable" at Betterment, the desktop's "Joint
Brokerage" at Wealthfront. Dates are relative to today. The link is removed afterwards, so the demo stays unlinked.
Run with PYTHONPATH at the repo root, after seed_chat.py."""
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.books.registry import open_books
from steward.db.models import Account, AccountFeed, AccountType, SimplefinLink
from steward.events import resolve_events_matching
from steward.services.categorize import sort_investment_rows
from steward.services.simplefin.sync import run_sync
from steward.settings import Settings
from tests.fake_simplefin import make_fake

H = ("testserver",)
PAIRS = (("phone", "Joint Taxable", "Betterment", "betterment"),
         ("desktop", "Joint Brokerage", "Wealthfront", "wealthfront"))
ROWS = ((6, 500_00, "DEPOSIT"), (4, -5_00, "COFFEE"), (4, -5_00, "COFFEE"), (3, -12_50, "ADVISORY FEE"),
        (1, 31_07, "DIVIDEND"))                         # days ago, cents, description: two real coffees on one day

books = open_books(Settings())
ours = books.book("ours")
now = deps.now()


def ago(days: int) -> int:
    return int((now - timedelta(days=days)).timestamp())


app, state = make_fake()
for key, name, bank, org in PAIRS:
    state.add_account(f"e2e-{key}-alex", bank, org, f"e2e-{key}-joint", 84_210_00, ago(0), name=name,
                      txns=[(f"e2e-{key}-alex-{i}", ago(d), cents, desc) for i, (d, cents, desc) in enumerate(ROWS)])
    state.add_account(f"e2e-{key}-alex", bank, org, f"e2e-{key}-more", 1_200_00, ago(0), name=f"{bank} Brokerage")
with TestClient(app) as http, Session(books.engine_for(ours)) as db:
    link = SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=now - timedelta(hours=2))
    db.add(link)
    db.commit()
    run_sync(db, http, link, now - timedelta(hours=2), model=None, allowed_hosts=H)
    db.commit()
    for key, name, bank, org in PAIRS:
        for ext in (f"sfin:e2e-{key}-joint", f"sfin:e2e-{key}-more"):
            acct = db.get(Account, db.scalar(select(AccountFeed.account_id).where(AccountFeed.external_id == ext)))
            acct.type = AccountType.brokerage_taxable           # as Alex set it in Settings → Banks
            sort_investment_rows(db, acct)
            resolve_events_matching(db, "system", f"New account '{acct.name}' from ", now)
        state.add_account(f"e2e-{key}-sam", bank, org, f"e2e-{key}-sam-joint", 84_210_00, ago(0), name=name,
                          txns=[(f"e2e-{key}-sam-{i}", ago(d), cents, desc) for i, (d, cents, desc) in enumerate(ROWS)]
                          + [(f"e2e-{key}-sam-new", ago(0), -40_00, "WIRE FEE")])
    db.commit()
    res = run_sync(db, http, link, now - timedelta(hours=1), model=None, allowed_hosts=H)
    db.commit()
    assert res.accounts_held == len(PAIRS), res
    db.delete(db.get(SimplefinLink, link.id))   # the demo stays unlinked, as settings.spec's Banks test expects
    db.commit()
books.dispose()
print("same-account fixtures seeded")
