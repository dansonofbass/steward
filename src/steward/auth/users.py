from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from steward.auth.passwords import hash_password, verify_password
from steward.db.directory_models import User

LOCK_AFTER = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LEN = 12
_DUMMY_HASH = hash_password("dummy-password-not-used")


class UserExists(ValueError):
    pass


class BadCredentials(PermissionError):
    pass


class Locked(PermissionError):
    def __init__(self, until: datetime):
        super().__init__(f"Locked until {until.isoformat()}")
        self.until = until


class WeakPassword(ValueError):
    pass


def _check_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise WeakPassword(f"Use at least {MIN_PASSWORD_LEN} characters.")


def find_user(db: Session, username_or_email: str) -> User | None:
    key = username_or_email.strip().lower()
    return db.scalar(select(User).where(or_(User.username == key, User.email == key)))


def create_user(db: Session, username: str, email: str, display_name: str, password: str) -> User:
    _check_strength(password)
    username, email = username.strip().lower(), email.strip().lower()
    if find_user(db, username) or find_user(db, email):
        raise UserExists(username)
    u = User(username=username, email=email, display_name=display_name,
             password_hash=hash_password(password))
    db.add(u)
    db.commit()
    return u


def set_password(db: Session, user: User, password: str) -> None:
    _check_strength(password)
    user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    db.commit()


def check_login(db: Session, username_or_email: str, password: str, now: datetime) -> User:
    u = find_user(db, username_or_email)
    if u is None:
        verify_password(_DUMMY_HASH, password)  # keeps timing close to a known user
        raise BadCredentials()
    _check_password(db, u, password, now)
    return u


def check_password(db: Session, user: User, password: str, now: datetime) -> None:
    """Re-check a signed-in user's password; counts failures and locks like a sign-in."""
    _check_password(db, user, password, now)


def _check_password(db: Session, u: User, password: str, now: datetime) -> None:
    if u.locked_until and u.locked_until > now:
        raise Locked(u.locked_until)
    if not verify_password(u.password_hash, password):
        db.execute(update(User).where(User.id == u.id)
                   .values(failed_logins=User.failed_logins + 1))
        db.refresh(u)
        if u.failed_logins >= LOCK_AFTER:
            # A lockout leaves Claude Code grants alone: anyone who knows a username can cause one, so revoking here
            # would let a stranger cut off a person's grants. A new password revokes them (sessions.revoke_all_for_user).
            u.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            u.failed_logins = 0
        db.commit()
        raise BadCredentials()
    u.failed_logins = 0
    u.locked_until = None
    db.commit()
