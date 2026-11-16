from datetime import datetime

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from steward.db.models import EventLog

# Kinds a viewer never sees, counts or acts on (PDF statements spec P4; Engineering choice 14): an import notice can
# name uploaded files. Every path that lists, counts or acts on EventLog rows for a person goes through these two.
MANAGERS_ONLY = frozenset({"import"})


def event_visible(e: EventLog, manager: bool) -> bool:
    return manager or e.kind not in MANAGERS_ONLY


def visible_to(q: Select, manager: bool) -> Select:
    """The same rule in SQL, so a limit counts only what the person may see."""
    return q if manager else q.where(EventLog.kind.not_in(MANAGERS_ONLY))


def log_event(db: Session, level: str, kind: str, message: str, actionable: bool = False) -> EventLog:
    e = EventLog(level=level, kind=kind, message=message, actionable=actionable)
    db.add(e)
    db.flush()
    return e


def resolve_events(db: Session, kind: str, now: datetime) -> int:
    """Mark every unresolved event of this kind resolved. Returns how many changed."""
    result = db.execute(
        update(EventLog)
        .where(EventLog.kind == kind, EventLog.resolved_at.is_(None))
        .values(resolved_at=now)
    )
    return result.rowcount


def resolve_event(db: Session, event_id: int, now: datetime) -> bool:
    """Resolve one event. False if it doesn't exist; resolving twice keeps the first time."""
    e = db.get(EventLog, event_id)
    if e is None:
        return False
    if e.resolved_at is None:
        e.resolved_at = now
        db.flush()
    return True


def resolve_events_matching(db: Session, kind: str, prefix: str, now: datetime) -> int:
    """Resolve unresolved events of this kind whose message starts with `prefix`.

    Loads and updates the rows (rather than a bulk UPDATE) so objects already in the
    session stay fresh; the prefix is matched literally, not as a LIKE pattern.
    """
    events = db.scalars(select(EventLog).where(
        EventLog.kind == kind, EventLog.resolved_at.is_(None),
        EventLog.message.startswith(prefix, autoescape=True))).all()
    for e in events:
        e.resolved_at = now
    db.flush()
    return len(events)
