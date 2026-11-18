"""The one-time link `steward setup` prints for the first person (release spec 2026-11-05, section 6; claim S7).

- 32 random bytes (secrets.token_urlsafe), kept only as their SHA-256: the directory, and every backup of it, holds
  no usable link.
- 30 minutes: long enough to open it on the phone that will be used (installing Tailscale there first, say), short
  enough that a terminal's scrollback left open is soon worth nothing. It works once, and a new `steward setup`
  closes any link still open, so only one is ever live.
- Compared in constant time, against every open link.
- Refused once anyone exists: Steward has no open sign-up; everyone after the first is invited.
The first person is a manager of Ours whose membership nobody made (created_by NULL), which is how the guided first
run knows them (guided setup spec, 2.1 and 7.1)."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from steward.auth import users
from steward.books.service import add_membership
from steward.db.directory_models import Book, SetupLink, User

TTL_MINUTES = 30
MAX_TOKEN = 128
FIRST_BOOK = "ours"
SETUP_COMMAND = "docker compose run --rm steward steward setup"   # as docs/quickstart/install.md gives it (issue #20)
LINK_GONE = f"This link has expired or was already used. Run {SETUP_COMMAND} again for a new one."
ALREADY = "Steward is already set up. Sign in."
ZONE_NOT_SET = "Time zone: not set yet. You'll choose it on the welcome screen."
ALREADY_CLI = "Steward already has an account. Sign in, or add someone with `steward create-user`."


class LinkGone(ValueError):
    """The token is no open link's: wrong, used, closed by a newer one, or past its 30 minutes."""


class AlreadySetUp(RuntimeError):
    """Someone exists, so there is nothing to set up."""


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def has_people(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


def has_people_in(engine) -> bool:
    with Session(engine) as db:
        return has_people(db)


def issue(db: Session, now: datetime) -> str:
    """A new link; any link still open is closed first."""
    if has_people(db):
        raise AlreadySetUp()
    db.execute(update(SetupLink).where(SetupLink.used_at.is_(None)).values(used_at=now))
    token = secrets.token_urlsafe(32)
    db.add(SetupLink(token_hash=_h(token), created_at=now, expires_at=now + timedelta(minutes=TTL_MINUTES)))
    db.commit()
    return token


def _open_link(db: Session, token: object, now: datetime) -> SetupLink | None:
    if not isinstance(token, str) or not 0 < len(token) <= MAX_TOKEN:
        return None
    want, found = _h(token).encode(), None
    for link in db.scalars(select(SetupLink).where(SetupLink.used_at.is_(None), SetupLink.expires_at > now)):
        if hmac.compare_digest(link.token_hash.encode(), want):   # every open link is compared, a match or not
            found = link
    return found


def check(db: Session, token: object, now: datetime) -> None:
    """Whether the link still works, without using it (the page asks before it shows the form)."""
    if has_people(db):
        raise AlreadySetUp()
    if _open_link(db, token, now) is None:
        raise LinkGone()


def claim(db: Session, token: object, now: datetime, *, username: str, email: str, display_name: str,
          password: str) -> User:
    """Use the link: the first person, a manager of Ours, made in the same transaction that marks the link used. A
    weak password rolls both back, so it never burns the link."""
    if has_people(db):
        raise AlreadySetUp()
    link = _open_link(db, token, now)
    if link is None:
        raise LinkGone()
    taken = db.execute(update(SetupLink).where(SetupLink.id == link.id, SetupLink.used_at.is_(None))
                       .values(used_at=now))
    if taken.rowcount != 1:
        raise LinkGone()
    try:
        u = users.create_user(db, username, email, display_name, password)   # commits the claim with the person
    except (users.WeakPassword, users.UserExists):
        db.rollback()
        raise
    ours = db.scalar(select(Book).where(Book.slug == FIRST_BOOK))
    if ours is None:
        raise RuntimeError("The household book is missing; run steward migrate.")
    add_membership(db, u.id, ours.id, "manager", by=None, now=now, note="steward setup")
    db.commit()
    return u
