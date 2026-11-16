"""SimpleFIN feeds (same-account spec, Data and Ongoing sync). A feed is one SimpleFIN account id ("sfin:<id>") and
the connection it comes through. Sync finds a Steward account by its feeds; Account.external_id stays the first feed's
id for imports and older code. An account has one feed, or several after a merge."""
from datetime import datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountFeed

NEW_ACCOUNT_MSG = "New account '{name}' from {bank} needs its type and owner set in Settings"


def add(db: Session, account: Account, ext: str, institution_id: int, name: str, at: datetime) -> AccountFeed:
    feed = AccountFeed(account_id=account.id, external_id=ext, institution_id=institution_id, name=name,
                       added_at=at, last_seen_at=at)
    db.add(feed)
    db.flush()
    return feed


def find(db: Session, ext: str) -> AccountFeed | None:
    """The feed with this SimpleFIN id. An account that carries the id but has no feed (made outside sync: the parent
    demo, a fixture, a restored row) gets its feed now, so sync doesn't make it a second time (Engineering choice 5)."""
    feed = db.scalar(select(AccountFeed).where(AccountFeed.external_id == ext))
    if feed is not None:
        return feed
    account = db.scalar(select(Account).where(Account.external_id == ext))
    if account is None:
        return None
    return add(db, account, ext, account.institution_id, account.name, account.created_at)


def account_of(db: Session, ext: str) -> Account | None:
    """find's account, without writing anything (categorize_fetched reads in a session it then rolls back)."""
    account_id = db.scalar(select(AccountFeed.account_id).where(AccountFeed.external_id == ext))
    if account_id is not None:
        return db.get(Account, account_id)
    return db.scalar(select(Account).where(Account.external_id == ext))


def seen(feed: AccountFeed, name: str, now: datetime) -> None:
    """SimpleFIN sent this feed again: its own name for it (a person's rename lives on the account), and when."""
    feed.name, feed.last_seen_at = name, now


def of(db: Session, account_id: int) -> list[AccountFeed]:
    return list(db.scalars(select(AccountFeed).where(AccountFeed.account_id == account_id).order_by(AccountFeed.id)))


def several(db: Session, account_id: int) -> bool:
    return (db.scalar(select(func.count()).select_from(AccountFeed).where(AccountFeed.account_id == account_id)) or 0) > 1


def depends_on(db: Session, institution_id: int) -> bool:
    """Something here needs this connection: an account of its own, or a feed into any account (Review Focus 5)."""
    return bool(db.scalar(select(or_(exists().where(Account.institution_id == institution_id),
                                     exists().where(AccountFeed.institution_id == institution_id)))))
