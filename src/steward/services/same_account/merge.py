"""Merging (same-account spec, Merging): a held feed into the account it looks like, or an account in the book into
another. It runs in the caller's transaction and records one undo entry (action merge) with everything it changed.
The kept account keeps its own history, categories, notes, type, owner and links; the other's feed joins it."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from steward.db.models import (Account, AccountFeed, AccountType, AdvisorAlias, BalanceSnapshot, BusinessRule,
                               CategorySource, Child, DuplicateKeep, EventLog, Fact, FeedTxnAlias, Flag, FlagEvent,
                               HeldFeed, Holding, ImportBatch, InventoryItem, MailOutbox, PositionsImport,
                               SameAccountAnswer, SetAside, SetAsideMatch, TaxState, Transaction, TransactionNote,
                               StatementLayout, StatementStage, WatchKnown)
from steward.services import feeds
from steward.services.accounts import latest_balance, record_balance
from steward.services.home_value import LINK_KEY
from steward.services.ingest import ingest_rows
from steward.services.same_account import held as held_feeds
from steward.services.same_account.journal import Journal, recording
from steward.services.transfers import pair_transfers, unpair_peers
from steward.services.txn_match import WINDOW_DAYS, copies, pair_up, record_aliases

NO_SUCH_ACCOUNT = "No such account."
NOT_ITSELF = "Choose another account to merge into."
NOT_OPEN = "Choose an account that's still open."
NOT_SAME_TYPE = "Choose an account of the same type."
NOT_FEEDS = "Only two accounts that come from a bank can be merged here."


class MergeRefused(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Merged:
    kept_id: int
    kept_name: str
    dropped: int       # copies dropped
    kept_new: int      # new rows kept (a held feed) or rows moved over (an account in the book)
    undo: str | None = None


def check(db: Session, keep: Account | None, other: Account | None, *, same_type: bool = True) -> None:
    """Merge into…'s rules (Engineering choice 12): two active accounts from a bank, with feeds, of one type. The
    account merged away may still be Type not set yet, as a newer duplicate often is: the kept account's type stands.
    The card's merges pass same_type=False."""
    if keep is None or other is None:
        raise MergeRefused(NO_SUCH_ACCOUNT, 404)
    if keep.id == other.id:
        raise MergeRefused(NOT_ITSELF)
    if not keep.is_active or not other.is_active:
        raise MergeRefused(NOT_OPEN)
    if not feeds.of(db, keep.id) or not feeds.of(db, other.id):
        raise MergeRefused(NOT_FEEDS)
    if same_type and other.type != AccountType.unknown and keep.type != other.type:
        raise MergeRefused(NOT_SAME_TYPE)


def copies_in_book(db: Session, keep_id: int, other_id: int) -> dict[int, int]:
    """The other account's transactions that copy one in the kept account, by id → the kept one's id: a feed's row
    against the kept account's feed rows (decision 4), and any row whose bank id the kept account already has
    (Engineering choice 13)."""
    rows = db.execute(select(Transaction.id, Transaction.posted_at, Transaction.amount_cents, Transaction.feed_id,
                             Transaction.external_id)
                      .where(Transaction.account_id == other_id).order_by(Transaction.posted_at, Transaction.id)).all()
    fed = [r for r in rows if r.feed_id is not None]
    out: dict[int, int] = {}
    if fed:
        lo = min(r.posted_at for r in fed) - timedelta(days=WINDOW_DAYS)
        hi = max(r.posted_at for r in fed) + timedelta(days=WINDOW_DAYS)
        theirs = [tuple(r) for r in db.execute(
            select(Transaction.id, Transaction.posted_at, Transaction.amount_cents).where(
                Transaction.account_id == keep_id, Transaction.feed_id.is_not(None),
                Transaction.posted_at >= lo, Transaction.posted_at <= hi))]
        pairs = pair_up([(r.posted_at, r.amount_cents) for r in fed], theirs)
        out = {fed[i].id: tid for i, tid in pairs.items()}
    known = dict(db.execute(select(Transaction.external_id, Transaction.id).where(
        Transaction.account_id == keep_id, Transaction.external_id.is_not(None))).all())
    for r in rows:
        if r.id not in out and r.external_id is not None and r.external_id in known:
            out[r.id] = known[r.external_id]
    return out


