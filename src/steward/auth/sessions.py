import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from steward.db.directory_models import Session, User
from steward.db.engine import begin_write

# Phase 18: last_seen_at was written on every signed-in request, so every request took the directory's write lock.
TOUCH_EVERY = timedelta(minutes=5)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: OrmSession, user: User, device_label: str, now: datetime, days: int):
    token = secrets.token_urlsafe(32)
    s = Session(user_id=user.id, token_hash=_h(token), device_label=device_label[:120],
                created_at=now, last_seen_at=now, expires_at=now + timedelta(days=days))
    db.add(s)
    db.commit()
    return token, s


def _live(db: OrmSession, token: str, now: datetime) -> Session | None:
    s = db.scalar(select(Session).where(Session.token_hash == _h(token)))
    if s is None or s.revoked_at is not None or s.expires_at <= now:
        return None
    return s


def resolve(db: OrmSession, token: str, now: datetime) -> tuple[User, Session] | None:
    """The signed-in person and their session, or None. last_seen_at moves at most every TOUCH_EVERY: a GET's read
    session takes the write lock only then (begin_write), and reads the session again under it, so a revoke that
    committed in between still wins."""
    s = _live(db, token, now)
    if s is None:
        return None
    if now - s.last_seen_at >= TOUCH_EVERY:
        begin_write(db)
        s = _live(db, token, now)
        if s is None:
            return None
        s.last_seen_at = now
        db.commit()
    return db.get(User, s.user_id), s


def revoke(db: OrmSession, session_id: int, user_id: int, now: datetime) -> bool:
    s = db.get(Session, session_id)
    if s is None or s.user_id != user_id or s.revoked_at is not None or s.expires_at <= now:
        return False
    s.revoked_at = now
    db.commit()
    return True


def revoke_token(db: OrmSession, token: str, now: datetime) -> None:
    s = _live(db, token, now)
    if s:
        s.revoked_at = now
        db.commit()


def revoke_all_for_user(db: OrmSession, user_id: int, now: datetime, keep: int | None = None) -> None:
    """Signs a person out everywhere after a new password (reset link, a manager's reset, steward reset-password, a
    password change), and revokes their Claude Code grants with it (final review M5)."""
    from steward.advisor.grants import revoke_all_for
    stmt = update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None)).values(revoked_at=now)
    if keep is not None:
        stmt = stmt.where(Session.id != keep)
    db.execute(stmt)
    revoke_all_for(db, user_id, now)
    db.commit()
