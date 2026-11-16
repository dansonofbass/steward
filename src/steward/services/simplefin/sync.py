import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward import gateway_name
from steward.books.sample_guard import SAMPLE_REFUSED, SampleRefused, is_sample
from steward.db.models import Account, AccountType, EventLog, Institution, SimplefinLink, Source, Transaction
from steward.events import log_event, resolve_event, resolve_events_matching
from steward.logs import outside_text
from steward.services import feeds, txn_match
from steward.services.accounts import latest_balance, record_balance
from steward.services.categorize import NO_MATCH, Suggestion, rule_suggestion
from steward.services.categorizer_client import HttpModelClient, ModelClient
from steward.services.holdings import Position, replace_holdings
from steward.services.importers.base import ParsedRow
from steward.services.ingest import ingest_rows, model_fill, rule_suggestions, teaching_examples
from steward.services.same_account import detect
from steward.services.same_account import held as held_feeds
from steward.services.simplefin.client import (
    DEFAULT_HOSTS, AccountSet, Connection, SfAccount, SfError, SimplefinError, UNREACHABLE, fetch_accounts)

Suggestions = dict[tuple[str, str], Suggestion]   # by (SimpleFIN account id, transaction id)

FIRST_PULL_DAYS = 89  # SimpleFIN allows 90; one day less keeps clock skew from tripping the limit
NORMAL_PULL_DAYS = 44  # SimpleFIN recommends at most 45 per request after that; the same one-day margin
CAPPED_MSG = "SimpleFIN limited the history it sent to the last 90 days."
LINK_PROBLEM_MSG = ("SimpleFIN reported a problem with this link. Steward will try again at the next sync; "
                    "if it keeps happening, check your SimpleFIN account.")
NEW_BANK_MSG = ("{name} is new here, so SimpleFIN sent only its last 45 days. "
                "For older history, import a file from the bank.")
GAP_MSG = ("{name} couldn't be reached from {since} until now, and SimpleFIN sends only the last 45 days, so its "
           "transactions from before {cut} may be missing. For those, import a file from the bank.")
OVERLAP_DAYS = 7
log = logging.getLogger(__name__)
SYNC_FAILED = "Steward couldn't sync this book. It will try again at the next sync."   # logged by books/jobs.py
LINK_MESSAGES = ("That SimpleFIN address isn't allowed.", UNREACHABLE)  # step-1 errors not starting with "SimpleFIN "
MODEL_DOWN_MSG = "{gateway} is off, so categorization is paused"


@dataclass
class SyncResult:
    institutions_ok: int = 0
    institutions_failed: int = 0
    accounts_new: int = 0
    transactions_new: int = 0
    accounts_held: int = 0     # same-account spec: looked like an account already here, so they wait for a question
    pairs_raised: int = 0      # same-account spec: pairs already in the book the check after the sync asks about
    errors: list[str] = field(default_factory=list)


def _event_once(db: Session, message: str) -> None:
    """Log an actionable sync event unless an identical unresolved one already exists."""
    exists = db.scalar(select(EventLog.id).where(EventLog.message == message, EventLog.resolved_at.is_(None)))
    if exists is None:
        log_event(db, "warn", "sync", message, actionable=True)


def _is_range_notice(msg: str) -> bool:
    """SimpleFIN's informational notes about the requested date range ("exceeds recommended range of 45 days",
    "exceeds limit of 90 days and was capped"); not a problem with the link."""
    m = (msg or "").lower()
    return "date range" in m or ("exceeds" in m and "days" in m)


def _is_range_capped(msg: str) -> bool:
    """The range notice that means history was actually shortened."""
    return _is_range_notice(msg) and "capped" in (msg or "").lower()


def _day(d: datetime) -> str:
    return f"{d:%b} {d.day}"


def _plain_error(name: str, code: str) -> str:
    if code.startswith("con."):
        return f"{name} needs you to sign in again at SimpleFIN"
    return f"{name}: SimpleFIN reported a problem with this connection. Steward will try again at the next sync."


