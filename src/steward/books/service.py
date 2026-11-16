"""Changes to books and who belongs to them. Every membership change is also written to membership_change
(spec 5), so it stays on record after the person's access is gone."""
from __future__ import annotations

from steward import clock
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from steward.auth.passwords import hash_password
from steward.auth.users import find_user
from steward.books.bootstrap import remove_db_files
from steward.books.owners import HOUSEHOLD_OWNER_NAMES, owner_key, parse_owner_names, to_json
from steward.books.registry import BookInfo, BookRegistry, household_book_id
from steward.db.directory_models import (
    BOOK_KINDS, AdvisorGrant, Book, Membership, MembershipChange, Passkey, PasswordReset, PendingInvite,
    Session as DbSession, User,
)
from steward.db.engine import make_engine
from steward.db.migrate import MigrationFailed, run_migrations


def _now() -> datetime:
    return clock.now()


def add_membership(ddb: Session, user_id: int, book_id: int, role: str, *, by: int | None,
                   now: datetime | None = None, note: str | None = None, welcomed: bool = False) -> Membership:
    t = now or _now()
    m = Membership(user_id=user_id, book_id=book_id, role=role, created_at=t, created_by=by,
                   welcome_seen_at=t if welcomed else None)
    ddb.add(m)
    ddb.add(MembershipChange(at=t, book_id=book_id, user_id=user_id, action="added", role_before=None,
                             role_after=role, by_user_id=by, note=note))
    ddb.flush()
    return m


RESERVED_SLUGS = frozenset({"directory"})   # steward-directory-*.db is the directory's backup name
NAME_RULE = "Enter a book name of up to 60 characters."
KIND_RULE = "Choose household or parent."
ONE_HOUSEHOLD = "Steward has one household book, made at setup. Add a parent book instead."


class BookRefused(ValueError):
    """A book that can't be made as asked; the message is plain words for the person asking."""


def slug_for(ddb: Session, name: str) -> str:
    base = owner_key(name)[:36].strip("-") or "book"
    slug, n = base, 2
    while slug in RESERVED_SLUGS or ddb.scalar(select(Book.id).where(Book.slug == slug)) is not None:
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_book(books: BookRegistry, ddb: Session, *, name: object, kind: object, owner_labels: object = None,
                by: int | None = None, managers=(), now: datetime | None = None,
                allow_household: bool = False, sample_of: int | None = None) -> BookInfo:
    """A new book: its directory row, its own file at books/<slug>/book.db with a derived key, migrated to head, and
    its first managers (`by` and `managers`). The slug never changes (ruling 3).

    One household per install: setup (bootstrap) makes it, so a household book is refused unless the caller passes
    allow_household (only `steward book create`, run by whoever runs the server), and even then while one exists. The
    HTTP route never passes it: managing a household book is what makes someone an install manager.
    sample_of: only books/sample.make_sample passes it (plan D1)."""
    clean = name.strip() if isinstance(name, str) else ""
    if not clean or len(clean) > 60:
        raise BookRefused(NAME_RULE)
    if kind not in BOOK_KINDS:
        raise BookRefused(KIND_RULE)
    if sample_of is not None and kind != "household":
        raise BookRefused(KIND_RULE)
    if kind == "household" and sample_of is None and (not allow_household or household_book_id(ddb) is not None):
        raise BookRefused(ONE_HOUSEHOLD)
    try:
        names = HOUSEHOLD_OWNER_NAMES if kind == "household" else parse_owner_names(owner_labels)
    except ValueError as e:
        raise BookRefused(str(e)) from None
    t = now or _now()
    slug = slug_for(ddb, clean)
    row = Book(slug=slug, name=clean, kind=kind, owner_names=to_json(names), file=f"books/{slug}/book.db",
               key_scheme="derived", created_at=t, sample_of=sample_of)
    ddb.add(row)
    ddb.flush()
    info = BookInfo.of(row)
    path = books.path_for(info)
    remove_db_files(path)   # left by an attempt whose directory row never committed
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    eng = make_engine(path, books.key_for(info))
    try:
        run_migrations(eng)
    except MigrationFailed:
        eng.dispose()
        remove_db_files(path)
        raise
    eng.dispose()
    for uid in dict.fromkeys(([by] if by is not None else []) + list(managers)):
        add_membership(ddb, uid, row.id, "manager", by=by, now=t, note="Made the book", welcomed=True)
    ddb.commit()
    return info