def preview(db: Session, keep_id: int, other_id: int) -> tuple[int, int]:
    """What Merge into… would do: (dropped, moved over). Writes nothing."""
    dropped = len(copies_in_book(db, keep_id, other_id))
    total = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.account_id == other_id)) or 0
    return dropped, total - dropped


def merge(db: Session, keep_id: int, other: HeldFeed | int, *, user_id: int, now: datetime) -> Merged:
    """Merge a held feed, or the account with id `other`, into the account `keep_id`. The caller commits."""
    keep = db.get(Account, keep_id)
    with recording(db) as j:
        if isinstance(other, HeldFeed):
            dropped, kept_new = _held(db, j, keep, other, now)
        else:
            dropped, kept_new = _account(db, j, keep, db.get(Account, other), now)
    token = j.save(user_id, "merge", now)
    keep = db.get(Account, keep_id)
    return Merged(keep.id, keep.name, dropped, kept_new, token)


def _held(db: Session, j: Journal, keep: Account, h: HeldFeed, now: datetime) -> tuple[int, int]:
    """Merging a held feed: it becomes a feed of the kept account; its copies are dropped and remembered, the rest
    ingested (rules only: the catch-up asks the model later), its balance recorded if newer; the held row goes."""
    feed = AccountFeed(account_id=keep.id, external_id=h.external_id, institution_id=h.institution_id, name=h.name,
                       added_at=now, last_seen_at=h.last_seen_at)
    db.add(feed)
    j.add(feed)
    rows = held_feeds.rows(h)
    matched = copies(db, keep.id, feed.id, rows)
    j.add(*record_aliases(db, keep.id, feed.id, rows, matched, now))
    fresh = [r for i, r in enumerate(rows) if i not in matched]
    if fresh:
        j.add(*ingest_rows(db, keep, fresh, batch=None, now=now, model=None, household=True, feed_id=feed.id))
    latest = latest_balance(db, keep.id)
    if latest is None or h.balance_date > latest[0]:
        record_balance(db, keep.id, h.balance_date, h.balance_cents)
        j.add_key(BalanceSnapshot, account_id=keep.id, as_of=h.balance_date)
    j.remove(HeldFeed, HeldFeed.id == h.id)
    return len(matched), len(fresh)


def _carry(db: Session, j: Journal, drop_id: int, match_id: int) -> None:
    """What a person put on a dropped copy goes onto the transaction it copies, where that has none of its own."""
    d, m = db.get(Transaction, drop_id), db.get(Transaction, match_id)
    vals: dict = {}
    if d.category_source == CategorySource.correction and m.category_source != CategorySource.correction:
        vals.update(category=d.category, merchant=d.merchant, category_source=d.category_source,
                    is_transfer=d.is_transfer, reviewed_at=d.reviewed_at, guess_category=None, guess_pct=None)
    if d.business_answered_at is not None and m.business_answered_at is None:
        vals.update(business_pct=d.business_pct, is_business=d.is_business, business_source=d.business_source,
                    business_line=d.business_line, business_answered_at=d.business_answered_at)
    if d.reimburse_source == "manual" and m.reimburse_source == "none":
        vals.update(reimburser_id=d.reimburser_id, trip_id=d.trip_id, reimburse_source="manual")
    name = d.nickname if d.nickname and not m.nickname else None
    j.change(TransactionNote, TransactionNote.transaction_id == drop_id, transaction_id=match_id)   # a thread: all move
    if vals:
        j.change(Transaction, Transaction.id == match_id, **vals)
    if name is not None:                     # the name goes to undo_text, never the entry (P36)
        j.change_text(db.get(Transaction, match_id), "nickname", name)


