"""The change record (spec 5; design pass decisions 5 and 8). record() writes a row for a manager's write in a
parent book and nothing in a household book. describe() turns a row into the words the Settings tab, Home's Recent
changes and an item's History show. Rows hold raw values; numbers arrive here already masked to the last 4."""
from __future__ import annotations

from steward import clock
import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine, false, select
from sqlalchemy.orm import Session

from steward.db.models import ChangeRecord, InventoryItem
from steward.inventory import kinds as K
from steward.inventory.present import (
    day_label, joined, long_label, ordinal, parent_name, possessive, short_ref, size_label, usd,
)

KIND_FILTERS: dict[str, tuple[str, ...]] = {
    "items": ("item",), "files": ("file",), "suggestions": ("suggestion", "taxform"), "transactions": ("txn",),
    "imports": ("import", "export"), "members": (), "bank_feed": ("feed",), "watching": ("flag", "watch"),
    "care": ("care",),
}
KIND_RULE = "Choose one of the kinds of change."
PAGE = 50

FIELD_LABELS = {
    "name": "Name", "owner": "Owner", "institution": "Institution", "number": "Number", "status": "Status",
    "check_reason": "Why it needs checking", "data_source": "Data from", "type": "Type", "source": "Source",
    "role": "Role", "amount_cents": "Amount", "frequency": "How often", "usual_day": "Usual day",
    "lands_in_id": "Lands in", "paid_from_id": "Paid from", "renewal_on": "Renewal date",
    "original_kept_in": "Original kept in", "signed_on": "Signed", "prepared_by_id": "Prepared by", "phone": "Phone",
    "email": "Email", "looks_after_ids": "Looks after", "match_text": "Matched by", "balance_cents": "Balance",
    "floor_cents": "Low-balance floor",
    "benefit_cents": "Benefit", "benefit_per": "Benefit paid", "waiting_days": "Waiting period",
    "pool_cents": "Total benefit", "benefit_years": "Benefit years", "rider_bp": "Inflation protection",
    "login_kept_in": "Login kept in", "notes": "Notes", "category": "Category", "merchant": "Merchant",
    "is_business": "Business or personal",
}
REF_FIELDS = frozenset({"lands_in_id", "paid_from_id", "prepared_by_id"})
DATE_FIELDS = frozenset({"renewal_on", "signed_on", "closed_on"})
MONEY_FIELDS = frozenset({"amount_cents", "balance_cents", "floor_cents", "benefit_cents", "pool_cents"})


@dataclass(frozen=True)
class ItemLabel:
    name: str
    kind: str
    long: str
    short: str


def labels_for(db: Session) -> dict[int, ItemLabel]:
    rows = db.execute(select(InventoryItem.id, InventoryItem.name, InventoryItem.kind, InventoryItem.institution,
                             InventoryItem.last4))
    return {i: ItemLabel(n, k, long_label(n, inst, l4, k), short_ref(n, inst, l4)) for i, n, k, inst, l4 in rows}


def _now() -> datetime:
    return clock.now()


def record(db: Session, ctx, action: str, *, target_id: int | None = None, item_id: int | None = None,
           before: dict | None = None, after: dict | None = None, note: object = None) -> ChangeRecord | None:
    """One row for a write in a parent book; household books record nothing new (spec 5)."""
    if ctx.book.kind != "parent":
        return None
    return _write(db, ctx.user_id, action, target_id, item_id, before, after, note)


def record_system(db: Session, action: str, *, target_id: int | None = None, item_id: int | None = None,
                  after: dict | None = None) -> ChangeRecord:
    """A row with no person: the bank feed or start-up added something (ruling 13). Callers are parent-book code."""
    return _write(db, None, action, target_id, item_id, None, after, None)


def _write(db, user_id, action, target_id, item_id, before, after, note) -> ChangeRecord:
    clean = note.strip()[:300] if isinstance(note, str) and note.strip() else None
    row = ChangeRecord(at=_now(), user_id=user_id, action=action, target_type=action.split(".", 1)[0],
                       target_id=target_id, item_id=item_id, before=json.dumps(before) if before else None,
                       after=json.dumps(after) if after else None, note=clean)
    db.add(row)
    db.flush()
    return row


