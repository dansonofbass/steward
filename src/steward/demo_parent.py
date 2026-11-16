"""The synthetic parent, Margaret Ellis (spec 11). Fictional throughout: no real person, bank login or account.
Eight accounts (Wells Fargo, Pacific Western Credit Union, Fidelity, Westmark Life, Citi) plus the house and a closed
Chase savings account; Social Security and a pension; four policies, Medicare Part B coming out of Social Security
(ruling 27); a power of attorney and two contacts. Six months of transactions leave exactly three suggestions:
Westmark Life annuity deposits, a Globe Mutual Medicare supplement premium and Harbor Savings Bank interest. Dates
are relative to `today`; with 2026-10-18 the figures match docs/design/inventory/README.md."""
from __future__ import annotations

from steward import clock
import calendar
import json
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from steward.db.models import (
    Account, CategorySource, Institution, InventoryItem, SimplefinLink, Source, Transaction,
)
from steward.inventory import kinds as K
from steward.inventory.changes import record
from steward.inventory.items import snapshot
from steward.services.accounts import manual_institution, record_balance


def _before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _after(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, 1)


def _day(y: int, m: int, day: int) -> date:
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


# name, kind, owner, institution, last4, status, data_source, details, extra
ITEMS = [
    ("Joint checking", "account", "joint", "Wells Fargo", "4417", "confirmed", "feed", {"type": "checking"}, {}),
    ("Way2Save savings", "account", "joint", "Wells Fargo", "4425", "confirmed", "feed", {"type": "savings"}, {}),
    ("12-month CD", "account", "margaret", "Pacific Western Credit Union", "0072", "confirmed", "statement", {"type": "cd"}, {}),
    ("Brokerage", "account", "margaret", "Fidelity", "3381", "confirmed", "statement", {"type": "brokerage"}, {}),
    ("Traditional IRA", "account", "margaret", "Fidelity", "3390", "confirmed", "statement", {"type": "ira"}, {}),
    ("Deferred annuity", "account", "margaret", "Westmark Life", "5521", "needs_checking", "manual", {"type": "annuity"},
     {"check_reason": "Typed in from an annual letter found in Margaret's mail. We haven't seen a statement."}),
    ("House", "account", "joint", "Fullerton", None, "confirmed", "manual", {"type": "property"}, {}),
    ("Citi card", "account", "margaret", "Citi", "9012", "confirmed", "feed", {"type": "credit_card"}, {}),
    ("Savings", "account", "margaret", "Chase", "6630", "closed", "statement", {"type": "savings"},
     {"closed_reason": "Moved to Wells Fargo savings, per the Feb 2025 Chase statement"}),
    ("Social Security", "income", "margaret", "Social Security Administration", None, "confirmed", "feed",
     {"source": "social_security", "amount_cents": 214000, "frequency": "monthly", "usual_day": 3,
      "lands_in": "Joint checking", "match_text": "SSA TREAS 310"}, {}),
    ("County Schools pension", "income", "margaret", "County Schools Retirement", None, "confirmed", "feed",
     {"source": "pension", "amount_cents": 138500, "frequency": "monthly", "usual_day": 1,
      "lands_in": "Joint checking", "match_text": "COUNTY SCHOOLS RET"}, {}),
    ("Long-term care", "insurance", "margaret", "Evergreen Mutual", "7730", "needs_checking", "manual",
     {"type": "long_term_care", "amount_cents": 21200, "frequency": "monthly", "usual_day": 10,
      "paid_from": "Joint checking", "match_text": "EVERGREEN MUTUAL", "benefit_cents": 15000, "benefit_per": "day",
      "waiting_days": 90, "benefit_years": 3},
     {"check_reason": "Typed in from a premium notice found in Margaret's mail. We haven't seen the policy or a statement.",
      "full_number": "EM-LTC-0047730"}),
    ("Medicare Part D", "insurance", "margaret", "Clearpath Rx", "2291", "confirmed", "feed",
     {"type": "part_d", "amount_cents": 3840, "frequency": "monthly", "usual_day": 20, "paid_from": "Joint checking",
      "match_text": "CLEARPATH RX"}, {}),
    ("Homeowners", "insurance", "joint", "Pacific Shield", "4108", "confirmed", "statement",
     {"type": "home", "amount_cents": 146000, "frequency": "yearly", "paid_from": "Joint checking"}, {}),
    ("Medicare Part B", "insurance", "margaret", "Medicare", None, "confirmed", "manual",
     {"type": "medicare", "amount_cents": 18500, "frequency": "monthly", "paid_from": "Social Security"}, {}),
    ("Durable power of attorney", "document", "margaret", None, None, "confirmed", None,
     {"type": "power_of_attorney", "original_kept_in": "The fire safe, blue folder marked \"Mom legal\"",
      "signed_on": "2019-06-12", "prepared_by": "Linda Park"}, {"notes": "Agent and successor agent are named inside."}),
    ("Daniel Ortiz", "contact", "margaret", "Fidelity", None, "confirmed", None,
     {"role": "advisor", "phone": "(714) 555-0102", "email": "dortiz@example.com",
      "looks_after": ["Brokerage", "Traditional IRA"]}, {}),
    ("Linda Park", "contact", "margaret", "Park & Reyes Law", None, "confirmed", None,
     {"role": "attorney", "phone": "(714) 555-0148", "email": "lpark@example.com"}, {}),
]
REFS = {"lands_in": "lands_in_id", "paid_from": "paid_from_id", "prepared_by": "prepared_by_id"}


