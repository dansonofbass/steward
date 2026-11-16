"""The parent Home and the top of the inventory (spec 3.4; docs/design/inventory/README.md screen 1). Joint
accounts and the house count at full value (decision 6). Premiums paid out of an income item are named, not counted
(ruling 27)."""
from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import InventoryItem, SimplefinLink
from steward.inventory import kinds as K
from steward.inventory.present import (
    day_label, joined, ordinal, parent_name, possessive, short_ref, usd, when_label,
)
from steward.inventory.views import Loaded, counts_in_totals


def label_of(L: Loaded, item: InventoryItem) -> str:
    word = K.type_word(item.kind, L.details[item.id].get(K.TYPE_FIELD[item.kind]))
    return f"{item.institution} {word}" if item.institution and word else item.name


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _total_note(key: str, members: list[InventoryItem], L: Loaded) -> str:
    if not members:
        return "None listed"
    if key == "property":
        return f"{members[0].name}, estimate" if len(members) == 1 else f"{len(members)} properties, estimates"
    if key == "debts":
        words = Counter(K.type_word("account", L.details[i.id].get("type")) for i in members)
        return ", ".join(_count(n, w) for w, n in words.items())
    missing = sum(1 for i in members if i.account_id not in L.balances)
    return _count(len(members), "account") + (f", {missing} with no balance" if missing else "")


def _ref(L: Loaded, item_id) -> str | None:
    it = L.by_id.get(item_id)
    return short_ref(it.name, it.institution, it.last4) if it else None


def overview(db: Session, L: Loaded, today: date, *, recent=(), suggestions: dict | None = None,
             pending_income=()) -> dict:
    whose = possessive(parent_name(L.owners.values()))
    accounts = [i for i in L.items if i.kind == "account" and i.status != "closed"]
    counted = [i for i in accounts if i.account_id in L.balances]
    missing = [i for i in accounts if i.account_id not in L.balances]
    if not accounts:
        counted_line = "No accounts listed yet."
    elif not missing:
        counted_line = f"From {whose} one account." if len(accounts) == 1 else f"From all {len(accounts)} of {whose} accounts."
    else:
        counted_line = f"From {len(counted)} of {whose} {len(accounts)} accounts."
        counted_line += (f" The {label_of(L, missing[0])} has no balance yet." if len(missing) == 1
                         else f" {len(missing)} have no balance yet.")

    synced = db.scalar(select(SimplefinLink.last_sync_at).order_by(SimplefinLink.id))
    statements = [L.balances[i.account_id][0] for i in counted if i.data_source == "statement"]
    parts = []
    if synced and any(i.data_source == "feed" for i in accounts):
        parts.append(f"bank feed updated {when_label(synced, today)}")
    if statements:
        parts.append(f"statements through {day_label(max(statements), today)}")
    fresh = " \u00b7 ".join(parts)

    checking = [i for i in L.items if i.status == "needs_checking"]
    totals = []
    for key, label in K.TOTALS:
        members = [i for i in accounts if K.TOTAL_GROUP.get(L.details[i.id].get("type")) == key]
        totals.append({"key": key, "label": label,
                       "cents": sum(L.balances[i.account_id][1] for i in members if i.account_id in L.balances),
                       "note": _total_note(key, members, L)})

    open_items = [i for i in L.items if i.status != "closed"]
    from_income = [i for i in open_items if i.kind == "insurance" and not counts_in_totals(L, i)]
    incoming_rows, incoming = [], 0
    for i in (x for x in open_items if x.kind == "income"):
        d = L.details[i.id]
        when = f"Around the {ordinal(d['usual_day'])}" if d.get("usual_day") else K.FREQUENCY_LABELS[d["frequency"]]
        into = _ref(L, d.get("lands_in_id"))
        taken = [x.name for x in from_income if L.details[x.id].get("paid_from_id") == i.id]
        sub = [when, f"into {into}" if into else None, f"after {joined(taken)}" if taken else None]
        incoming_rows.append({"item_id": i.id, "name": i.name, "cents": d["amount_cents"],
                              "per": K.FREQUENCY_WORDS[d["frequency"]], "sub": " \u00b7 ".join(s for s in sub if s),
                              "status": i.status})
        incoming += K.monthly_cents(d["amount_cents"], d["frequency"]) or 0
    pending = [f"{payer} deposits of {usd(cents)} a month" for payer, cents in pending_income]
    incoming_foot = f"Not counted yet: {joined(pending)}, waiting in Is this one of {whose}?" if pending else None

    outgoing_rows, outgoing = [], 0
    for i in (x for x in open_items if x.kind == "insurance" and counts_in_totals(L, x)):
        d = L.details[i.id]
        amount, freq = d.get("amount_cents"), d.get("frequency")
        if amount is None or freq is None:
            continue
        monthly = K.monthly_cents(amount, freq)
        renewal = date.fromisoformat(d["renewal_on"]) if d.get("renewal_on") else None
        if freq == "monthly":
            when = f"Around the {ordinal(d['usual_day'])}" if d.get("usual_day") else "Monthly"
        else:
            when = f"Renews {renewal:%b} {renewal.day}" if renewal else K.FREQUENCY_LABELS[freq]
        frm = _ref(L, d.get("paid_from_id"))
        sub = [when, f"from {frm}" if frm else None, f"{usd(monthly)} a month" if freq != "monthly" else None]
        outgoing_rows.append({"item_id": i.id, "name": f"{i.name} \u00b7 {i.institution}" if i.institution else i.name,
                              "cents": amount, "per": K.FREQUENCY_WORDS[freq],
                              "sub": " \u00b7 ".join(s for s in sub if s), "status": i.status})
        outgoing += monthly
    foot = "From insurance items."
    for x in from_income:
        d = L.details[x.id]
        if d.get("amount_cents") is not None:
            foot += f" {x.name} ({usd(d['amount_cents'])}) comes out of {L.by_id[d['paid_from_id']].name} before it arrives."

    return {
        "net_worth_cents": sum(L.balances[i.account_id][1] for i in counted), "counted_line": counted_line,
        "fresh_line": fresh[:1].upper() + fresh[1:] if fresh else None,
        "needs_checking": {"count": len(checking), "labels": [label_of(L, i) for i in checking]},
        "suggestions": suggestions, "totals": totals,
        "incoming": {"monthly_cents": incoming, "rows": incoming_rows, "foot": incoming_foot},
        "outgoing": {"monthly_cents": outgoing, "rows": outgoing_rows, "foot": foot},
        "recent": list(recent),
    }
