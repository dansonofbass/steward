"""Same-account spec, Detecting a duplicate. A SimpleFIN account this book has no feed for looks like an account it
has when all of these hold:
1. the same bank: the same SimpleFIN org id, or before one is recorded on either side, the same bank name;
2. the same name: the incoming name equals the bank's own name for the account (kept on its feed) or the account's
   name in the book (a person's rename), without case, with spaces collapsed and quotes made straight;
3. the same money: at least 2 of its transactions match (same amount, within 3 days, one to one), or with fewer than
   2 to compare, balances within $1 from within 3 days of each other, or a reconnect: the existing account's feeds
   are all dead (none seen in the latest sync) and came before the live one, so its balance stopped where the new
   feed's carries on and only the name and bank can tell. And when both sides are live (sent in the same sync),
   balances from within 3 days of each other that differ by more than $1 or 0.5% are two accounts, whatever rows
   coincide: one account seen through two logins shows one balance;
4. the account is active and isn't fed by this same connection: two accounts with one name on one login are two.
Nothing here writes."""
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountFeed, Institution, SameAccountAnswer, SimplefinLink, Transaction
from steward.services.accounts import latest_balance
from steward.services.simplefin.client import SfAccount
from steward.services.txn_match import WINDOW_DAYS, pair_up

MIN_MATCHES = 2
BALANCE_CENTS = 100
LIVE_APART_PER_MILLE = 5                 # two live balances further apart than 0.5% (or $1) are two accounts

Balance = tuple[date, int]


