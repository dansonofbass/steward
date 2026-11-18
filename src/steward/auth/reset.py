import hashlib
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from steward.auth import sessions
from steward.auth.users import WeakPassword, find_user, set_password
from steward.db.directory_models import Passkey, PasswordReset, User
from steward.mail import Mailer, mail_ready

TTL_MINUTES = 15
LINK_GONE = "That link has expired or was already used."   # web/src/lib/copy.ts RESET_LINK_GONE
log = logging.getLogger("steward.mail")


class BadToken(ValueError):
    pass


def _h(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def safe_send(mailer: Mailer, to: str, subject: str, body: str) -> None:
    """Send mail, never raising; logs a one-line warning without the token or body. With email not set up it
    doesn't try: the link was made, but nobody can be emailed it."""
    if not mail_ready(mailer):
        log.warning("Email isn't set up, so an email wasn't sent")
        return
    try:
        mailer.send(to, subject, body)
    except Exception as e:
        log.warning("Could not send reset email (%s)", type(e).__name__)


def request_reset(db: Session, mailer: Mailer, base_url: str, username_or_email: str, now: datetime,
                  *, send: Callable[[str, str, str], None] | None = None) -> None:
    u = find_user(db, username_or_email)
    if u is None:
        return
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(user_id=u.id, token_hash=_h(token), expires_at=now + timedelta(minutes=TTL_MINUTES)))
    db.commit()
    link = f"{base_url.rstrip('/')}/reset?token={token}"
    (send or (lambda *a: safe_send(mailer, *a)))(u.email, "Reset your Steward password",
                f"Hi {u.display_name},\n\nUse this link to choose a new password. "
                f"It works for {TTL_MINUTES} minutes and only from a device on your home network.\n\n{link}\n\n"
                "If you didn't ask for this, you can ignore it.\n")


def close_open_resets(db: Session, user_id: int, now: datetime) -> None:
    db.execute(update(PasswordReset).where(PasswordReset.user_id == user_id, PasswordReset.used_at.is_(None))
               .values(used_at=now))


def start_clean(db: Session, user_id: int, now: datetime) -> int:
    """Recovery starts clean (SEC-4). After a password set through recovery (an emailed link, a manager's reset or
    `steward reset-password`), the account's other links close, its passkeys are deleted, and it is signed out
    everywhere with its Claude Code grants ended, so nothing someone else added outlives the reset. Commits. Returns
    how many passkeys went, for the caller to say."""
    close_open_resets(db, user_id, now)
    gone = db.execute(delete(Passkey).where(Passkey.user_id == user_id)).rowcount
    sessions.revoke_all_for_user(db, user_id, now)   # commits all three
    return gone


def consume(db: Session, token: str, new_password: str, now: datetime) -> User:
    pr = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == _h(token)))
    if pr is None or pr.used_at is not None or pr.expires_at <= now:
        raise BadToken()
    claimed = db.execute(update(PasswordReset).where(PasswordReset.id == pr.id, PasswordReset.used_at.is_(None))
                         .values(used_at=now))
    if claimed.rowcount != 1:
        raise BadToken()
    close_open_resets(db, pr.user_id, now)
    u = db.get(User, pr.user_id)
    try:
        set_password(db, u, new_password)  # commits used_at together with the new password
    except WeakPassword:
        db.rollback()  # a weak password must not burn the link
        raise
    from steward.books.service import give_real_username
    give_real_username(db, u)
    db.commit()
    start_clean(db, u.id, now)
    return u
