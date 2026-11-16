"""What the inventory screens read (docs/design/inventory/README.md, screens 2, 3a and 3b): one load of the book's
items, balances and file counts, then a row for the list and the whole item page. Never full_number (decision 5)."""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine, and_, func, select
from sqlalchemy.orm import Session

from steward.books.people import mid_sentence
from steward.db.models import BalanceSnapshot, InventoryItem, SimplefinLink, StoredFile, Transaction
from steward import clock
from steward.inventory import kinds as K
from steward.inventory.changes import history_for
from steward.inventory.present import day_label, joined, long_label, mask, month_year, ordinal, size_label, when_label
from steward.services.holdings import newest as holdings_newest


@dataclass
class Loaded:
    items: list[InventoryItem]
    by_id: dict[int, InventoryItem]
    details: dict[int, dict]
    balances: dict[int, tuple[date, int]]
    file_counts: dict[int, int]
    owners: dict[str, str]


def load(db: Session, owners: dict[str, str]) -> Loaded:
    """Three queries, whatever the number of items (spec 12: the page API under 500 ms with 200 items)."""
    items = list(db.scalars(select(InventoryItem).order_by(InventoryItem.id)))
    newest = (select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.as_of).label("d"))
              .group_by(BalanceSnapshot.account_id).subquery())
    balances = {a: (d, c) for a, d, c in db.execute(
        select(BalanceSnapshot.account_id, BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
        .join(newest, and_(BalanceSnapshot.account_id == newest.c.account_id, BalanceSnapshot.as_of == newest.c.d)))}
    files = dict(db.execute(select(StoredFile.item_id, func.count()).where(StoredFile.item_id.is_not(None))
                            .group_by(StoredFile.item_id)).all())
    return Loaded(items, {i.id: i for i in items}, {i.id: json.loads(i.details or "{}") for i in items}, balances,
                  files, owners)


def _type(L: Loaded, item: InventoryItem) -> str | None:
    return L.details[item.id].get(K.TYPE_FIELD[item.kind])


def counts_in_totals(L: Loaded, item: InventoryItem) -> bool:
    """A premium paid out of an income item (Medicare Part B from Social Security) isn't money going out (ruling 27)."""
    ref = L.by_id.get(L.details[item.id].get("paid_from_id"))
    return not (item.kind == "insurance" and ref is not None and ref.kind == "income")


def _local_day(t: datetime) -> date:
    return t.astimezone(clock.household_tz()).date()


def sub_line(L: Loaded, item: InventoryItem, today: date) -> str:
    d, t, m = L.details[item.id], _type(L, item), mask(item.last4)
    if item.kind == "account":
        if t == "property":
            parts = ["Property", item.institution]
        else:
            parts = [item.institution, " ".join(p for p in (K.type_word("account", t), m) if p) or None]
        if item.status == "closed" and item.closed_on:
            parts.append(f"closed {month_year(item.closed_on)}")
    elif item.kind == "income":
        freq = K.FREQUENCY_LABELS.get(d.get("frequency"))
        when = f"{freq}, around the {ordinal(d['usual_day'])}" if freq and d.get("usual_day") else freq
        into = L.by_id.get(d.get("lands_in_id"))
        parts = [when, f"into {mask(into.last4) or into.name}" if into else None]
    elif item.kind == "insurance":
        parts = [item.institution, f"policy {m}" if m else None]
    elif item.kind == "document":
        signed = d.get("signed_on")
        parts = [K.type_label("document", t), f"signed {day_label(date.fromisoformat(signed), today)}" if signed else None,
                 "scan attached" if L.file_counts.get(item.id) else None]
    else:
        parts = [K.type_label("contact", t), item.institution]
    return " · ".join(p for p in parts if p)


def item_row(L: Loaded, item: InventoryItem, today: date) -> dict:
    d, t = L.details[item.id], _type(L, item)
    bal = L.balances.get(item.account_id) if item.account_id else None
    amount = per = monthly = None
    no_balance = False
    if item.kind == "account":
        amount = bal[1] if bal else None
        no_balance = bal is None and item.status != "closed"
    elif item.kind in ("income", "insurance"):
        amount = d.get("amount_cents")
        monthly = K.monthly_cents(amount, d.get("frequency"))
        if item.kind == "insurance" and d.get("frequency"):
            per = K.PER_SUFFIX[d["frequency"]]
    if item.status == "closed" and item.closed_on:
        updated = item.closed_on
    elif bal and item.data_source in ("feed", "statement"):
        updated = bal[0]
    else:
        updated = _local_day(item.updated_at)
    return {
        "id": item.id, "kind": item.kind, "name": item.name, "owner": item.owner,
        "owner_label": L.owners.get(item.owner, item.owner), "institution": item.institution, "last4": item.last4,
        "status": item.status, "data_source": item.data_source, "type": t, "type_label": K.type_label(item.kind, t),
        "type_word": K.type_word(item.kind, t),
        "sub": sub_line(L, item, today), "amount_cents": amount, "amount_per": per, "monthly_cents": monthly,
        "counts_in_totals": counts_in_totals(L, item), "no_balance": no_balance,
        "total_group": K.TOTAL_GROUP.get(t) if item.kind == "account" and item.status != "closed" else None,
        "updated_on": updated.isoformat(), "check_reason": item.check_reason, "account_id": item.account_id,
    }


def weekend_note(posted: date, usual_day: int | None, today: date) -> str | None:
    """"the 3rd is a Saturday" when a deposit or payment moved off its usual day because of a weekend (ruling 21)."""
    if not usual_day or posted.day == usual_day:
        return None
    intended = date(posted.year, posted.month, min(usual_day, calendar.monthrange(posted.year, posted.month)[1]))
    if intended.weekday() < 5 or not 0 < abs((posted - intended).days) <= 3:
        return None
    tense = "is" if (intended.year, intended.month) == (today.year, today.month) else "was"
    return f"the {ordinal(usual_day)} {tense} a {'Saturday' if intended.weekday() == 5 else 'Sunday'}"


def _matched(db: Session, L: Loaded, item: InventoryItem, today: date) -> dict | None:
    d = L.details[item.id]
    text = d.get("match_text")
    if not text or item.kind not in ("income", "insurance", "account"):
        return None
    q = select(Transaction).where(Transaction.raw_description.icontains(text, autoescape=True))
    via = L.by_id.get(d.get("lands_in_id") if item.kind == "income" else d.get("paid_from_id"))
    if via is not None and via.account_id is not None:
        q = q.where(Transaction.account_id == via.account_id)
    if item.kind == "income":
        q = q.where(Transaction.amount_cents > 0)
    elif item.kind == "insurance":
        q = q.where(Transaction.amount_cents < 0)
    txns = db.scalars(q.order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(6)).all()
    rows = [{"posted_at": t.posted_at.isoformat(), "amount_cents": t.amount_cents,
             "note": weekend_note(t.posted_at, d.get("usual_day"), today)} for t in txns]
    heading = {"income": "Last {n} deposits", "insurance": "Last {n} payments",
               "account": "Matched transactions"}[item.kind].format(n=len(rows))
    return {"heading": heading, "match_text": text, "rows": rows,
            "last_paid": rows[0]["posted_at"] if item.kind == "insurance" and rows else None}


def file_row(f: StoredFile, names: dict[int, str], today: date) -> dict:
    return {"id": f.id, "name": f.name, "content_type": f.content_type,
            "label": K.CONTENT_LABELS.get(f.content_type, "File"), "size": f.size, "size_label": size_label(f.size),
            "uploaded_on": _local_day(f.uploaded_at).isoformat(), "uploaded_by": mid_sentence(names.get(f.uploaded_by))}


def _ref(L: Loaded, item_id) -> dict | None:
    it = L.by_id.get(item_id)
    return {"id": it.id, "label": long_label(it.name, it.institution, it.last4, it.kind)} if it else None


def item_detail(db: Session, L: Loaded, item: InventoryItem, today: date, directory: Engine) -> dict:
    from steward.books.history import names_for
    d = L.details[item.id]
    open_ = [i for i in L.items if i.status != "closed"]
    money_in = [{"id": i.id, "name": i.name} for i in open_ if i.kind == "income" and L.details[i.id].get("lands_in_id") == item.id]
    paid_here = [{"id": i.id, "name": i.name} for i in open_ if i.kind == "insurance" and L.details[i.id].get("paid_from_id") == item.id]
    linked: dict[int, str] = {}
    if item.kind == "contact":
        for i in d.get("looks_after_ids", []):
            if i in L.by_id:
                linked[i] = L.by_id[i].name
        for i in L.items:
            if i.kind == "document" and L.details[i.id].get("prepared_by_id") == item.id:
                linked[i.id] = i.name
    files = list(db.scalars(select(StoredFile).where(StoredFile.item_id == item.id).order_by(StoredFile.uploaded_at.desc())))
    names = names_for(directory, [f.uploaded_by for f in files] + [item.created_by])
    added = day_label(_local_day(item.created_at), today)
    added_line = (f"{added} by {mid_sentence(names.get(item.created_by, 'someone'))}" if item.created_by is not None
                  else f"{added}, from the bank feed" if item.data_source == "feed" else f"{added}, from an existing account")
    balance = None
    bal = L.balances.get(item.account_id) if item.account_id else None
    if bal:
        as_of, cents = bal
        if item.data_source == "feed":
            synced = db.scalar(select(SimplefinLink.last_sync_at).order_by(SimplefinLink.id))
            line = f"From the bank feed, {when_label(synced, today) if synced else day_label(as_of, today)}"
        elif item.data_source == "statement":
            line = f"From a statement, {day_label(as_of, today)}"
        else:
            line = f"Typed in, {day_label(as_of, today)}"
        balance = {"cents": cents, "line": line}
    txns = []
    if item.kind == "account" and item.account_id is not None:
        txns = [{"id": t.id, "name": t.merchant or t.raw_description, "amount_cents": t.amount_cents,
                 "posted_at": t.posted_at.isoformat(), "category": t.category}
                for t in db.scalars(select(Transaction).where(Transaction.account_id == item.account_id)
                                    .order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(5))]
    held = None
    if item.kind == "account" and item.account_id is not None:
        newest = holdings_newest(db, item.account_id)          # PDF statements spec P41: read-only, the newest day
        if newest:
            held = {"as_of": newest[0].as_of.isoformat(),
                    "rows": [{"symbol": h.symbol, "name": h.name, "value_cents": h.market_value_cents} for h in newest]}
    return {
        **item_row(L, item, today), "details": d, "login_kept_in": item.login_kept_in, "notes": item.notes,
        "has_full_number": bool(item.full_number),
        "closed_on": item.closed_on.isoformat() if item.closed_on else None, "closed_reason": item.closed_reason,
        "refs": {f: _ref(L, d.get(f)) for f in ("lands_in_id", "paid_from_id", "prepared_by_id")},
        "looks_after": [r for r in (_ref(L, i) for i in d.get("looks_after_ids", [])) if r],
        "money_in_here": money_in, "paid_from_here": paid_here,
        "linked_items": [{"id": i, "name": n} for i, n in linked.items()],
        "joint_names": joined([lbl for k, lbl in L.owners.items() if k != "joint"]) if item.owner == "joint" else None,
        "added_line": added_line, "balance": balance, "transactions": txns, "holdings": held, "matched": _matched(db, L, item, today),
        "files": [file_row(f, names, today) for f in files],
        "history": history_for(db, directory, item.id, today, L.owners),
    }