def seed_parent(db: Session, today: date, *, by: int | None = None) -> dict[str, int]:
    now = clock.now()
    statement_day = today.replace(day=1) - timedelta(days=1)                 # Sep 30 for Oct 18
    house_day = _month_start(today, 2) + timedelta(days=3)                   # Aug 4 for Oct 18
    closed_on = date(today.year - 1, 2, 14)
    wells = Institution(name="Wells Fargo", source=Source.simplefin, simplefin_org_id="demo-wf")
    citi = Institution(name="Citi", source=Source.simplefin, simplefin_org_id="demo-citi")
    db.add_all([wells, citi])
    db.flush()
    manual = manual_institution(db)
    feed_inst = {"Wells Fargo": wells, "Citi": citi}
    balances = {"Joint checking": (821455, today), "Way2Save savings": (2248010, today), "12-month CD": (4000000, statement_day),
                "Brokerage": (14260000, statement_day), "Traditional IRA": (18835000, statement_day),
                "House": (78000000, house_day), "Citi card": (-118240, today), "Savings": (0, closed_on)}
    renewal = date(today.year + (1 if (today.month, today.day) >= (3, 1) else 0), 3, 1)
    ids: dict[str, int] = {}
    accounts: dict[str, Account] = {}
    pending_refs = []
    for name, kind, owner, inst, last4, status, source, details, extra in ITEMS:
        d = {k: v for k, v in details.items() if k not in REFS and k != "looks_after"}
        if name == "Homeowners":
            d["renewal_on"] = renewal.isoformat()
        item = InventoryItem(kind=kind, name=name, owner=owner, institution=inst, last4=last4, status=status,
                             data_source=source, details=json.dumps(d), created_at=now, created_by=by,
                             updated_at=now, updated_by=by, check_reason=extra.get("check_reason"),
                             full_number=extra.get("full_number"), notes=extra.get("notes"),
                             closed_on=closed_on if status == "closed" else None, closed_reason=extra.get("closed_reason"))
        if kind == "account":
            feed = source == "feed"
            acct = Account(institution_id=(feed_inst[inst] if feed else manual).id, name=name,
                           type=K.ACCOUNT_TYPE_TO_ACCOUNT[details["type"]], owner=owner,
                           source=Source.simplefin if feed else Source.manual,
                           external_id=f"sfin:demo-{last4}" if feed else None, is_active=status != "closed")
            db.add(acct)
            db.flush()
            item.account_id = acct.id
            accounts[name] = acct
            if name in balances:
                record_balance(db, acct.id, balances[name][1], balances[name][0])
        db.add(item)
        db.flush()
        ids[name] = item.id
        pending_refs.append((item, details))
    for item, details in pending_refs:
        d = json.loads(item.details)
        for k, field in REFS.items():
            if k in details:
                d[field] = ids[details[k]]
        if "looks_after" in details:
            d["looks_after_ids"] = sorted(ids[n] for n in details["looks_after"])
        item.details = json.dumps(d)
    synced = datetime.combine(today, time(13, 10), tzinfo=timezone.utc)
    wells.last_sync_at = citi.last_sync_at = synced        # both banks came back in the last sync
    db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=now, last_sync_at=synced))
    for name, acct in accounts.items():                      # a feed account reports a balance each sync it comes back
        if acct.source == Source.simplefin and balances.get(name, (0, None))[1] != today:
            record_balance(db, acct.id, today, balances[name][0] if name in balances else 0)
    _transactions(db, today, accounts["Joint checking"], accounts["Way2Save savings"], accounts["Citi card"])
    if by is not None:
        ctx = SimpleNamespace(book=SimpleNamespace(kind="parent"), user_id=by)
        for item, _ in pending_refs:
            record(db, ctx, "item.add", target_id=item.id, item_id=item.id, after={**snapshot(item), "kind": item.kind})
    db.commit()
    return ids