def welcome_kind(book: Book, m: Membership, household_id: int | None, user_id: int, *,
                 ignore_mark: bool = False) -> Literal["first_run", "partner"] | None:
    """Which welcome this person's membership plays (spec 7.1): the first run for whoever made the household book
    (a manager there with no adder, or who added themself), the partner welcome for anyone else, none in a Sample or
    once marked (a replay passes ignore_mark)."""
    if book.sample_of is not None:
        return None
    if m.welcome_seen_at is not None and not ignore_mark:
        return None
    if book.id == household_id and m.role == "manager" and m.created_by in (None, user_id):
        return "first_run"
    return "partner"


LAST_MANAGER = "A book needs at least one manager."
EMAIL_RULE = "Enter an email address."
NEW_NAME_RULE = "Enter their name, up to 80 characters."
INVITE_DAYS = 7


class MemberRefused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _managers(ddb: Session, book_id: int) -> int:
    from sqlalchemy import func
    return ddb.scalar(select(func.count()).select_from(Membership)
                      .where(Membership.book_id == book_id, Membership.role == "manager")) or 0


def _member(ddb: Session, book_id: int, user_id: int) -> Membership:
    m = ddb.get(Membership, (user_id, book_id))
    if m is None:
        raise MemberRefused("That person isn't in this book.", 404)
    return m


def set_role(ddb: Session, book_id: int, user_id: int, role: str, *, by: int, now: datetime | None = None) -> Membership:
    m = _member(ddb, book_id, user_id)
    if m.role == role:
        return m
    if m.role == "manager" and _managers(ddb, book_id) <= 1:
        raise MemberRefused(LAST_MANAGER, 409)
    ddb.add(MembershipChange(at=now or _now(), book_id=book_id, user_id=user_id, action="role_changed",
                             role_before=m.role, role_after=role, by_user_id=by))
    if role == "viewer":
        from steward.advisor.grants import revoke_for
        revoke_for(ddb, book_id, user_id, by, now or _now())   # a grant is a manager's, so it ends with the role
    m.role = role
    ddb.flush()
    return m


def remove_member(ddb: Session, book_id: int, user_id: int, *, by: int, now: datetime | None = None) -> None:
    m = _member(ddb, book_id, user_id)
    if m.role == "manager" and _managers(ddb, book_id) <= 1:
        raise MemberRefused(LAST_MANAGER, 409)
    ddb.add(MembershipChange(at=now or _now(), book_id=book_id, user_id=user_id, action="removed",
                             role_before=m.role, role_after=None, by_user_id=by))
    from steward.advisor.grants import revoke_for
    revoke_for(ddb, book_id, user_id, by, now or _now())       # a grant never outlives the membership (ruling 3)
    ddb.delete(m)
    ddb.flush()


def username_for(ddb: Session, email: str) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:32] or "person"
    name, n = base, 2
    while find_user(ddb, name) is not None:
        name, n = f"{base}{n}", n + 1
    return name


@dataclass
class InviteResult:
    """What invite() did. `kind` is "added" (they share a book with the inviter, so they are in) or "pending" (they
    must accept first; an account the invite made also gets a sign-in link). New and existing look the same in the
    answer."""
    kind: str
    user: User
    email: str
    role: str
    token: str | None = None
    sign_in: str | None = None   # a password-setting link, only as may_hand_sign_in_link allows


PLACEHOLDER = "invited-"   # the username of someone invited who has not joined yet


def give_real_username(ddb: Session, person: User | None) -> None:
    """Replaces the placeholder username of an invited person (when they set a password or accept)."""
    if person is not None and person.is_placeholder:
        person.username = username_for(ddb, person.email)
        person.is_placeholder = False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _shares_managed_book(ddb: Session, by: int, user_id: int) -> bool:
    """True when the person is in a book the inviter manages, so the inviter already sees and controls them there."""
    managed = select(Membership.book_id).where(Membership.user_id == by, Membership.role == "manager")
    return ddb.scalar(select(Membership.book_id).where(Membership.user_id == user_id,
                                                       Membership.book_id.in_(managed)).limit(1)) is not None


def _never_signed_in(ddb: Session, user_id: int) -> bool:
    return ddb.scalar(select(DbSession.id).where(DbSession.user_id == user_id).limit(1)) is None


def may_hand_sign_in_link(ddb: Session, by: int, person: User, t: datetime) -> bool:
    """Whether a link that chooses `person`'s password may be made for an invite from `by` and, with email off, handed
    to `by` to pass on (SEC-1). Only for an account an invite made that has never signed in, and only when every book
    it belongs to or has an open invite to is one `by` manages: the rule a manager's reset uses for members. A real
    account, even one that has never signed in, chooses its password through its own email or that kind of manager."""
    if not person.is_placeholder or not _never_signed_in(ddb, person.id):
        return False
    managed = select(Membership.book_id).where(Membership.user_id == by, Membership.role == "manager")
    elsewhere = (
        select(Membership.book_id).where(Membership.user_id == person.id, Membership.book_id.not_in(managed)),
        select(PendingInvite.id).where(PendingInvite.user_id == person.id, PendingInvite.accepted_at.is_(None),
                                       PendingInvite.expires_at > t, PendingInvite.book_id.not_in(managed)),
    )
    return all(ddb.scalar(q.limit(1)) is None for q in elsewhere)