def _warn_unless_dismissed(db: Session, inst: Institution, message: str) -> None:
    """Open the Home warning unless a person dismissed this same message for this connection. The dismissal is read
    from the row: a savepoint rollback may have expired the object, and the dismissal was never part of what rolled
    back."""
    if inst.dismissed_error != message:
        inst.dismissed_error = None
        _event_once(db, message)


def _fail(db: Session, inst: Institution, message: str, res: SyncResult) -> None:
    inst.last_error = message
    _warn_unless_dismissed(db, inst, message)
    res.institutions_failed += 1
    res.errors.append(message)
    db.flush()


def _connection_error(db: Session, inst: Institution, err: SfError, res: SyncResult, now: datetime) -> None:
    """SimpleFIN says this connection is broken. Its code and its words, scrubbed, go to the log; the Banks page gets a
    plain line. A sign-in problem (con.*) warns only when accounts here depend on the connection, and not again once a
    person dismissed that same warning."""
    message = _plain_error(inst.name, err.code)
    log.warning("SimpleFIN error %s for institution %s: %s", err.code, inst.id, outside_text(err.msg))
    inst.last_error = message
    if err.code.startswith("con.") and not feeds.depends_on(db, inst.id):
        # Nothing here depends on it, so a warning already open (from an older Steward, or from before its accounts
        # were removed) is closed too.
        resolve_events_matching(db, "sync", f"{inst.name} needs you to sign in again", now)
        db.flush()
        return
    _warn_unless_dismissed(db, inst, message)
    res.institutions_failed += 1
    res.errors.append(message)
    db.flush()


def dismiss_sync_warning(db: Session, event: EventLog, now: datetime) -> None:
    """A person dismissed a sync warning from Home: resolve it, and remember it on the connection it is about so the
    next sync doesn't raise it again. It comes back when that connection's error changes or clears."""
    resolve_event(db, event.id, now)
    for inst in db.scalars(select(Institution).where(Institution.last_error == event.message)):
        inst.dismissed_error = event.message
    db.flush()


def _new_rows(db: Session, acct: Account | None, a: SfAccount) -> list[ParsedRow]:
    """The fetched account's transactions not yet in the book (all of them when the account isn't either), less any
    copy dropped once already (same-account spec: a copy matched once never comes back)."""
    ids = [t.id for t in a.transactions]
    have = set() if acct is None else set(db.scalars(select(Transaction.external_id).where(
        Transaction.account_id == acct.id, Transaction.external_id.in_(ids)))) | txn_match.aliased(db, acct.id, ids)
    rows = []
    for t in a.transactions:
        if t.id not in have:
            have.add(t.id)  # a repeated id in one payload would violate the unique index
            rows.append(ParsedRow(t.posted_at, t.amount_cents, t.description, t.id))
    return rows


def _good_accounts(s: AccountSet):
    """The fetched accounts run_sync will write, in its order: those of a listed connection SimpleFIN reported no
    problem with."""
    bad = {e.conn_id for e in s.errors if e.conn_id and not _is_range_notice(e.msg)}
    for conn in s.connections:
        if conn.conn_id not in bad:
            yield from (x for x in s.accounts if x.conn_id == conn.conn_id)


def _live(s: AccountSet) -> dict[str, tuple]:
    """This sync's balance for every feed it fetched without a problem (rule 3's live feeds), by "sfin:<id>"."""
    return {f"sfin:{x.id}": (x.balance_date, x.balance_cents) for x in _good_accounts(s)}


def _held_or_will_be(db: Session, a: SfAccount, conn: Connection, live: dict[str, tuple]) -> bool:
    """Whether sync will hold this account, read without writing: a held feed still waiting, or one detection finds."""
    waiting = held_feeds.find(db, f"sfin:{a.id}")
    if waiting is not None:
        return waiting.candidate_account_id is not None
    inst_id = db.scalar(select(Institution.id).where(Institution.simplefin_org_id == conn.conn_id))
    return detect.find_candidate(db, a, conn.org_id, conn.name, inst_id, live=live) is not None