def _resolve_new_account_event(db: Session, j: Journal, name: str, *, other_unknown: bool, keep_waits_too: bool,
                               now: datetime) -> None:
    """The other account's "New account … needs its type and owner" goes with it (Engineering choice 15). When the
    kept account has the same name and still waits for its type too, only the newer of two such events goes."""
    if not other_unknown:
        return
    ids = list(db.scalars(select(EventLog.id).where(
        EventLog.kind == "system", EventLog.resolved_at.is_(None),
        EventLog.message.startswith(f"New account '{name}' from ", autoescape=True)).order_by(EventLog.id.desc())))
    if keep_waits_too:
        ids = ids[:1] if len(ids) > 1 else []
    if ids:
        j.change(EventLog, EventLog.id.in_(ids), resolved_at=now)


def _holdings(j: Journal, kid: int, oid: int) -> None:
    """Holdings (investment views spec) follow the account a day at a time: for a day the kept account already has,
    its own positions stand and the other's go; the other's other days move over, with the positions imports that
    wrote them."""
    kept_days = select(Holding.as_of).where(Holding.account_id == kid)
    j.remove(Holding, and_(Holding.account_id == oid, Holding.as_of.in_(kept_days)))
    j.change(Holding, Holding.account_id == oid, account_id=kid)
    j.change(PositionsImport, PositionsImport.account_id == oid, account_id=kid)


SENDS = (("sends_holdings", "holdings_seen_at"), ("sends_transactions", "transactions_seen_at"))


def _account_fields(j: Journal, keep: Account, other: Account) -> None:
    """The investment views fields (spec, Data): the kept account takes the other's advisory fee and vehicle loan when
    it has none of its own; it sends holdings or transactions if either did, last seen at the later of the two. A
    vehicle whose loan was the other account now names the kept one if that is a loan, or none."""
    kid, oid = keep.id, other.id
    own_loan = None if keep.loan_id == oid else keep.loan_id
    theirs = {f: getattr(other, f) for f in ("advisory_fee_bp", "loan_id") + tuple(x for p in SENDS for x in p)}
    mine = {f: getattr(keep, f) for f in theirs}
    vals: dict = {}
    if keep.loan_id == oid:
        vals["loan_id"] = None
    if mine["advisory_fee_bp"] is None and theirs["advisory_fee_bp"] is not None:
        vals["advisory_fee_bp"] = theirs["advisory_fee_bp"]
    if own_loan is None and theirs["loan_id"] not in (None, kid, oid):
        vals["loan_id"] = theirs["loan_id"]
    for flag, seen in SENDS:
        if theirs[flag] is not None and mine[flag] is not True and theirs[flag] != mine[flag]:
            vals[flag] = theirs[flag]
        if theirs[seen] is not None and (mine[seen] is None or theirs[seen] > mine[seen]):
            vals[seen] = theirs[seen]
    j.change(Account, and_(Account.loan_id == oid, Account.id != kid),
             loan_id=kid if keep.type == AccountType.loan else None)
    if vals:
        j.change(Account, Account.id == kid, **vals)


