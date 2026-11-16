"""They're different (same-account spec, Asking), and the one-time check for pairs already in the book (decision 6).

A held feed kept apart becomes a normal new account: its payload is ingested now (rules only; the catch-up asks the
model later), so its history isn't lost, and the "set its type and owner" step follows as for any new account. A pair
in the book is just remembered. Either is recorded for Undo (action different). Undo keeps the "New account" line (it
never deletes an event_log row) and resolves it, since the account it asked about goes."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from steward.db.models import (Account, AccountType, BalanceSnapshot, HeldFeed, Institution, Owner,
                               SameAccountAnswer, Source, WatchState)
from steward.events import log_event
from steward.services import feeds
from steward.services.accounts import record_balance
from steward.services.ingest import ingest_rows
from steward.services.same_account import detect
from steward.services.same_account import held as held_feeds
from steward.services.same_account.journal import Journal, recording

# The one-time check's own version, kept in the book with the other internal marks (watch_state): the check runs once
# at the start-up that finds the book without it. 2: a reconnect, a dead feed's account and a live one with its name
# at its bank (Oct 29).
CHECK_KEY = "same_account_check"
CHECK_VERSION = "2"


def keep_apart(db: Session, question: HeldFeed | SameAccountAnswer, user_id: int, now: datetime) -> str:
    """Answer "They're different". Returns the undo token; the caller commits."""
    with recording(db) as j:
        if isinstance(question, HeldFeed):
            _held_apart(db, j, question, user_id, now)
        else:
            j.change(SameAccountAnswer, SameAccountAnswer.id == question.id, answer="different", answered_at=now,
                     answered_by=user_id)
    return j.save(user_id, "different", now)


def _held_apart(db: Session, j: Journal, h: HeldFeed, user_id: int, now: datetime) -> None:
    name, ext, bank_name = h.name, h.external_id, db.get(Institution, h.institution_id).name
    acct = Account(institution_id=h.institution_id, name=name, type=AccountType.unknown, owner=Owner.joint.value,
                   source=Source.simplefin, external_id=ext, currency=h.currency, is_active=True, created_at=now)
    db.add(acct)
    j.add(acct)
    feed = feeds.add(db, acct, ext, h.institution_id, name, now)
    j.add(feed)
    rows = held_feeds.rows(h)
    if rows:
        j.add(*ingest_rows(db, acct, rows, batch=None, now=now, model=None, household=True, feed_id=feed.id))
    record_balance(db, acct.id, h.balance_date, h.balance_cents)
    j.add_key(BalanceSnapshot, account_id=acct.id, as_of=h.balance_date)
    j.log(log_event(db, "info", "system", feeds.NEW_ACCOUNT_MSG.format(name=name, bank=bank_name), actionable=True))
    answer = SameAccountAnswer(account_id=h.candidate_account_id, other_account_id=acct.id, held_external_id=ext,
                               answer="different", match_count=0, created_at=h.first_seen_at, answered_at=now,
                               answered_by=user_id)
    db.add(answer)
    j.add(answer)
    j.remove(HeldFeed, HeldFeed.id == h.id)


def check_book(db: Session, now: datetime, only: set[int] | None = None) -> int:
    """Pairs of active SimpleFIN accounts already in the book that meet rules 1, 2 and 4, with the same money by their
    stored transactions (the newer account's feed rows against the older's), or a reconnect with too few rows to
    compare (one side's feeds dead, the other's live), and not two live balances apart (rule 3), are raised as open
    questions. Each pair is raised once; a pair asked or answered before is skipped. The older account is the one a
    merge keeps. `only` limits it to pairs with one of those accounts in them (the check after a
    sync). Returns how many it raised; the caller commits."""
    by = detect.active_feeds(db)
    accounts = sorted((db.get(Account, aid) for aid in by), key=lambda a: (a.created_at, a.id))
    asked = {frozenset(p) for p in db.execute(select(SameAccountAnswer.account_id, SameAccountAnswer.other_account_id)
                                              .where(SameAccountAnswer.other_account_id.is_not(None))).all()}
    since = detect.latest_sync(db)
    raised = 0
    for i, a in enumerate(accounts):
        for b in accounts[i + 1:]:
            if only is not None and a.id not in only and b.id not in only:
                continue
            if frozenset((a.id, b.id)) in asked or not detect.alike(a, by[a.id], b, by[b.id]):
                continue
            if detect.live_apart(db, a.id, by[a.id], b.id, by[b.id], since):
                continue
            reconnect = detect.reconnected(by[a.id], by[b.id], since) or detect.reconnected(by[b.id], by[a.id], since)
            m = detect.in_book(db, a.id, b.id, replaced=reconnect)
            if m.same:
                db.add(SameAccountAnswer(account_id=a.id, other_account_id=b.id, answer="open",
                                         match_count=m.matches, created_at=now))
                asked.add(frozenset((a.id, b.id)))
                raised += 1
    db.flush()
    return raised


def check_once(engine: Engine, was: str | None, now: datetime) -> int:
    """Engineering choice 6: once per version of the check (CHECK_VERSION), at the start-up that finds a household book
    without it: the one that upgraded it to feeds (0027), and again after detection learns a rule, so pairs already in
    the book are asked about without anyone running the CLI. A new book (was None) has nothing to look at; it is only
    marked."""
    with Session(engine) as db:
        mark = db.get(WatchState, CHECK_KEY)
        if mark is not None and mark.value == CHECK_VERSION:
            return 0
        raised = 0 if was is None else check_book(db, now)
        if mark is None:
            db.add(WatchState(key=CHECK_KEY, value=CHECK_VERSION, updated_at=now))
        else:
            mark.value, mark.updated_at = CHECK_VERSION, now
        db.commit()
    return raised