def categorize_fetched(db: Session, s: AccountSet, model: ModelClient | None, household: bool = True) -> Suggestions:
    """Rule-then-model suggestions for every fetched row not yet in the book, for run_sync to write with. The read
    ends before the model is asked (the catch-up's pattern), so no transaction, let alone the book's write lock, is
    held during the network call; `db` is a plain, non-IMMEDIATE session. A held feed's rows, and those of a feed sync
    is about to hold, are asked about nowhere (same-account spec, Privacy)."""
    read: list[tuple[str, list[ParsedRow], list[Suggestion | None]]] = []
    conns = {c.conn_id: c for c in s.connections}
    live = _live(s)
    for a in _good_accounts(s):
        known = feeds.account_of(db, f"sfin:{a.id}")
        if known is None and household and _held_or_will_be(db, a, conns[a.conn_id], live):
            continue
        rows = _new_rows(db, known, a)
        read.append((a.id, rows, rule_suggestions(db, rows, known.type if known is not None else None)))
    examples = teaching_examples(db, model)
    db.rollback()  # end the read before going to the network
    out: Suggestions = {}
    for a_id, rows, found in read:
        for r, sugg in zip(rows, model_fill(model, rows, found, examples), strict=True):
            out[(a_id, r.external_id)] = sugg
    return out


def _record_feed(db: Session, acct: Account, a: SfAccount, now: datetime) -> None:
    """What this bank sent for the account (investment views spec, What the bank sends), and the day's holdings. A sync
    without holdings leaves the last ones as they were."""
    # An account fed by several feeds sends what any of them sent at this sync: a feed already seen at `now` counts.
    acct.sends_transactions = bool(a.raw.get("transactions")) or acct.transactions_seen_at == now
    acct.sends_holdings = bool(a.holdings) or acct.holdings_seen_at == now
    if acct.sends_transactions:
        acct.transactions_seen_at = now
    if a.holdings:
        acct.holdings_seen_at = now
        replace_holdings(db, acct.id, a.balance_date, [
            Position(h.symbol, h.description or h.symbol or "", h.shares_milli, h.market_value_cents, h.cost_basis_cents)
            for h in a.holdings])