def _account(db: Session, j: Journal, keep: Account, other: Account, now: datetime) -> tuple[int, int]:
    """Merging an account in the book (spec, Merging): feeds, transactions, balances, links, then the account goes."""
    kid, oid = keep.id, other.id
    other_name, other_unknown = other.name, other.type == AccountType.unknown
    keep_waits_too = keep.type == AccountType.unknown and keep.name == other.name
    match = copies_in_book(db, kid, oid)
    drop = sorted(match)
    peers: list[int] = []
    if drop:
        peers = list(db.scalars(select(Transaction.id).where(Transaction.transfer_peer_id.in_(drop))))
        unpair_peers(db, drop)
        j.remove(DuplicateKeep, or_(DuplicateKeep.a_id.in_(drop), DuplicateKeep.b_id.in_(drop)))
        j.remove(SetAsideMatch, SetAsideMatch.transaction_id.in_(drop))
        flag_ids = list(db.scalars(select(Flag.id).where(Flag.transaction_id.in_(drop))))
        if flag_ids:                      # a flag's history goes with it; what points at it lets go first
            j.remove(FlagEvent, FlagEvent.flag_id.in_(flag_ids))
            j.change(WatchKnown, WatchKnown.flag_id.in_(flag_ids), flag_id=None)
            j.change(MailOutbox, MailOutbox.flag_id.in_(flag_ids), flag_id=None)
            j.remove(Flag, Flag.id.in_(flag_ids))
        j.remove(TaxState, TaxState.key.in_([f"payment:{t}" for t in drop]))
        for t in drop:
            _carry(db, j, t, match[t])
        for t in drop:
            j.change(FeedTxnAlias, FeedTxnAlias.transaction_id == t, transaction_id=match[t])
        gone = db.execute(select(Transaction.id, Transaction.feed_id, Transaction.external_id)
                          .where(Transaction.id.in_(drop))).all()
        aliases = [FeedTxnAlias(account_id=kid, feed_id=fid, external_id=ext, transaction_id=match[tid],
                                created_at=now) for tid, fid, ext in gone if fid is not None and ext is not None]
        db.add_all(aliases)
        j.add(*aliases)
        j.remove(TransactionNote, TransactionNote.transaction_id.in_(drop))
        j.remove(Transaction, Transaction.id.in_(drop))
    moved = list(db.scalars(select(Transaction.id).where(Transaction.account_id == oid)))
    j.change(Transaction, Transaction.account_id == oid, account_id=kid)
    j.change(AccountFeed, AccountFeed.account_id == oid, account_id=kid)
    j.change(FeedTxnAlias, FeedTxnAlias.account_id == oid, account_id=kid)
    # Transfers between the two are inside one account now: undo those pairs, then pair everything that moved again.
    peer = aliased(Transaction)
    inside = list(db.scalars(select(Transaction.id).join(peer, peer.id == Transaction.transfer_peer_id)
                             .where(Transaction.account_id == kid, peer.account_id == kid)))
    if inside:
        unpair_peers(db, inside)
    pair_transfers(db, moved + peers + inside)
    latest = latest_balance(db, kid)
    for as_of, cents in db.execute(select(BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
                                   .where(BalanceSnapshot.account_id == oid).order_by(BalanceSnapshot.as_of)).all():
        if latest is None or as_of > latest[0]:
            record_balance(db, kid, as_of, cents)
            j.add_key(BalanceSnapshot, account_id=kid, as_of=as_of)
    j.remove(BalanceSnapshot, BalanceSnapshot.account_id == oid)
    _holdings(j, kid, oid)
    _account_fields(j, keep, other)
    for model in (ImportBatch, Flag, BusinessRule, SetAside, StatementStage, StatementLayout):
        j.change(model, model.account_id == oid, account_id=kid)
    j.change(HeldFeed, HeldFeed.candidate_account_id == oid, candidate_account_id=kid)
    for model in (Child, InventoryItem):
        taken = db.scalar(select(model.id).where(model.account_id == kid).limit(1)) is not None
        j.change(model, model.account_id == oid, account_id=None if taken else kid)
    j.change(Fact, and_(Fact.key == LINK_KEY, Fact.value == str(oid)), value=str(kid))
    theirs = and_(AdvisorAlias.kind == "account", AdvisorAlias.target == str(oid))
    if db.scalar(select(AdvisorAlias.id).where(AdvisorAlias.kind == "account", AdvisorAlias.target == str(kid))) is None:
        j.change(AdvisorAlias, theirs, target=str(kid))
    else:
        j.remove(AdvisorAlias, theirs)
    j.remove(SameAccountAnswer, or_(SameAccountAnswer.account_id == oid, SameAccountAnswer.other_account_id == oid))
    _resolve_new_account_event(db, j, other_name, other_unknown=other_unknown, keep_waits_too=keep_waits_too, now=now)
    j.remove(Account, Account.id == oid)
    return len(drop), len(moved)
