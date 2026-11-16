"""One home value (roadmap 11, JR Oct 26): what the home would sell for is the balance of the home's Property account.

Profile's "What the home would sell for today" is the fact `home.value_cents`; the Accounts tab, net worth and Care read
property accounts. The two are kept as one value: saving the fact records the linked Home account's balance on the same
day, and a balance entered on that account records the fact. The link is the fact `home.account_id` (internal, not
settable through /facts). With no link yet, the first save links the household's one active property account, or one
named Home, or makes a manual Property account called Home. Other properties stay plain accounts.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType, Fact, Owner, Source
from steward.services.accounts import latest_balance, manual_institution, record_balance

VALUE_KEY = "home.value_cents"
LINK_KEY = "home.account_id"
HOME_NAME = "Home"
FROM_ACCOUNT_NOTE = "From the Home account's balance"


def _latest_fact(db: Session, key: str) -> Fact | None:
    return db.scalar(select(Fact).where(Fact.key == key).order_by(Fact.as_of.desc(), Fact.id.desc()).limit(1))


def linked_account(db: Session) -> Account | None:
    """The account the home value lives in, if one has been linked and is still a property account."""
    link = _latest_fact(db, LINK_KEY)
    if link is None or not link.value.isdigit():
        return None
    a = db.get(Account, int(link.value))
    return a if a is not None and a.type == AccountType.property else None


def main_mortgage(db: Session) -> Account | None:
    """The mortgage on where you live, the one the Plan models (profile spec P19; Engineering choice 6): the home's
    linked mortgage while it is active; before any property links one, the first active mortgage no property links,
    which is what the Plan read before Profile."""
    home = linked_account(db)
    if home is not None and home.loan_id is not None:
        m = db.get(Account, home.loan_id)
        return m if m is not None and m.is_active and m.type == AccountType.mortgage else None
    taken = select(Account.loan_id).where(Account.type == AccountType.property, Account.loan_id.is_not(None))
    return db.scalar(select(Account).where(Account.is_active.is_(True), Account.type == AccountType.mortgage,
                                           Account.id.not_in(taken)).order_by(Account.id).limit(1))


def _pick_or_make(db: Session, owners: list[str], as_of: date) -> Account:
    props = list(db.scalars(select(Account).where(Account.type == AccountType.property).order_by(Account.id)))
    active = [a for a in props if a.is_active]
    named = [a for a in props if a.name.strip().lower() == HOME_NAME.lower()]
    if len(active) == 1:
        return active[0]
    if len(named) == 1:
        return named[0]
    if active:   # several, none called Home: the largest is the home, as Care takes it
        return max(active, key=lambda a: ((latest_balance(db, a.id) or (as_of, 0))[1], -a.id))
    owner = Owner.joint.value if Owner.joint.value in owners else owners[0]
    a = Account(institution_id=manual_institution(db).id, name=HOME_NAME, type=AccountType.property, owner=owner,
                source=Source.manual)
    db.add(a)
    db.flush()
    return a


def _link(db: Session, a: Account, as_of: date) -> None:
    db.add(Fact(key=LINK_KEY, value=str(a.id), as_of=as_of))
    db.flush()


def value_saved(db: Session, cents: int, as_of: date, owners: list[str]) -> Account:
    """Profile saved what the home would sell for: the Home account's balance becomes that value on that day. Its bank
    can't be told, so a linked account that updates itself from a bank is left as it is."""
    a = linked_account(db)
    if a is None:
        a = _pick_or_make(db, owners, as_of)
        _link(db, a, as_of)
    if not a.is_active:
        a.is_active = True           # the household says it owns the home, so its account shows again
    if a.source == Source.manual:
        record_balance(db, a.id, as_of, cents)
    return a


def balance_saved(db: Session, account_id: int, cents: int, as_of: date) -> None:
    """A balance was entered on an account by hand: when it is the Home account, Profile's value follows it, unless
    Profile already has a later answer."""
    a = linked_account(db)
    if a is None or a.id != account_id:
        return
    fact = _latest_fact(db, VALUE_KEY)
    if fact is not None and fact.as_of > as_of:
        return
    db.add(Fact(key=VALUE_KEY, value=str(cents), as_of=as_of, note=FROM_ACCOUNT_NOTE))
    db.flush()


def current_value(db: Session) -> int | None:
    """The home's value: the linked account's latest balance, or Profile's answer when nothing is linked."""
    a = linked_account(db)
    if a is not None and a.is_active:
        latest = latest_balance(db, a.id)
        if latest is not None:
            return latest[1]
    fact = _latest_fact(db, VALUE_KEY)
    return int(fact.value) if fact is not None and fact.value.lstrip("-").isdigit() else None