def _transactions(db: Session, today: date, chk: Account, save: Account, card: Account) -> None:
    def add(acct: Account, d: date, cents: int, raw: str, category: str) -> None:
        if d > today:
            return
        db.add(Transaction(account_id=acct.id, posted_at=d, amount_cents=cents, raw_description=raw, category=category,
                           category_source=CategorySource.rule,
                           external_id=f"demo-{d.isoformat()}-{raw[:12]}-{cents}" if acct.source == Source.simplefin else None))

    for back in range(5, -1, -1):
        first = _month_start(today, back)
        y, m = first.year, first.month
        add(chk, _before(_day(y, m, 3)), 214000, "SSA TREAS 310 XXSOC SEC", "income")
        add(chk, _before(_day(y, m, 1)), 138500, "COUNTY SCHOOLS RET PENSION", "income")
        add(chk, _before(_day(y, m, 10)), -21200, "EVERGREEN MUTUAL LTC PREM", "insurance")
        add(chk, _before(_day(y, m, 20)), -3840, "CLEARPATH RX PART D PREM", "insurance")
        add(chk, _before(_day(y, m, 14)), -(8000 + back * 317), "STATER BROS 123", "groceries")
        add(chk, _before(_day(y, m, 16)), -(9000 + back * 2311), "SOUTHERN CALIFORNIA EDISON", "utilities")
        add(chk, _before(_day(y, m, 22)), -(20000 + back * 5333), "CITI CARD ONLINE PAYMENT", "transfer")
        add(card, _before(_day(y, m, 8)), -(4000 + back * 731), "TRADER JOE'S 512", "groceries")
    # The annuity deposits and the premium land around the 15th. Margaret has the last four that have already landed,
    # whatever day this runs, so the suggestions say 4 deposits and 4 payments before the 15th as well as after.
    for raw, cents, move in (("WESTMARK LIFE ANN PMT 5521", 41000, _before), ("GLOBE MUTUAL MEDSUPP PREM", -18620, _after)):
        landed = [d for d in (move(_day(f.year, f.month, 15)) for f in (_month_start(today, b) for b in range(5, -1, -1)))
                  if d <= today]
        for d in landed[-4:]:
            add(chk, d, cents, raw, "uncategorized")
    quarter_ends = [_day(y, m, 31) for y in (today.year - 1, today.year) for m in (3, 6, 9, 12)]
    for d, cents in zip([q for q in quarter_ends if q <= today][-2:], (1461, 1482)):
        add(save, d, cents, "HARBOR SAVINGS BK INT XFER", "uncategorized")
