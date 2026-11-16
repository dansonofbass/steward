"""Low balances and new bank feed accounts (spec 4.1; rulings 11 and 13). A low balance is flagged once per dip below
an account item's floor: watch_state "low:<account id>" holds the floor that was crossed until the balance recovers."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, BalanceSnapshot, Flag, Institution, InventoryItem, Source
from steward.inventory import kinds as K
from steward.inventory.present import clean_account, usd
from steward.watch import vocab as V
from steward.watch.store import FEED_ACCOUNTS, add_flag, get_state, set_state


def low_key(account_id: int) -> str:
    return f"low:{account_id}"


def balance_on(db: Session, account_id: int, today: date) -> tuple[date, int] | None:
    row = db.execute(select(BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
                     .where(BalanceSnapshot.account_id == account_id, BalanceSnapshot.as_of <= today)
                     .order_by(BalanceSnapshot.as_of.desc()).limit(1)).first()
    return (row[0], row[1]) if row else None


def floored_items(db: Session) -> list[tuple[InventoryItem, dict]]:
    """Open checking, savings and CD items with an account, in item order, with their details."""
    out = []
    for item in db.scalars(select(InventoryItem).where(InventoryItem.kind == "account", InventoryItem.status != "closed",
                                                       InventoryItem.account_id.is_not(None)).order_by(InventoryItem.id)):
        d = json.loads(item.details or "{}")
        if d.get("type") in K.FLOOR_TYPES:
            out.append((item, d))
    return out


def check_low(db: Session, today: date, now: datetime, *, after: str, account_id: int | None = None) -> list[int]:
    """`account_id` limits the check to one account, for a floor changed on that account's item: the trigger label
    is then true, and no other account gets a flag from someone else's edit."""
    made = []
    for item, d in floored_items(db):
        if account_id is not None and item.account_id != account_id:
            continue
        key, floor = low_key(item.account_id), d.get("floor_cents")
        bal = balance_on(db, item.account_id, today) if floor is not None else None
        if floor is None or (bal is not None and bal[1] >= floor):
            set_state(db, key, None, now)
            if floor is not None:      # a lowered floor leaves an open flag naming the old one
                stale = db.scalar(select(Flag).where(Flag.check == "low", Flag.account_id == item.account_id,
                                                     Flag.status.in_(V.NOT_DONE)))
                facts = json.loads(stale.facts or "{}") if stale is not None else {}
                back = f"{clean_account(item.name)} is back above its {usd(floor)} floor"
                if stale is not None and (facts.get("floor_cents") != floor or stale.summary != back):
                    stale.summary = back
                    stale.facts = json.dumps({**facts, "floor_cents": floor})
            continue
        if bal is None or get_state(db, key) == str(floor):
            continue
        set_state(db, key, str(floor), now)
        as_of, cents = bal
        open_flag = db.scalar(select(Flag).where(Flag.check == "low", Flag.account_id == item.account_id,
                                                 Flag.status.in_(V.NOT_DONE)))
        if open_flag is not None:      # a new floor under an open flag: the flag says the floor it is under now
            open_flag.summary = f"{clean_account(item.name)} is under its {usd(floor)} floor"
            open_flag.facts = json.dumps({**json.loads(open_flag.facts or "{}"), "floor_cents": floor})
            continue
        f = add_flag(db, check="low", severity="normal", summary=f"{clean_account(item.name)} is under its {usd(floor)} floor",
                     title=f"{clean_account(item.name)} is under its floor", now=now, after=after, item_id=item.id,
                     account_id=item.account_id,
                     facts={"balance_cents": cents, "floor_cents": floor, "as_of": as_of.isoformat(),
                            "account": item.name, "amount_cents": cents})
        made.append(f.id)
    return made


def check_new_accounts(db: Session, now: datetime, *, after: str) -> list[int]:
    feed = db.execute(select(Account.id, Account.name, Institution.name)
                      .join(Institution, Institution.id == Account.institution_id)
                      .where(Account.source == Source.simplefin).order_by(Account.id)).all()
    ids = {r[0] for r in feed}
    raw = get_state(db, FEED_ACCOUNTS)
    seen = set(json.loads(raw)) if raw else set()
    if not seen:                                   # the first sync of a feed (ruling 13)
        if ids:
            set_state(db, FEED_ACCOUNTS, json.dumps(sorted(ids)), now)
        return []
    items = dict(db.execute(select(InventoryItem.account_id, InventoryItem.id)
                            .where(InventoryItem.account_id.is_not(None))).all())
    made = []
    for account_id, name, institution in feed:
        if account_id in seen:
            continue
        f = add_flag(db, check="account", severity="normal", now=now, after=after,
                     summary=f"{clean_account(institution)} reports {clean_account(name)}, which wasn't in the inventory",
                     title=f"New account at {clean_account(institution)}", facts={"account": name, "institution": institution},
                     item_id=items.get(account_id), account_id=account_id)
        made.append(f.id)
    if ids - seen:
        set_state(db, FEED_ACCOUNTS, json.dumps(sorted(seen | ids)), now)
    return made
