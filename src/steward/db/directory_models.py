"""The directory database (spec 2.2): people and sign-in, shared by every book, and the books and who belongs to
which. Its own metadata, its own file (data/directory.db) and its own key (HKDF info steward/directory). The four
sign-in tables have exactly the columns they had in steward.db, so the move copies them row for row."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy import false as sa_false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from steward.db.models import TZDateTime, utcnow

BOOK_KINDS: tuple[str, ...] = ("household", "parent")
ROLES: tuple[str, ...] = ("manager", "viewer")
KEY_SCHEMES: tuple[str, ...] = ("raw", "derived")
MEMBERSHIP_ACTIONS: tuple[str, ...] = ("added", "invited", "role_changed", "removed")


class DirectoryBase(DeclarativeBase):
    pass


class User(DirectoryBase):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)  # stored lowercase
    email: Mapped[str] = mapped_column(String(200), unique=True)    # stored lowercase
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())  # made by an invite, not yet joined
    # Phase 17 spec 3.6: the person's Celebrations (default on) and Sound (default off); None until they choose.
    celebrations: Mapped[bool | None] = mapped_column(Boolean)
    sound: Mapped[bool | None] = mapped_column(Boolean)


class Passkey(DirectoryBase):
    __tablename__ = "passkey"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    credential_id: Mapped[bytes] = mapped_column(unique=True)
    public_key: Mapped[bytes]
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class PasswordReset(DirectoryBase):
    __tablename__ = "password_reset"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class SetupLink(DirectoryBase):
    """The one-time link `steward setup` prints (release spec 2026-11-05, section 6): 32 random bytes kept only as
    their SHA-256, good for 30 minutes and once. A new link closes any older one still open."""
    __tablename__ = "setup_link"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Session(DirectoryBase):
    __tablename__ = "session"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device_label: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Book(DirectoryBase):
    """One family's finances: a database file under the data folder and its key scheme (spec 2.1, 2.3)."""
    __tablename__ = "book"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(10))
    owner_names: Mapped[str] = mapped_column(Text)        # JSON: [{"key": "jr", "label": "Person 1"}, ...]
    file: Mapped[str] = mapped_column(String(200))        # relative to the data folder
    key_scheme: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    sample_of: Mapped[int | None] = mapped_column(Integer)   # spec 8.2: the person whose Sample this is; no FK (plan D3)
    __table_args__ = (
        CheckConstraint("kind IN ('household', 'parent')", name="ck_book_kind"),
        CheckConstraint("key_scheme IN ('raw', 'derived')", name="ck_book_key_scheme"),
    )


class Membership(DirectoryBase):
    __tablename__ = "membership"
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    growth_seen: Mapped[int | None] = mapped_column(Integer)   # phase 17 spec 3.4: the growth stage this person last saw here
    welcome_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime)   # guided setup spec 7.1: when this person's welcome to this book ended; NULL plays it
    __table_args__ = (CheckConstraint("role IN ('manager', 'viewer')", name="ck_membership_role"),)


class MembershipChange(DirectoryBase):
    """Every change to who belongs to a book, kept even after the person's access is gone (spec 5)."""
    __tablename__ = "membership_change"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    action: Mapped[str] = mapped_column(String(12))
    role_before: Mapped[str | None] = mapped_column(String(8))
    role_after: Mapped[str | None] = mapped_column(String(8))
    by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))  # None: the move or the CLI
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("action IN ('added', 'invited', 'role_changed', 'removed')", name="ck_membership_change_action"),
    )


class PendingInvite(DirectoryBase):
    """An invitation to an account that already exists and shares no book with the inviter. It adds nothing until
    that person, signed in, uses the emailed link (POST /api/invites/accept)."""
    __tablename__ = "pending_invite"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    role: Mapped[str] = mapped_column(String(8))
    invited_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    __table_args__ = (CheckConstraint("role IN ('manager', 'viewer')", name="ck_pending_invite_role"),)


class DirectoryEvent(DirectoryBase):
    """The directory's event log (spec 8): a book that can't be opened is logged here by slug."""
    __tablename__ = "directory_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(40))
    book_id: Mapped[int | None] = mapped_column(ForeignKey("book.id"))
    message: Mapped[str] = mapped_column(Text)


class DirectoryMeta(DirectoryBase):
    __tablename__ = "directory_meta"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AdvisorGrant(DirectoryBase):
    """A Claude Code grant (spec 7, ruling 3): one person, one book, read-only, 30 days, revocable. Only the hash of
    the grant's text is kept; the text is shown once."""
    __tablename__ = "advisor_grant"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("book.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    issued_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class AppSetting(DirectoryBase):
    """A runtime setting chosen in the app (guided setup spec 4). .env wins: a value here is used only when the
    setting's variable isn't set at all. Secrets are sealed (spec 4.4) and never leave in an answer."""
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)   # one of app_settings.KEYS
    value: Mapped[str | None] = mapped_column(Text)                   # plain settings
    sealed: Mapped[bytes | None] = mapped_column(LargeBinary)         # secret settings
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    __table_args__ = (CheckConstraint("(value IS NULL) <> (sealed IS NULL)", name="ck_app_setting_one"),)
