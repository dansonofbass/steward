"""Who gets watching email (decision 4; ruling 5). The switches live in the book (watch_recipient), by user id;
names, roles and addresses come from the directory each time (spec 2.2). No row: managers get both, viewers neither."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from steward.db.directory_models import Membership, User
from steward.db.models import WatchRecipient
from steward.inventory.changes import record
from steward.watch.flags import FlagRefused

NOT_A_MEMBER = "No such person in this book."
NOT_YOURS = "You can change your own emails and a viewer's."
LAST_MANAGER = "At least one manager has to get urgent emails. Turn them on for another manager first."
SWITCH_RULE = "Choose on or off."


@dataclass(frozen=True)
class Member:
    user_id: int
    name: str
    role: str
    email: str


def members(directory: Engine, book_id: int) -> list[Member]:
    with Session(directory) as s:
        rows = s.execute(select(User.id, User.display_name, Membership.role, User.email)
                         .join(Membership, Membership.user_id == User.id).where(Membership.book_id == book_id)
                         .order_by(Membership.role, User.id)).all()
    return [Member(*r) for r in rows]


def prefs(db: Session, people: list[Member]) -> dict[int, tuple[bool, bool]]:
    rows = {r.user_id: r for r in db.scalars(select(WatchRecipient))}
    out = {}
    for m in people:
        r = rows.get(m.user_id)
        out[m.user_id] = (r.urgent, r.summary) if r is not None else (m.role == "manager", m.role == "manager")
    return out


def urgent_to(db: Session, people: list[Member]) -> list[Member]:
    p = prefs(db, people)
    chosen = [m for m in people if p[m.user_id][0]]
    if not any(m.role == "manager" for m in chosen):     # ruling 5: never leave urgent mail with no manager
        chosen = [m for m in people if p[m.user_id][0] or m.role == "manager"]
    return chosen


def summary_to(db: Session, people: list[Member]) -> list[Member]:
    p = prefs(db, people)
    return [m for m in people if p[m.user_id][1]]


def _switch(body: dict, key: str, current: bool) -> bool:
    if key not in body:
        return current
    if not isinstance(body[key], bool):
        raise FlagRefused(SWITCH_RULE)
    return body[key]


def set_prefs(db: Session, ctx, people: list[Member], target_id: int, body: dict, now: datetime) -> None:
    target = next((m for m in people if m.user_id == target_id), None)
    if target is None:
        raise FlagRefused(NOT_A_MEMBER, 404)
    if target.role == "manager" and target_id != ctx.user_id:
        raise FlagRefused(NOT_YOURS, 403)
    current = prefs(db, people)
    old = current[target_id]
    new = (_switch(body, "urgent", old[0]), _switch(body, "summary", old[1]))
    if target.role == "manager" and old[0] and not new[0]:
        if not any(m.role == "manager" and m.user_id != target_id and current[m.user_id][0] for m in people):
            raise FlagRefused(LAST_MANAGER, 409)
    if new == old:
        return
    row = db.get(WatchRecipient, target_id)
    if row is None:
        db.add(WatchRecipient(user_id=target_id, urgent=new[0], summary=new[1], updated_at=now, updated_by=ctx.user_id))
    else:
        row.urgent, row.summary, row.updated_at, row.updated_by = new[0], new[1], now, ctx.user_id
    keys = [k for k, a, b in (("urgent", old[0], new[0]), ("summary", old[1], new[1])) if a != b]
    record(db, ctx, "watch.emails", target_id=target_id, before={k: dict(zip(("urgent", "summary"), old))[k] for k in keys},
           after={k: dict(zip(("urgent", "summary"), new))[k] for k in keys}, note=body.get("note"))
    db.flush()


def stop_mine(db: Session, ctx, people: list[Member], now: datetime) -> None:
    """Stop my emails (ruling 5): anyone may turn their own off; the last-manager rule still applies."""
    set_prefs(db, ctx, people, ctx.user_id, {"urgent": False, "summary": False}, now)
