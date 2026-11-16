"""Claude Code grants (spec 7, ruling 3). A manager issues one for themself (final review M6); its text,
`stg1.<slug>.<43 random characters>`, is shown once and pasted into `steward-gateway mcp-grant add` on the gateway.
Only its SHA-256 is kept. It lasts 30 days, can be revoked by a manager or the person it is for, and is revoked when
that person leaves the book or resets their password. Every member of the book sees the list."""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.directory_models import AdvisorGrant, User
from steward import clock
from steward.inventory.present import at_label, day_label

GRANT_DAYS = 30
PREFIX = "stg1"
GRANT_RE = re.compile(r"^stg1\.([a-z0-9][a-z0-9-]{0,39})\.([A-Za-z0-9_-]{43})$")
TOUCH_EVERY = timedelta(minutes=1)


def token_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def issue(ddb: Session, *, book_id: int, slug: str, user_id: int, by: int, now: datetime) -> tuple[AdvisorGrant, str]:
    text = f"{PREFIX}.{slug}.{secrets.token_urlsafe(32)}"
    g = AdvisorGrant(book_id=book_id, user_id=user_id, issued_by=by, token_hash=token_hash(text), created_at=now,
                     expires_at=now + timedelta(days=GRANT_DAYS))
    ddb.add(g)
    ddb.flush()
    return g, text


def state(g: AdvisorGrant, now: datetime) -> str:
    if g.revoked_at is not None:
        return "revoked"
    return "active" if g.expires_at > now else "expired"


def resolve(ddb: Session, text: object, now: datetime) -> AdvisorGrant | None:
    if not isinstance(text, str) or not GRANT_RE.match(text):
        return None
    g = ddb.scalar(select(AdvisorGrant).where(AdvisorGrant.token_hash == token_hash(text)))
    return g if g is not None and state(g, now) == "active" else None


def touch(g: AdvisorGrant, now: datetime) -> None:
    if g.last_used_at is None or now - g.last_used_at >= TOUCH_EVERY:
        g.last_used_at = now


def revoke(g: AdvisorGrant, by: int | None, now: datetime) -> bool:
    if g.revoked_at is not None:
        return False
    g.revoked_at, g.revoked_by = now, by
    return True


def revoke_all_for(ddb: Session, user_id: int, now: datetime) -> int:
    """Every live grant of one person, in every book (final review M5: a new password). Revoked by
    Steward itself, so revoked_by stays empty. The caller commits."""
    found = ddb.scalars(select(AdvisorGrant).where(AdvisorGrant.user_id == user_id,
                                                   AdvisorGrant.revoked_at.is_(None))).all()
    return sum(revoke(g, None, now) for g in found)


def revoke_for(ddb: Session, book_id: int, user_id: int, by: int | None, now: datetime) -> int:
    found = ddb.scalars(select(AdvisorGrant).where(AdvisorGrant.book_id == book_id, AdvisorGrant.user_id == user_id,
                                                   AdvisorGrant.revoked_at.is_(None))).all()
    return sum(revoke(g, by, now) for g in found)


def _day(t: datetime, today: date) -> str:
    return day_label(t.astimezone(clock.household_tz()).date(), today)


def row(g: AdvisorGrant, names: dict[int, str], *, now: datetime, today: date, me: int, manager: bool) -> dict:
    st = state(g, now)
    if st == "active":
        used = f"last used {at_label(g.last_used_at, today)}" if g.last_used_at else "not used yet"
        line = f"Until {_day(g.expires_at, today)} · {used}"
    elif st == "revoked":
        who = "Steward" if g.revoked_by is None else names.get(g.revoked_by, "someone")
        line = f"Revoked by {who}, {_day(g.revoked_at, today)}"
    else:
        line = f"Ended {_day(g.expires_at, today)}"
    return {"id": g.id, "person": names.get(g.user_id, "Someone"), "issued_by": names.get(g.issued_by, "someone"),
            "issued": _day(g.created_at, today), "state": st, "line": line,
            "can_revoke": st == "active" and (manager or g.user_id == me)}


def names_for(ddb: Session, ids: set[int]) -> dict[int, str]:
    return dict(ddb.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all()) if ids else {}


def rows(ddb: Session, book_id: int, *, now: datetime, today: date, me: int, manager: bool) -> list[dict]:
    found = ddb.scalars(select(AdvisorGrant).where(AdvisorGrant.book_id == book_id)
                        .order_by(AdvisorGrant.created_at.desc(), AdvisorGrant.id.desc())).all()
    names = names_for(ddb, {i for g in found for i in (g.user_id, g.issued_by, g.revoked_by) if i is not None})
    return [row(g, names, now=now, today=today, me=me, manager=manager) for g in found]
