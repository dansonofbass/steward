"""Change record wording for flag actions and Watching settings (spec 5; README screen 8). Rows are written by
steward.watch.flags and steward.api.watching; inventory.changes.describe hands them here."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import ChangeRecord, Flag
from steward.inventory.present import parent_name, possessive, safe_line, usd
from steward.watch import vocab as V

STATUS_ICONS = {"open": "flag", "checking": "hourglass", "expected": "circle-check", "handled": "check",
                "arrived": "calendar-check"}


def flag_label(f: Flag, name: str) -> str:
    return f"{V.check_label(f.check, name)}: {safe_line(f.title)}"


def flag_labels(db: Session, name: str) -> dict[int, str]:
    return {f.id: flag_label(f, name) for f in db.scalars(select(Flag))}


def _onoff(v) -> str:
    return "on" if v else "off"


def _money(v) -> str:
    return usd(int(v)) if v is not None else "none"


def describe_watch(row: ChangeRecord, before: dict, after: dict, labels: dict, extra: dict, owners: dict,
                   on_item: bool):
    """(icon, text, item, diffs, lines). text holds {item} where the link goes."""
    a = row.action
    flags, names = extra.get("flags", {}), extra.get("names", {})
    diffs: list[dict] = []
    if a in ("flag.status", "flag.note"):
        label = flags.get(row.target_id) or "a flag"
        item = {"id": row.target_id, "label": label, "path": f"/look-into/{row.target_id}"}
        if a == "flag.note":
            return "hourglass", "changed the note on {item}", item, [], []
        new, old = after.get("status", ""), before.get("status", "")
        diffs.append({"label": "Status", "before": V.STATUS_LABELS.get(old, old), "after": V.STATUS_LABELS.get(new, new)})
        known = after.get("known") or {}
        if "add" in known:
            diffs.append({"label": "Known payees", "before": None, "after": f"+ {known['add']}"})
        if "remove" in known:
            diffs.append({"label": "Known payees", "before": known["remove"], "after": None})
        text = "reopened {item}" if new == "open" else f"marked {{item}} {V.STATUS_LABELS.get(new, new)}"
        return STATUS_ICONS.get(new, "flag"), text, item, diffs, []
    if a == "watch.large":
        return ("banknote", "changed the large amount", None,
                [{"label": "Flag money out of", "before": _money(before.get("large_cents")),
                  "after": _money(after.get("large_cents"))}], [])
    if a == "watch.cash_floor":
        return ("coins", "changed the cash alert floor", None,
                [{"label": "Alert on cash from", "before": _money(before.get("cash_alert_floor_cents")),
                  "after": _money(after.get("cash_alert_floor_cents"))}], [])
    if a == "watch.floor":
        old, new = before.get("floor_cents"), after.get("floor_cents")
        verb = "set" if old is None else "removed" if new is None else "changed"
        lab = labels.get(row.item_id)
        item = None if on_item or lab is None else {"id": row.item_id, "label": lab.name}
        text = f"{verb} the low-balance floor" if verb != "set" else "set a low-balance floor"
        if item is not None:
            text += " on {item}"
        return "trending-down", text, item, [{"label": "Floor", "before": _money(old), "after": _money(new)}], []
    if a == "watch.known_remove":
        return "trash", "removed a known payee", None, [{"label": "Known payees", "before": before.get("known", ""),
                                                         "after": None}], []
    if a == "watch.emails":
        whose = "their own" if row.target_id == row.user_id else possessive(names.get(row.target_id, "someone"))
        for key, lab in (("urgent", "Urgent"), ("summary", "Daily summary")):
            if key in before or key in after:
                if before.get(key) != after.get(key):
                    diffs.append({"label": lab, "before": _onoff(before.get(key)), "after": _onoff(after.get(key))})
        return "mail", f"changed {whose} emails", None, diffs, []
    return "pencil", a, None, [], []
