"""Shared set-ups for the same-account tests: two Betterment logins through the fake SimpleFIN, JR's and Sam's, that
both carry the joint account, and (from Task 5) accounts already in the book."""
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from steward.db.models import (Account, AccountFeed, AccountType, BalanceSnapshot, Base, HeldFeed, Institution,
                               SimplefinLink, Source, Transaction)
from steward.services.simplefin.client import claim
from steward.services.simplefin.sync import run_sync

H = ("testserver",)
NOW = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)      # Oct 27, 1 PM in the household's time zone
LATER = NOW + timedelta(hours=6)


def E(d: date, h: int = 19) -> int:
    """A SimpleFIN epoch: 19:00 UTC is noon in the household's time zone, so the row posts on `d`."""
    return int(datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc).timestamp())


# The joint account's last week: a deposit, two $5 coffees on one day, a fee and a dividend.
JOINT_DAYS = [(date(2026, 10, 21), 500_00, "DEPOSIT"), (date(2026, 10, 23), -5_00, "COFFEE"),
              (date(2026, 10, 23), -5_00, "COFFEE"), (date(2026, 10, 24), -12_50, "ADVISORY FEE"),
              (date(2026, 10, 26), 31_07, "DIVIDEND")]
BALANCE = 84_210_00
BALANCE_DAY = date(2026, 10, 27)


def txns(prefix: str, days=JOINT_DAYS) -> list[tuple]:
    """The fake's rows for one login: the same transactions, with that login's own ids."""
    return [(f"{prefix}-{i}", E(d), cents, desc) for i, (d, cents, desc) in enumerate(days)]


def linked(db, http) -> SimplefinLink:
    access = claim(http, "http://testserver/claim/same", allowed_hosts=H)
    link = SimplefinLink(access_url=access, claimed_at=NOW)
    db.add(link)
    db.commit()
    return link


def sync(db, http, link, at=NOW, household=True):
    res = run_sync(db, http, link, at, model=None, allowed_hosts=H, household=household)
    db.commit()
    return res


def jr_login(state, joint_name="Joint Taxable") -> None:
    state.add_account("jr", "Betterment", "betterment", "jr-joint", BALANCE, E(BALANCE_DAY), txns=txns("jr"),
                      name=joint_name)
    state.add_account("jr", "Betterment", "betterment", "jr-ira", 12_000_00, E(BALANCE_DAY), name="JR IRA")


def sam_login(state, joint_name="Joint Taxable", extra=()) -> None:
    state.add_account("sam", "Betterment", "betterment", "sam-joint", BALANCE, E(BALANCE_DAY),
                      txns=txns("sam") + list(extra), name=joint_name)
    state.add_account("sam", "Betterment", "betterment", "sam-ira", 9_500_00, E(BALANCE_DAY), name="Sam IRA")


def feed_account(db, ext: str) -> Account | None:
    account_id = db.scalar(select(AccountFeed.account_id).where(AccountFeed.external_id == ext))
    return None if account_id is None else db.get(Account, account_id)


# Accounts already in the book (Task 5 on).
AT_OLD = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)
AT_NEW = datetime(2026, 10, 27, 17, 0, tzinfo=timezone.utc)


def bank(db, conn_id: str) -> Institution:
    inst = Institution(name="Betterment", source=Source.simplefin, simplefin_org_id=conn_id, org_id="betterment")
    db.add(inst)
    db.flush()
    return inst


def booked(db, key: str, inst: Institution, created: datetime, *, days=JOINT_DAYS, balance=(BALANCE_DAY, BALANCE),
           type_=AccountType.brokerage_taxable, name="Joint Taxable") -> Account:
    """A SimpleFIN account already in the book: its feed, its rows (bank ids "<key>-<n>") and its balance."""
    ext = f"sfin:{key}-joint"
    a = Account(institution_id=inst.id, name=name, type=type_, owner="joint", source=Source.simplefin,
                external_id=ext, created_at=created)
    db.add(a)
    db.flush()
    feed = AccountFeed(account_id=a.id, external_id=ext, institution_id=inst.id, name=name, added_at=created,
                       last_seen_at=NOW)
    db.add(feed)
    db.flush()
    for i, (d, cents, desc) in enumerate(days):
        db.add(Transaction(account_id=a.id, posted_at=d, amount_cents=cents, raw_description=desc,
                           external_id=f"{key}-{i}", feed_id=feed.id, imported_at=created))
    db.add(BalanceSnapshot(account_id=a.id, as_of=balance[0], balance_cents=balance[1]))
    db.commit()
    return a


def jr_account(db, **kw) -> Account:
    return booked(db, "jr", bank(db, "jr"), AT_OLD, **kw)


def in_book_pair(db, *, keys=("jr", "sam"), name="Joint Taxable", other_days=JOINT_DAYS,
                 other_balance=(BALANCE_DAY, BALANCE)) -> tuple[Account, Account]:
    """JR's joint account and Sam's copy of it, both already in the book (the one-time check's case). The newer one
    is still "Type not set yet", as a duplicate usually is."""
    keep = booked(db, keys[0], bank(db, keys[0]), AT_OLD, name=name)
    other = booked(db, keys[1], bank(db, keys[1]), AT_NEW, name=name, days=other_days, balance=other_balance,
                   type_=AccountType.unknown)
    return keep, other


def held_copy(db, keep: Account, *, days=JOINT_DAYS, balance=(BALANCE_DAY, BALANCE)) -> HeldFeed:
    """Sam's login's copy of `keep`, held for a question, with its own bank ids ("sam-<n>")."""
    h = HeldFeed(external_id="sfin:sam-joint", institution_id=bank(db, "sam").id, name="Joint Taxable",
                 currency="USD", candidate_account_id=keep.id, balance_cents=balance[1], balance_date=balance[0],
                 payload=json.dumps([{"id": f"sam-{i}", "posted": d.isoformat(), "amount_cents": c, "description": s}
                                     for i, (d, c, s) in enumerate(days)]),
                 first_seen_at=LATER, last_seen_at=LATER)
    db.add(h)
    db.commit()
    return h


def txn(db, account: Account, ext: str) -> Transaction:
    return db.scalar(select(Transaction).where(Transaction.account_id == account.id, Transaction.external_id == ext))


SNAPSHOT_SKIP = frozenset({"undo_entry", "watch_state"})   # the entries themselves, and the categorizer's wave marker


def snapshot(db) -> dict[str, list[tuple]]:
    """Every row of every book table, as stored, to compare a book before an action and after its undo."""
    db.flush()
    return {t.name: sorted((tuple(r) for r in db.execute(select(t))), key=repr)
            for t in Base.metadata.sorted_tables if t.name not in SNAPSHOT_SKIP}