def changed(before: dict, after: dict) -> tuple[dict, dict]:
    keys = [k for k in dict.fromkeys([*before, *after]) if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _marks_confirmed(after: dict) -> bool:
    """An edit that only makes the item Confirmed (clearing its reason with it) reads as "marked Confirmed"."""
    return set(after) in ({"status"}, {"status", "check_reason"}) and after.get("status") == "confirmed"


def about(t) -> dict:
    """What a transaction row in the record says about the transaction, kept even if it is removed later."""
    return {"raw": t.raw_description, "amount_cents": t.amount_cents, "posted_at": t.posted_at.isoformat()}


def _about_line(a: dict, today: date) -> str:
    return f"{a['raw']} · {usd(a['amount_cents'])} · {day_label(date.fromisoformat(a['posted_at']), today)}"


def field_label(field: str, kind: str | None) -> str:
    if field == "number":
        return {"insurance": "Policy number", "account": "Account number"}.get(kind or "", "Number")
    if field == "amount_cents" and kind == "insurance":
        return "Premium"
    return FIELD_LABELS.get(field, field)


def _value(field: str, v, kind: str | None, labels: dict[int, ItemLabel], owners: dict[str, str], today: date) -> str:
    if v is None or v == "" or v == []:
        return "none" if field == "floor_cents" else "not known"
    if field == "status":
        return K.STATUS_LABELS.get(v, v)
    if field == "owner":
        return owners.get(v, v)
    if field == "data_source":
        return K.SOURCE_LABELS.get(v, v)
    if field in ("type", "source", "role"):
        return K.type_label(kind or "", v) or str(v)
    if field == "frequency":
        return K.FREQUENCY_LABELS.get(v, v)
    if field in MONEY_FIELDS:
        return usd(int(v))
    if field in DATE_FIELDS:
        return day_label(date.fromisoformat(v), today)
    if field == "usual_day":
        return f"the {ordinal(int(v))}"
    if field in REF_FIELDS:
        return labels[v].long if v in labels else "a removed item"
    if field == "looks_after_ids":
        return joined([labels[i].name for i in v if i in labels]) or "not known"
    if field == "category":
        return str(v).replace("_", " ").capitalize()
    if field == "is_business":
        return "Business" if v else "Personal"
    if field == "benefit_per":
        return "a day" if v == "day" else "a month"
    if field == "waiting_days":
        return f"{int(v)} days"
    if field == "benefit_years":
        return "1 year" if int(v) == 1 else f"{int(v)} years"
    if field == "rider_bp":
        return f"{int(v) / 100:g}% a year"
    return str(v)


def _diffs(before: dict, after: dict, kind, labels, owners, today) -> list[dict]:
    out = []
    for f in FIELD_LABELS:
        if f in before or f in after:
            out.append({"label": field_label(f, kind), "before": _value(f, before.get(f), kind, labels, owners, today),
                        "after": _value(f, after.get(f), kind, labels, owners, today)})
    return out


_ICONS = {
    "item.add": "plus", "item.edit": "pencil", "item.close": "archive", "item.reopen": "archive-restore",
    "item.reveal": "eye", "file.add": "paperclip", "file.remove": "trash", "suggestion.dismiss": "x",
    "suggestion.link": "link", "suggestion.undo": "undo", "taxform.add": "receipt", "txn.edit": "pencil",
    "txn.remove": "trash", "txn.reviewed": "list-checks", "txn.keep_both": "copy", "txn.spread": "list-checks", "txn.sort_many": "list-checks", "txn.undo": "undo", "txn.note_add": "message-square", "txn.note_remove": "trash", "import.add": "upload",
    "import.undo": "undo", "export.backup": "download", "feed.connect": "refresh", "feed.disconnect": "unplug",
    "care.setup": "pencil", "care.scenario_add": "plus", "care.scenario_edit": "pencil", "care.scenario_remove": "trash",
    "care.quote": "receipt", "care.quote_remove": "undo",
}


def describe(row: ChangeRecord, who: str | None, labels: dict[int, ItemLabel], owners: dict[str, str], today: date,
             context: str = "page", extra: dict | None = None) -> dict:
    """context: "page" (Settings → Change record), "item" (an item's History) or "home" (only summary is read)."""
    if row.target_type in ("flag", "watch"):
        from steward.watch.changes import describe_watch
        icon, text, item, diffs, lines = describe_watch(
            row, json.loads(row.before) if row.before else {}, json.loads(row.after) if row.after else {},
            labels, extra or {}, owners, context == "item")
        return _out(f"c{row.id}", row.at, who, icon, text, item, diffs, lines, row.note, None, row.action)
    before = json.loads(row.before) if row.before else {}
    after = json.loads(row.after) if row.after else {}
    label = labels.get(row.item_id) if row.item_id is not None else None
    kind = label.kind if label else after.get("kind")
    on_item = context == "item"
    icon, text, lines, diffs, link_label = _ICONS.get(row.action, "pencil"), row.action, [], [], label.name if label else None
    a = row.action
    if a == "item.add":
        status = K.STATUS_LABELS.get(after.get("status", ""), "")
        if who is None:
            feed = after.get("from") == "feed"
            text = "Added from the bank feed" if feed else "Added from an existing account"
            lines = ["Confirmed, because the feed reports it"] if feed else [status]
        else:
            text = "added this item" if on_item else "added {item}"
            what = [K.KIND_LABELS.get(after.get("kind", ""), ""), K.type_word(after.get("kind", ""),
                    after.get(K.TYPE_FIELD.get(after.get("kind", ""), "type"))) or "",
                    owners.get(after.get("owner", ""), ""), status]
            lines = [" · ".join(w for w in what if w)] if not on_item else [status]
            if after.get("from_suggestion"):
                lines.append(f"From a suggestion: {after['from_suggestion']}")
    elif a == "item.edit":
        diffs = _diffs(before, after, kind, labels, owners, today)
        only_status = _marks_confirmed(after)
        if only_status:
            icon = "circle-check"
        if on_item:
            text = ("marked this item Confirmed" if only_status else
                    f"changed the {diffs[0]['label'].lower()}" if len(diffs) == 1 else "edited this item")
        else:
            text = "edited {item}"
    elif a == "item.close":
        text = "closed this item" if on_item else "closed {item}"
        link_label = label.long if label else None
        diffs = [{"label": "Closed on", "before": None,
                  "after": _value("closed_on", after.get("closed_on"), kind, labels, owners, today)}]
    elif a == "item.reopen":
        text = "reopened this item" if on_item else "reopened {item}"
    elif a == "item.reveal":
        text = "showed the full number" if on_item else "showed the full number for {item}"
    elif a in ("file.add", "file.remove"):
        name = after.get("name") or before.get("name", "a file")
        verb, prep = ("attached", "to") if a == "file.add" else ("removed", "from")
        text = f"{verb} {name}" if on_item or label is None else f"{verb} {name} {prep} {{item}}"
        if a == "file.add" and label is None:
            text = f"uploaded {name}"
        facts = after or before
        lines = [f"{facts.get('type', '')} · {size_label(int(facts.get('size', 0)))}"]
    elif a == "suggestion.dismiss":
        text = f"answered Not {possessive(parent_name(owners.values()))} to a suggestion"
        lines = [f"Payer: {after.get('payer', '')}"]
    elif a == "suggestion.link":
        text = "linked a suggestion here" if on_item else "linked a suggestion to {item}"
        lines = [f"Payer: {after.get('payer', '')} · {after.get('count', 0)} {after.get('noun', 'transactions')}"]
        if after.get("confirmed"):
            lines.append("Marked Confirmed")
    elif a == "suggestion.undo":
        text, lines = "undid an answer to a suggestion", [f"Payer: {after.get('payer', '')}"]
    elif a == "taxform.add":
        text = f"typed in a {after.get('form', 'tax form')} from {after.get('payer', '')}"
        lines = [f"Tax year {after.get('tax_year', '')}" + (f" · ••{after['last4']}" if after.get("last4") else "")]
    elif a in ("txn.edit", "txn.remove", "txn.reviewed"):
        text = {"txn.edit": "edited a transaction", "txn.remove": "removed a transaction",
                "txn.reviewed": "marked a transaction reviewed"}[a]
        lines = [_about_line(after["about"], today)] if after.get("about") else []
        if a == "txn.edit":
            diffs = _diffs(before, after, None, labels, owners, today)
    elif a == "txn.keep_both":
        text, lines = "kept two transactions that look alike", [_about_line(x, today) for x in after.get("about", [])]
    elif a == "txn.spread":
        text = f"set the category on {after.get('count', 0)} transactions like this one"
        lines = [_about_line(after["about"], today)] if after.get("about") else []
    elif a == "txn.sort_many":
        n = after.get("count", 0)
        what = "a transaction" if n == 1 else f"{n} transactions"
        text, lines = f"sorted {what} as {_value('category', after.get('category', ''), None, labels, owners, today)}", []
    elif a == "txn.undo":
        n = after.get("count", 1)
        text = "undid a change to a transaction" if n == 1 else f"undid a change to {n} transactions"
        lines = [_about_line(after["about"], today)] if after.get("about") else []
    elif a in ("txn.note_add", "txn.note_remove"):
        text = "added a note to a transaction" if a == "txn.note_add" else "removed a note from a transaction"
        lines = [_about_line(after["about"], today)] if after.get("about") else []
    elif a == "import.add":
        text = f"imported {after.get('filename', 'a file')}"
        lines = [f"{after.get('rows', 0)} transactions into {after.get('account', 'an account')}"]
    elif a == "export.backup":
        text, lines = "made an encrypted backup of the book", []
    elif a == "import.undo":
        text, lines = f"undid the import of {after.get('filename', 'a file')}", [f"{after.get('rows', 0)} transactions removed"]
    elif a == "feed.connect":
        text, lines = "connected the bank feed", ["SimpleFIN"]
    elif a == "feed.disconnect":
        text = "disconnected the bank feed"
    elif a == "care.setup":
        text, lines = ("changed Care setup" if before else "set up Care"), [after.get("summary", "")]
    elif a == "care.scenario_add":
        text, lines = "added a care scenario", [after.get("label", "")]
    elif a == "care.scenario_edit":
        text = "changed a care scenario"
        was, now = before.get("label", ""), after.get("label", "")
        lines = [now] if was == now else [f"{was} → {now}"]
    elif a == "care.scenario_remove":
        text, lines = "removed a care scenario", [before.get("label", "")]
    elif a == "care.quote":
        text, lines = f"entered a quote for {after.get('label', 'care').lower()}", [after.get("text", "")]
    elif a == "care.quote_remove":
        text = f"went back to the typical cost for {before.get('label', 'care').lower()}"
    item = {"id": row.item_id, "label": link_label} if label and "{item}" in text else None
    return _out(f"c{row.id}", row.at, who, icon, text, item, diffs, lines, row.note, label, a, after)


def _summary(who: str | None, text: str, item: dict | None, label: ItemLabel | None, action: str, after: dict,
             diffs: list[dict]) -> str:
    if action == "item.edit" and label is not None:
        if _marks_confirmed(after):
            body = f"marked {label.long} Confirmed"
        else:
            body = f"edited {label.name}: {', '.join(d['label'].lower() for d in diffs)}"
    else:
        body = text.replace("{item}", item["label"]) if item else text
    return f"{who} {body}" if who else body[:1].upper() + body[1:]


def _out(cid, at, who, icon, text, item, diffs, lines, note, label=None, action="", after=None) -> dict:
    return {"id": cid, "at": at.isoformat(), "who": who, "icon": icon, "text": text, "item": item, "diffs": diffs,
            "lines": lines, "note": note, "summary": _summary(who, text, item, label, action, after or {}, diffs)}


def describe_member(m, names: dict[int, str]) -> dict:
    who = names.get(m.by_user_id) if m.by_user_id is not None else None
    name = names.get(m.user_id, "someone")
    text = {"added": f"added {name} as a {m.role_after}", "invited": f"invited {name} as a {m.role_after}",
            "role_changed": f"made {name} a {m.role_after}", "removed": f"removed {name}"}.get(m.action, m.action)
    if who is None:
        text = text[:1].upper() + text[1:]
    return _out(f"m{m.id}", m.at, who, "users", text, None, [], [], None)


def page(db: Session, directory: Engine, book_id: int, *, user_id: int | None, kind: str | None,
         before: datetime | None, today: date, owners: dict[str, str], limit: int = PAGE) -> dict:
    """A page of the Change record, newest first: the book's rows with a person, merged by time with the directory's
    membership changes for the book (ruling 14). `next` is the time to pass as `before` for the next page."""
    from steward.books.history import membership_changes, names_for
    q = select(ChangeRecord).where(ChangeRecord.user_id.is_not(None))
    if user_id is not None:
        q = q.where(ChangeRecord.user_id == user_id)
    if kind is not None:
        types = KIND_FILTERS[kind]
        q = q.where(ChangeRecord.target_type.in_(types)) if types else q.where(false())
    if before is not None:
        q = q.where(ChangeRecord.at < before)
    rows = list(db.scalars(q.order_by(ChangeRecord.at.desc(), ChangeRecord.id.desc()).limit(limit)))
    members = (membership_changes(directory, book_id, by=user_id, before=before, limit=limit)
               if kind in (None, "members") else [])
    merged = sorted([*rows, *members], key=lambda r: r.at, reverse=True)[:limit]
    from steward.watch.changes import flag_labels
    names = names_for(directory, [r.user_id for r in rows] + [m.by_user_id for m in members]
                      + [m.user_id for m in members] + [r.target_id for r in rows if r.action == "watch.emails"])
    labels = labels_for(db)
    extra = {"flags": flag_labels(db, parent_name(owners.values())), "names": names}
    out = [describe(r, names.get(r.user_id, "Someone"), labels, owners, today, extra=extra)
           if isinstance(r, ChangeRecord) else describe_member(r, names) for r in merged]
    more = len(rows) == limit or len(members) == limit or len(rows) + len(members) > limit
    return {"changes": out, "next": merged[-1].at.isoformat() if merged and more else None}


def history_for(db: Session, directory: Engine, item_id: int, today: date, owners: dict[str, str]) -> list[dict]:
    """An item's History, newest first, with the bank feed's own rows (ruling 13)."""
    from steward.books.history import names_for
    rows = list(db.scalars(select(ChangeRecord).where(ChangeRecord.item_id == item_id)
                           .order_by(ChangeRecord.at.desc(), ChangeRecord.id.desc()).limit(PAGE)))
    names = names_for(directory, [r.user_id for r in rows])
    labels = labels_for(db)
    return [describe(r, names.get(r.user_id, "Someone") if r.user_id is not None else None, labels, owners, today,
                     context="item", extra={"flags": {}, "names": names}) for r in rows]