def _sync_connection(db: Session, s, conn: Connection, inst: Institution, now: datetime,
                     model: ModelClient | None, default_owner: str, household: bool = True,
                     suggestions: Suggestions | None = None, live: dict[str, tuple] | None = None,
                     touched: set[int] | None = None) -> tuple[int, int, int]:
    """Upsert one connection's accounts, new transactions and balances, finding each account by its feed. Returns (new
    accounts, new transactions, held). Accounts that are new, or whose feed's name changed, go into `touched` for the
    same-account check after the sync."""
    touched = set() if touched is None else touched
    inst.name = conn.name
    if conn.org_id:                      # SimpleFIN's id for the bank; a connection that sent none keeps the last one
        inst.org_id = conn.org_id
    new_accounts = new_txns = held = 0
    for a in (x for x in s.accounts if x.conn_id == conn.conn_id):
        ext = f"sfin:{a.id}"
        feed = feeds.find(db, ext)
        released: list[ParsedRow] | None = None
        if feed is None:
            waiting = held_feeds.find(db, ext) if household else None
            if waiting is not None and waiting.candidate_account_id is not None:
                held_feeds.refresh(waiting, a, now)          # still a question: it waits with today's balance and rows
                held += 1
                continue
            if waiting is None and household:
                found = detect.find_candidate(db, a, conn.org_id, conn.name, inst.id, live=live)
                if found is not None:
                    held_feeds.hold(db, a, inst.id, found.account.id, now)
                    held += 1
                    continue
            if waiting is not None:
                # The account it looked like went (Engineering choice 9): it comes in as a new one, with its history.
                held_feeds.refresh(waiting, a, now)
                released = held_feeds.rows(waiting)
                db.delete(waiting)
                db.flush()
            acct = Account(institution_id=inst.id, name=a.name, type=AccountType.unknown, owner=default_owner,
                           source=Source.simplefin, external_id=ext, currency=a.currency[:3], is_active=True)
            db.add(acct)
            db.flush()
            feed = feeds.add(db, acct, ext, inst.id, a.name, now)
            new_accounts += 1
            touched.add(acct.id)
            log_event(db, "info", "system", feeds.NEW_ACCOUNT_MSG.format(name=a.name, bank=inst.name),
                      actionable=True)
        else:
            acct = db.get(Account, feed.account_id)
            if detect.norm(feed.name) != detect.norm(a.name):
                touched.add(acct.id)
            feeds.seen(feed, a.name, now)
        rows = released if released is not None else _new_rows(db, acct, a)
        several = feeds.several(db, acct.id)
        if rows and several:
            rows, _ = txn_match.drop_copies(db, acct.id, feed.id, rows, now)    # decision 4
        if rows:
            found = None
            if suggestions is not None:
                found = [suggestions.get((a.id, r.external_id)) for r in rows]
                for i, r in enumerate(rows):
                    if found[i] is None:
                        # Deleted here between the read pass and now: rules only, and the catch-up asks the model.
                        found[i] = rule_suggestion(db, r.raw_description, acct.type, r.amount_cents) or NO_MATCH
                        if hasattr(model, "missed"):
                            model.missed = True
            ingest_rows(db, acct, rows, batch=None, now=now, model=model, household=household, suggestions=found,
                        feed_id=feed.id)
            new_txns += len(rows)
        latest = latest_balance(db, acct.id) if several else None
        if latest is None or a.balance_date >= latest[0]:      # several feeds: the newest balance wins
            record_balance(db, acct.id, a.balance_date, a.balance_cents)
        _record_feed(db, acct, a, now)                          # on the account the feed resolves to; never a held one
    inst.last_sync_at, inst.last_error, inst.dismissed_error = now, None, None
    return new_accounts, new_txns, held


def _check_pairs(db: Session, touched: set[int], now: datetime) -> int:
    """Same-account spec, the check after a sync: pairs in the book with an account that is new, or whose feed now
    has a different name (a feed named from a person's rename by migration 0027 gets the bank's name back), are
    checked as the one-time check does. A failure here is logged and undone; it must not lose the sync."""
    from steward.services.same_account import apart
    db.flush()
    try:
        with db.begin_nested():
            return apart.check_book(db, now, only=touched)
    except Exception:  # noqa: BLE001 - the sync itself is already written
        log.exception("The same-account check after a sync failed")
        return 0


def sync_window(db: Session, link: SimplefinLink, now: datetime) -> datetime:
    """The start-date to fetch from: FIRST_PULL_DAYS on the first pull, else back to the oldest institution's last
    good sync, at most NORMAL_PULL_DAYS."""
    if not link.last_sync_at:
        return now - timedelta(days=FIRST_PULL_DAYS)
    # The oldest-synced institution sets the window, so a bank that failed for days is caught up. One that never
    # synced has nothing to catch up to and must not widen the window for everyone else.
    inst_syncs = db.scalars(select(Institution.last_sync_at).where(
        Institution.source == Source.simplefin, Institution.last_sync_at.is_not(None))).all()
    oldest = min([link.last_sync_at] + inst_syncs)
    return max(oldest - timedelta(days=OVERLAP_DAYS), now - timedelta(days=NORMAL_PULL_DAYS))