# Typographic quotes a bank's name may carry one day and not the next ("New York\u2019s" against "New York's").
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u201b": "'", "\u2032": "'", "`": "'",
                         "\u00b4": "'", "\u201c": '"', "\u201d": '"', "\u201f": '"', "\u2033": '"'})


def norm(name: str | None) -> str:
    """A name as rules 1 and 2 compare it: compatibility-normalized, quotes made straight, spaces collapsed, no case."""
    return " ".join(unicodedata.normalize("NFKC", name or "").translate(_QUOTES).split()).casefold()


@dataclass(frozen=True)
class Money:
    same: bool            # rule 3 holds
    matches: int          # one-to-one matches found
    same_balance: bool    # within $1, from within 3 days


@dataclass(frozen=True)
class Found:
    account: Account
    money: Money


def same_bank(inst: Institution, org_id: str | None, bank_name: str) -> bool:
    """Rule 1. Two recorded org ids decide; until both sides have one, the bank's name does."""
    if inst.org_id and org_id:
        return inst.org_id == org_id
    return norm(inst.name) == norm(bank_name)


def active_feeds(db: Session) -> dict[int, list[tuple[AccountFeed, Institution]]]:
    """Every active account's feeds with their institutions, by account id."""
    rows = db.execute(select(AccountFeed, Institution)
                      .join(Institution, Institution.id == AccountFeed.institution_id)
                      .join(Account, Account.id == AccountFeed.account_id)
                      .where(Account.is_active.is_(True))
                      .order_by(AccountFeed.account_id, AccountFeed.id)).all()
    out: dict[int, list[tuple[AccountFeed, Institution]]] = {}
    for feed, inst in rows:
        out.setdefault(feed.account_id, []).append((feed, inst))
    return out


def apart_by_balance(x: Balance | None, y: Balance | None) -> bool:
    """Rule 3 for two live feeds: balances from within 3 days of each other that differ by more than $1 or 0.5% of
    the larger, whichever is more."""
    if x is None or y is None or abs((x[0] - y[0]).days) > WINDOW_DAYS:
        return False
    allowed = max(BALANCE_CENTS, max(abs(x[1]), abs(y[1])) * LIVE_APART_PER_MILLE // 1000)
    return abs(x[1] - y[1]) > allowed


def latest_sync(db: Session) -> datetime | None:
    """When the book last synced: a feed seen then is live. After a sync it is that sync (run_sync sets it before
    the check after the sync runs)."""
    return db.scalar(select(SimplefinLink.last_sync_at).where(SimplefinLink.last_sync_at.is_not(None))
                     .order_by(SimplefinLink.last_sync_at.desc()).limit(1))


def money(db: Session, account_id: int, rows: list[tuple[date, int]], balance: Balance | None, *,
          replaced: bool = False) -> Money:
    """Rule 3: rows and a balance from elsewhere against this account's own (Engineering choice 7). `replaced` is a
    reconnect (see `reconnected`): with fewer than 2 rows to compare, it is the same money whatever the balances."""
    latest = latest_balance(db, account_id)
    same_balance = (balance is not None and latest is not None and abs(latest[1] - balance[1]) <= BALANCE_CENTS
                    and abs((latest[0] - balance[0]).days) <= WINDOW_DAYS)
    existing: list[tuple[int, date, int]] = []
    if rows:
        lo = min(d for d, _ in rows) - timedelta(days=WINDOW_DAYS)
        hi = max(d for d, _ in rows) + timedelta(days=WINDOW_DAYS)
        existing = [tuple(r) for r in db.execute(
            select(Transaction.id, Transaction.posted_at, Transaction.amount_cents)
            .where(Transaction.account_id == account_id, Transaction.posted_at >= lo, Transaction.posted_at <= hi))]
    matches = len(pair_up(rows, existing))
    comparable = len(rows) >= MIN_MATCHES and len(existing) >= MIN_MATCHES
    return Money(matches >= MIN_MATCHES if comparable else (same_balance or replaced), matches, same_balance)


def in_book(db: Session, keep_id: int, other_id: int, *, replaced: bool = False) -> Money:
    """Rule 3 between two accounts in the book, as of now: the other's feed rows and balance against the kept one's
    (the one-time check, and the count a pair question shows)."""
    rows = [tuple(r) for r in db.execute(select(Transaction.posted_at, Transaction.amount_cents).where(
        Transaction.account_id == other_id, Transaction.feed_id.is_not(None)))]
    return money(db, keep_id, rows, latest_balance(db, other_id), replaced=replaced)


def reconnected(dead: list[tuple[AccountFeed, Institution]], live: list[tuple[AccountFeed, Institution]],
             since: datetime | None) -> bool:
    """Rule 3's reconnect, between two accounts in the book: no feed of `dead` was seen in the latest sync (`since`),
    one of `live` was, and `dead`'s newest feed came before `live`'s newest. A connection deleted at SimpleFIN and added
    again looks like this: the old balance stopped days ago and a 529 may have no rows, so neither can match."""
    if since is None or not dead or not live:
        return False
    if any(f.last_seen_at >= since for f, _ in dead) or not any(f.last_seen_at >= since for f, _ in live):
        return False
    return max(f.added_at for f, _ in dead) < max(f.added_at for f, _ in live)


def find_candidate(db: Session, a: SfAccount, org_id: str | None, bank_name: str,
                   conn_institution_id: int | None, *, live: Mapping[str, Balance] | None = None) -> Found | None:
    """The account this incoming SimpleFIN account looks like, if any. When several do, the most matches wins, then a
    same balance, then the oldest (Engineering choice 8). A pair answered "different" is never found again. `live` is
    this sync's balance for each feed it fetched without a problem: an account it fetched too, whose balance differs,
    is a different account (rule 3), and one it fetched none of the feeds of is dead, so this one may be its
    reconnect."""
    ext = f"sfin:{a.id}"
    refused = set(db.scalars(select(SameAccountAnswer.account_id).where(
        SameAccountAnswer.held_external_id == ext, SameAccountAnswer.answer == "different")))
    rows = [(t.posted_at, t.amount_cents) for t in a.transactions]
    incoming = (a.balance_date, a.balance_cents)
    found: list[tuple[Account, bool]] = []
    for account_id, fs in active_feeds(db).items():
        if account_id in refused:
            continue
        if conn_institution_id is not None and any(f.institution_id == conn_institution_id for f, _ in fs):
            continue                                                       # rule 4
        acct = db.get(Account, account_id)
        if norm(a.name) not in names(fs, acct):
            continue                                                       # rule 2
        if not any(same_bank(inst, org_id, bank_name) for _, inst in fs):
            continue                                                       # rule 1
        theirs = [live[f.external_id] for f, _ in fs if live is not None and f.external_id in live]
        if theirs and all(apart_by_balance(incoming, b) for b in theirs):
            continue                                                       # rule 3: both live, two balances
        found.append((acct, live is not None and not theirs))             # rule 3: no feed of it live, a reconnect
    best: Found | None = None
    for acct, dead in sorted(found, key=lambda x: (x[0].created_at, x[0].id)):
        m = money(db, acct.id, rows, incoming, replaced=dead)
        if m.same and (best is None or (m.matches, m.same_balance) > (best.money.matches, best.money.same_balance)):
            best = Found(acct, m)
    return best


def feed_names(feeds: list[tuple[AccountFeed, Institution]]) -> set[str]:
    """The bank's own names for an account: what SimpleFIN calls each of its feeds."""
    return {norm(f.name) for f, _ in feeds}


def names(feeds: list[tuple[AccountFeed, Institution]], account: Account) -> set[str]:
    """Every name rule 2 finds an account by: its feeds' names and the name it has in the book."""
    return feed_names(feeds) | {norm(account.name)}


def alike(a: Account, a_feeds: list[tuple[AccountFeed, Institution]], b: Account,
          b_feeds: list[tuple[AccountFeed, Institution]]) -> bool:
    """Rules 1, 2 and 4 between two accounts already in the book: no connection in common, one's SimpleFIN name
    among the other's names, and one bank."""
    if {f.institution_id for f, _ in a_feeds} & {f.institution_id for f, _ in b_feeds}:
        return False
    if not (feed_names(a_feeds) & names(b_feeds, b) or feed_names(b_feeds) & names(a_feeds, a)):
        return False
    return any(same_bank(ia, ib.org_id, ib.name) for _, ia in a_feeds for _, ib in b_feeds)


def live_apart(db: Session, a_id: int, a_feeds: list[tuple[AccountFeed, Institution]], b_id: int,
               b_feeds: list[tuple[AccountFeed, Institution]], since: datetime | None) -> bool:
    """Rule 3 between two accounts in the book when both were seen in the latest sync (`since`): their latest
    balances, from within 3 days of each other, differ by more than $1 or 0.5%."""
    if since is None:
        return False
    if not (any(f.last_seen_at >= since for f, _ in a_feeds) and any(f.last_seen_at >= since for f, _ in b_feeds)):
        return False
    return apart_by_balance(latest_balance(db, a_id), latest_balance(db, b_id))