def _sign_in_link(ddb: Session, user_id: int, t: datetime) -> str:
    """Makes the invite's password link. Only invite() calls it, behind may_hand_sign_in_link."""
    token = secrets.token_urlsafe(32)
    ddb.add(PasswordReset(user_id=user_id, token_hash=_hash(token), expires_at=t + timedelta(days=INVITE_DAYS)))
    return token


def invite(ddb: Session, book_id: int, email: object, display_name: object, role: str, *, by: int,
           now: datetime | None = None) -> InviteResult:
    """Invites a person to a book without ever revealing whether the email already has an account.

    - A person in a book the inviter manages is added at once (the inviter already controls them there).
    - Everyone else gets a pending_invite and an emailed token; nothing is added until that person, signed in,
      accepts. An unknown email first gets an account (a password nobody knows) and a sign-in link that works for
      INVITE_DAYS through the password-reset page (ruling 6), but no membership, so it shows up nowhere
      (/api/users, people) until they accept. A repeat gets a new link while may_hand_sign_in_link allows it; an
      existing real account never gets one (SEC-1), even if it has never signed in.
    The two cases answer identically, ask for a name in the same cases, and repeat the same way."""
    t = now or _now()
    clean = email.strip().lower() if isinstance(email, str) else ""
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", clean) or len(clean) > 200:
        raise MemberRefused(EMAIL_RULE)
    existing = ddb.scalar(select(User).where(User.email == clean))
    if existing is not None and _shares_managed_book(ddb, by, existing.id):
        if ddb.get(Membership, (existing.id, book_id)) is not None:
            raise MemberRefused(f"{existing.display_name} is already in this book.", 409)
        add_membership(ddb, existing.id, book_id, role, by=by, now=t)
        return InviteResult("added", existing, clean, role)
    name = display_name.strip() if isinstance(display_name, str) else ""
    if not name or len(name) > 80:
        raise MemberRefused(NEW_NAME_RULE)
    password_hash = hash_password(secrets.token_urlsafe(32))   # computed in both branches so timing doesn't tell
    if existing is not None and ddb.get(Membership, (existing.id, book_id)) is not None:
        raise MemberRefused(f"{existing.display_name} is already in this book.", 409)
    user = existing
    if user is None:
        # Neither the id nor the username may use up the next ones in line, or the next person to join would show
        # a manager that this address was new: a random id and a placeholder username, the real one given on accept.
        user_id = secrets.randbelow(2**40) + 2**20
        while ddb.get(User, user_id) is not None:
            user_id = secrets.randbelow(2**40) + 2**20
        user = User(id=user_id, username=PLACEHOLDER + secrets.token_hex(6), email=clean, display_name=name,
                    password_hash=password_hash, created_at=t, is_placeholder=True)
        ddb.add(user)
        ddb.flush()
    ddb.execute(delete(PendingInvite).where(PendingInvite.book_id == book_id, PendingInvite.user_id == user.id,
                                            PendingInvite.accepted_at.is_(None)))
    token = secrets.token_urlsafe(32)
    ddb.add(PendingInvite(book_id=book_id, user_id=user.id, role=role, invited_by=by, token_hash=_hash(token),
                          created_at=t, expires_at=t + timedelta(days=INVITE_DAYS)))
    ddb.flush()
    sign_in = _sign_in_link(ddb, user.id, t) if may_hand_sign_in_link(ddb, by, user, t) else None
    ddb.flush()
    return InviteResult("pending", user, clean, role, token, sign_in)


NO_INVITE = "That invite link isn't valid any more."


class InviteGone(ValueError):
    pass


def accept_invite(ddb: Session, user_id: int, token: object, *, now: datetime | None = None) -> Book:
    """Adds the signed-in person to the book of an unexpired, unaccepted invitation made out to them, if whoever
    invited them still manages that book. Anything else is InviteGone."""
    t = now or _now()
    if not isinstance(token, str) or not token:
        raise InviteGone(NO_INVITE)
    pend = ddb.scalar(select(PendingInvite).where(PendingInvite.token_hash == _hash(token),
                                                  PendingInvite.user_id == user_id,
                                                  PendingInvite.accepted_at.is_(None), PendingInvite.expires_at > t))
    book = ddb.get(Book, pend.book_id) if pend else None
    inviter = ddb.get(Membership, (pend.invited_by, pend.book_id)) if pend else None
    if pend is None or book is None or book.archived_at is not None or inviter is None or inviter.role != "manager":
        raise InviteGone(NO_INVITE)
    give_real_username(ddb, ddb.get(User, user_id))
    if ddb.get(Membership, (user_id, book.id)) is None:
        add_membership(ddb, user_id, book.id, pend.role, by=pend.invited_by, now=t)
    pend.accepted_at = t
    ddb.flush()
    return book


