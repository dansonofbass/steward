"""e2e: Spending's targets for the demo household, and two rows dated today, so Spending has one category clearly over
its target (Gifts, by $50) and Fun (entertainment) exactly at its target whatever day the suite runs. The other
everyday targets are the typical-month suggestions, as "Use these targets" saves them, raised where the demo's random
month would put one over or ahead: Home's line then names exactly Gifts. Also a viewer of the household book (Val),
who reads Spending and changes nothing. Fictional amounts only. Run after seed_extra.py."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from steward import deps
from steward.auth.users import create_user
from steward.books.people import attach_people
from steward.books.registry import open_books
from steward.books.service import add_membership
from steward.db.models import Account, CategorySource, Transaction, UserSetup
from steward.services import spending as sp
from steward.settings import Settings

books = open_books(Settings())
ours = books.book("ours")
today = deps.today()
month = today.replace(day=1)
with Session(books.directory) as ddb:
    val = create_user(ddb, "val-viewer", "val-viewer@example.com", "Val", "pw-viewer-demo-2026")
    add_membership(ddb, val.id, ours.id, "viewer", by=None, note="e2e")
    ddb.commit()
    val_id = val.id
with Session(books.engine_for(ours)) as db:
    attach_people(db, lambda: books.people(ours.id))
    seen = deps.now()
    db.add(UserSetup(user_id=val_id, seen_at=seen, confirmed_at=seen))   # Home, not Set up Steward
    card = db.scalar(select(Account).where(Account.name == "Rewards Card"))
    # Gift money in nets against Gifts (choice 2), and the yearly family gift lands in December: the flowers cover it,
    # so Gifts has at least $150 spent and a target $50 under it is above $0.
    gifts = next((r for r in sp.month_view(db, today, month)["everyday"] if r["category"] == "gifts"), None)
    flowers = 15_000 + (gifts["refunds_cents"] if gifts else 0)
    # Descriptions no demo row has: a sort in Review with "Also apply" ticked (celebrate.spec's three sorts take the
    # oldest cards, and FLOWER CART is one) moves every unreviewed row with the same description, these included.
    for raw, merchant, category, cents in (("PETALWORKS FLORIST", "Petalworks", "gifts", -flowers),
                                           ("REEL HOUSE CINEMA", "Reel House", "entertainment", -30_000)):
        db.add(Transaction(account_id=card.id, posted_at=today, amount_cents=cents, raw_description=raw,
                           merchant=merchant, category=category, category_source=CategorySource.rule,
                           external_id=f"e2e-spending-{category}"))
    db.flush()
    m = sp.month_view(db, today, month)
    spent = {r["category"]: r["spent_cents"] for r in m["everyday"]}
    assert spent["gifts"] - 5_000 < 50_000, "Gifts must be clearly over: $50 is over 10% only of a target under $500"

    def on_track(c: str, suggested: int) -> int:
        """At least what keeps usual-by-today above the month's rows plus $150 that later specs add (a coffee
        imported twice, a corrected row), to the $100 above."""
        enough = -(-(spent.get(c, 0) + 15_000) * m["days"] // m["day"])
        return max(suggested, -(-enough // 10_000) * 10_000)

    view = sp.targets_view(db, today)
    targets = [(r["category"], "everyday", on_track(r["category"], r["suggested_cents"])) for r in view["categories"]
               if r["kind"] == "everyday" and r["suggested_cents"] and r["category"] not in ("gifts", "entertainment")]
    targets.append(("gifts", "everyday", spent["gifts"] - 5_000))                           # over by $50
    targets.append(("entertainment", "everyday", -(-spent["entertainment"] // 100) * 100))  # spent, to the dollar above
    alex = next(p for p in books.people(ours.id) if p.username == "alex")
    sp.save_targets(db, targets, user_id=alex.id, who=alex.display_name, at=deps.now())
    db.commit()
books.dispose()
print("spending fixtures seeded")