def run_sync(db: Session, http, link: SimplefinLink, now: datetime, model: ModelClient | None,
             allowed_hosts=DEFAULT_HOSTS, accounts: AccountSet | SimplefinError | None = None, *,
             default_owner: str = "joint", household: bool = True, suggestions: Suggestions | None = None) -> SyncResult:
    """Sync one link. `accounts` is a result already fetched outside the transaction (or the error from trying);
    when None, fetch here. `suggestions` is categorize_fetched's answer for it, computed outside the transaction too;
    when None, the model is asked here, inside it."""
    res = SyncResult()
    first_pull = link.last_sync_at is None
    try:
        if isinstance(accounts, SimplefinError):
            raise accounts
        s = accounts if accounts is not None else fetch_accounts(
            http, link.access_url, start=sync_window(db, link, now), allowed_hosts=allowed_hosts)
    except SimplefinError as e:
        link.last_error = str(e)
        _event_once(db, str(e))
        res.errors.append(str(e))
        res.institutions_failed = db.scalar(
            select(func.count()).select_from(Institution).where(Institution.source == Source.simplefin)) or 0
        db.flush()
        return res

    errors_by_conn = {}
    link_problems: list[str] = []
    capped = False
    for err in s.errors:  # includes steward.parse: the client skipped a malformed account
        if _is_range_notice(err.msg):
            log.info("SimpleFIN range notice: %s", outside_text(err.msg))
            capped = capped or _is_range_capped(err.msg)
            continue
        if not err.conn_id:
            # SimpleFIN's own words go to the log, scrubbed, never to a person.
            log.warning("SimpleFIN reported a link-level problem %s: %s", err.code, outside_text(err.msg))
            link_problems.append(LINK_PROBLEM_MSG)
        elif err.conn_id not in errors_by_conn or (
                err.code.startswith("con.") and not errors_by_conn[err.conn_id].code.startswith("con.")):
            errors_by_conn[err.conn_id] = err
    if capped and db.scalar(select(EventLog.id).where(EventLog.message == CAPPED_MSG)) is None:
        log_event(db, "info", "sync", CAPPED_MSG)
    seen = {c.conn_id for c in s.connections}
    # Failed connections are often missing from `connections`; still report the ones Steward knows by name.
    conns = list(s.connections)
    for cid in errors_by_conn:
        if cid in seen:
            continue
        if db.scalar(select(Institution.id).where(Institution.simplefin_org_id == cid)) is None:
            # No name and no accounts here: an old connection SimpleFIN still lists. Nothing for a person to do.
            log.warning("SimpleFIN reports an error for an old connection it still lists, unknown here: %s (%s)",
                        cid, errors_by_conn[cid].code)
            continue
        conns.append(Connection(cid, "", ""))
    for a in s.accounts:
        if a.conn_id not in seen and a.conn_id not in errors_by_conn:
            link_problems.append(f"SimpleFIN sent an account Steward couldn't place: {a.name}")
    # Link-level messages from an earlier failed fetch, unless the same problem is still present.
    for e in db.scalars(select(EventLog).where(EventLog.kind == "sync", EventLog.resolved_at.is_(None))):
        if (e.message.startswith("SimpleFIN ") or e.message in LINK_MESSAGES or e.message == SYNC_FAILED) and e.message not in link_problems:
            e.resolved_at = now
    for msg in dict.fromkeys(link_problems):
        _event_once(db, msg)
        res.errors.append(msg)

    live, touched = _live(s), set()
    for conn in conns:
        inst = db.scalar(select(Institution).where(Institution.simplefin_org_id == conn.conn_id))
        is_new = inst is None
        if is_new:
            inst = Institution(name=conn.name, source=Source.simplefin, simplefin_org_id=conn.conn_id)
            db.add(inst)
            db.flush()
        err = errors_by_conn.get(conn.conn_id)
        if err is not None:
            _connection_error(db, inst, err, res, now)
            continue
        name, last_good = inst.name, inst.last_sync_at
        try:
            with db.begin_nested():
                new_accounts, new_txns, held = _sync_connection(db, s, conn, inst, now, model, default_owner,
                                                                household, suggestions, live, touched)
        except Exception as e:  # noqa: BLE001 - one institution must not sink the others
            log.exception("SimpleFIN sync failed for institution %s", inst.id)
            _fail(db, inst, f"{name} couldn't be synced. Steward will try again at the next sync.", res)
            continue
        res.accounts_new += new_accounts
        res.accounts_held += held
        res.transactions_new += new_txns
        res.institutions_ok += 1
        if is_new and not first_pull:
            # The window is capped after the first pull, so this bank came in with 45 days, not 90. Say so, once.
            log_event(db, "info", "sync", NEW_BANK_MSG.format(name=inst.name))
        cut = now - timedelta(days=NORMAL_PULL_DAYS)
        if not first_pull and last_good is not None and last_good < cut:
            # Back after longer than the window reaches: what it posted in between wasn't asked for. Say so, on Home.
            _event_once(db, GAP_MSG.format(name=inst.name, since=_day(last_good), cut=_day(cut)))
        for prefix in (f"{inst.name} needs you to sign in again at SimpleFIN", f"{inst.name}: ",
                       f"{inst.name} couldn't be synced"):
            resolve_events_matching(db, "sync", prefix, now)

    link.last_sync_at = now
    link.last_error = link_problems[0] if link_problems else None
    if household and touched:
        res.pairs_raised = _check_pairs(db, touched, now)
    if isinstance(model, HttpModelClient):
        if model.last_error:
            _event_once(db, gateway_name.fill(MODEL_DOWN_MSG))
        else:
            resolve_events_matching(db, "sync", gateway_name.fill(MODEL_DOWN_MSG), now)
    db.flush()
    return res