def pending_rows(ddb: Session, book_id: int) -> list[dict]:
    """The people a manager has invited who have not joined yet, as "Invited" rows with the typed email and nothing
    else. The id is the pending_invite row's own, the same kind of value for a new person and an existing account."""
    return [{"status": "Invited", "invite_id": str(p.id), "email": u.email, "role": p.role,
             "user_id": None, "username": None, "display_name": None}
            for p, u in ddb.execute(select(PendingInvite, User).join(User, User.id == PendingInvite.user_id)
                                    .where(PendingInvite.book_id == book_id, PendingInvite.accepted_at.is_(None),
                                           PendingInvite.expires_at > _now())
                                    .order_by(PendingInvite.id)).all()]


def cancel_invite(ddb: Session, book_id: int, invite_id: str, *, by: int, now: datetime | None = None) -> None:
    """Cancels an invitation: its pending_invite is deleted. When the invitation's account is unused (ruling 30), the
    account goes too, with its sign-in links, so the cancelled person can't set a password and land in no book."""
    pend = ddb.get(PendingInvite, int(invite_id)) if invite_id.isdigit() else None
    if pend is None or pend.book_id != book_id or pend.accepted_at is not None:
        raise MemberRefused(NO_SUCH_INVITE, 404)
    user_id = pend.user_id
    ddb.delete(pend)
    ddb.flush()
    _forget_unused_account(ddb, user_id, now or _now())


def _forget_unused_account(ddb: Session, user_id: int, t: datetime) -> None:
    """Deletes a placeholder account (made by an invite) that has never signed in, belongs to no book, has no other open invite, no passkey and no
    membership history. Anything else about the person stays."""
    person = ddb.get(User, user_id)
    if person is None or not person.is_placeholder or not _never_signed_in(ddb, user_id):
        return
    in_use = (
        select(Membership.book_id).where(Membership.user_id == user_id),
        select(PendingInvite.id).where(PendingInvite.user_id == user_id, PendingInvite.accepted_at.is_(None),
                                       PendingInvite.expires_at > t),
        select(Passkey.id).where(Passkey.user_id == user_id),
        select(AdvisorGrant.id).where(AdvisorGrant.user_id == user_id),
        select(MembershipChange.id).where(or_(MembershipChange.user_id == user_id,
                                              MembershipChange.by_user_id == user_id)),
    )
    if any(ddb.scalar(q.limit(1)) is not None for q in in_use):
        return
    ddb.execute(delete(PasswordReset).where(PasswordReset.user_id == user_id))
    ddb.execute(delete(PendingInvite).where(PendingInvite.user_id == user_id))   # expired ones
    ddb.delete(person)
    ddb.flush()


NO_SUCH_INVITE = "That invite isn't here."


def _what(role: str) -> str:
    return ("You can see everything in it but not change anything." if role == "viewer"
            else "You can see and change everything in it.")


def pending_email(base_url: str, inviter: str, book_name: str, role: str, token: str) -> tuple[str, str]:
    body = (f"{inviter} invited you to \"{book_name}\" in Steward as a {role}. Open this link while signed in to "
            f"accept. It works for {INVITE_DAYS} days.\n\n{base_url.rstrip('/')}/invite?token={token}\n")
    return f"You've been invited to {book_name}", body


def invite_email(base_url: str, inviter: str, book_name: str, person: User, role: str, sign_in: str,
                 token: str) -> tuple[str, str]:
    """The pending-invite email, plus a link to choose a password first for someone who has never signed in."""
    subject, body = pending_email(base_url, inviter, book_name, role, token)
    base = base_url.rstrip('/')
    return subject, (f"Hi {person.display_name},\n\n{body}\n"
                     f"If you have not signed in to Steward yet, choose a password first with this link. It works for "
                     f"{INVITE_DAYS} days and only from a device on the household's Tailscale network.\n\n"
                     f"{base}/reset?token={sign_in}&invite=1\n\n"
                     f"Sign in with this email address.\n")


def added_email(base_url: str, inviter: str, book_name: str, slug: str, role: str) -> tuple[str, str]:
    body = (f"{inviter} added you to \"{book_name}\" in Steward as a {role}. {_what(role)}\n\n"
            f"Sign in as usual: {base_url.rstrip('/')}/b/{slug}\n")
    return f"You've been added to {book_name}", body
