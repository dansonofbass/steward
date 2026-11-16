from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import Account, AccountType as T, BalanceSnapshot


def month_start(day: date) -> date:
    return day.replace(day=1)


# The net worth split (investment views spec, Net worth). Investable is the Plan's buckets plus 529s; accounts nobody
# has typed yet get their own line, so the lines always add up to net worth (Engineering choice 12).
SPLIT: dict[str, frozenset] = {
    "investable": frozenset({T.checking, T.savings, T.brokerage_taxable, T.k401, T.traditional_ira, T.roth_ira, T.hsa,
                             T.plan529}),
    "home_and_cars": frozenset({T.property, T.vehicle}),
    "owed": frozenset({T.mortgage, T.loan, T.credit}),
    "business": frozenset({T.business_checking, T.business_credit}),
    "unset": frozenset({T.unknown}),
}
INVESTABLE = SPLIT["investable"]


def _latest_per_account(db: Session, day: date) -> dict[int, int]:
    """Latest balance on or before `day` for each active account, picked in SQL."""
    newest = (
        select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.as_of).label("as_of"))
        .where(BalanceSnapshot.as_of <= day)
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    rows = db.execute(
        select(BalanceSnapshot.account_id, BalanceSnapshot.balance_cents)
        .join(newest, (newest.c.account_id == BalanceSnapshot.account_id) & (newest.c.as_of == BalanceSnapshot.as_of))
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .where(Account.is_active.is_(True))
    ).all()
    return dict(rows)


def net_worth_on(db: Session, day: date) -> int:
    return sum(_latest_per_account(db, day).values())


def by_type_on(db: Session, day: date) -> dict[str, int]:
    latest = _latest_per_account(db, day)
    types = dict(db.execute(select(Account.id, Account.type).where(Account.id.in_(latest.keys()))).all())
    out: dict[str, int] = {}
    for acct_id, cents in latest.items():
        out[types[acct_id].value] = out.get(types[acct_id].value, 0) + cents
    return out


def split_on(db: Session, day: date) -> dict[str, dict]:
    latest = _latest_per_account(db, day)
    types = dict(db.execute(select(Account.id, Account.type).where(Account.id.in_(latest.keys()))).all())
    out: dict[str, dict] = {k: {"cents": 0, "account_ids": []} for k in SPLIT}
    for aid in sorted(latest):
        line = next(k for k, members in SPLIT.items() if types[aid] in members)
        out[line]["cents"] += latest[aid]
        out[line]["account_ids"].append(aid)
    return out


def history_with_investable(db: Session, start: date, end: date) -> list[tuple[date, int, int]]:
    """Net worth and its investable part per day from start to end, using three queries.

    Matches net_worth_on: each active account contributes its latest snapshot on or before the day, and nothing
    before its first snapshot. The first query seeds the balances as of the day before `start`; the second loads only
    the snapshots inside the window; the third reads the account types.
    """
    latest = _latest_per_account(db, start - timedelta(days=1))
    rows = db.execute(
        select(BalanceSnapshot.account_id, BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
        .join(Account, Account.id == BalanceSnapshot.account_id)
        .where(BalanceSnapshot.as_of >= start, BalanceSnapshot.as_of <= end, Account.is_active.is_(True))
        .order_by(BalanceSnapshot.as_of, BalanceSnapshot.account_id)
    ).all()
    investable = {aid for aid, t in db.execute(select(Account.id, Account.type)).all() if t in INVESTABLE}
    i, pts, d = 0, [], start
    while d <= end:
        while i < len(rows) and rows[i][1] <= d:
            latest[rows[i][0]] = rows[i][2]
            i += 1
        pts.append((d, sum(latest.values()), sum(c for aid, c in latest.items() if aid in investable)))
        d += timedelta(days=1)
    return pts


def history(db: Session, start: date, end: date) -> list[tuple[date, int]]:
    """Net worth per day from start to end (history_with_investable without its investable part)."""
    return [(d, n) for d, n, _ in history_with_investable(db, start, end)]