def sync_now(engine, http, model: ModelClient | None, now: datetime, allowed_hosts=DEFAULT_HOSTS, *,
             default_owner: str = "joint", after: Callable[[Session], None] | None = None,
             household: bool = True) -> SyncResult | None:
    """Sync without holding a transaction across the network fetch, or across the categorizer's answer. Returns None
    when SimpleFIN isn't linked."""
    if is_sample(engine):
        raise SampleRefused(SAMPLE_REFUSED)
    with Session(engine) as db:
        link = db.scalar(select(SimplefinLink).order_by(SimplefinLink.id))
        if link is None:
            return None
        link_id, access_url, start = link.id, link.access_url, sync_window(db, link, now)
        db.commit()  # end the read transaction before going to the network
    try:
        fetched: AccountSet | SimplefinError = fetch_accounts(http, access_url, start=start,
                                                              allowed_hosts=allowed_hosts)
    except SimplefinError as e:
        fetched = e
    suggestions = None
    if not isinstance(fetched, SimplefinError):
        with Session(engine) as db:  # a read, then the model, with nothing open
            suggestions = categorize_fetched(db, fetched, model, household)
    with Session(engine.execution_options(immediate=True)) as db:  # IMMEDIATE: wait for the lock, don't fail
        link = db.get(SimplefinLink, link_id)
        if link is None:  # unlinked while the fetch was running
            return None
        res = run_sync(db, http, link, now, model, allowed_hosts, accounts=fetched, default_owner=default_owner,
                       household=household, suggestions=suggestions)
        if household:
            # Phase 11c: new payments may belong to a set-aside (spec, Matching). A parent book has none. A failure
            # here is logged and undone; it must not lose the sync.
            from steward import clock
            from steward.inventory.accounts import run_safely
            from steward.services import setasides
            run_safely(db, lambda s: setasides.match_all(s, now.astimezone(clock.household_tz()).date()),
                       "Couldn't match payments to set-asides after this sync.")
        if after is not None:
            # Parent books: items for new accounts, then suggestions. A failure here must not lose the sync.
            from steward.inventory.accounts import run_safely
            run_safely(db, after, "Couldn't update the inventory after this sync.")
        db.commit()
    return res
