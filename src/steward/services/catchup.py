"""The catch-up (spec 6.1, ruling 11; phase 12, Catch-up): when the categorizer answers after a miss, or while a book
has rows pending, untouched rows (source none, uncategorized, not reviewed, not snoozed, not a transfer, not a
Zelle-style payment) that the model has not been asked about are asked in batches of 50, per book, across all history
newest first, at most 1,000 per book per run. Every asked row gets model_asked_at (ruling 14), so a row the model
couldn't place is not asked again at every restart; an answer is written only if the row is still untouched then. A
row a built-in rule now answers (a card payment worded the way phase 12 learned, a Zelle payment) takes that answer
instead, as at ingest; a row only a household rule matches is asked like any other (ruling F5 revised). A snooze that
has run out counts as none. A book busy syncing is skipped and tried again at the next tick.

A tick asks at most TICK_BATCHES batches across all books, so the advisor's 60-second health check keeps its
cadence; the rest waits for the next tick.

Progress (decision 7): a wave starts when untouched-and-unasked rows appear with none before; watch_state "catchup_wave"
keeps its start. pending is untouched and unasked; done is rows asked since the wave began; nothing shows when
pending is 0."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine, and_, func, or_, select, update
from sqlalchemy.orm import Session

from steward import gateway_name
from steward.books.registry import BookUnavailable
from steward.db.models import Account, AccountType, CategorySource, Transaction, WatchState
from steward.events import log_event
from steward.services.categorize import (INVESTMENT_TYPES, P2P_MERCHANTS, Suggestion, builtin_rule, household_rule,
                                         investment_suggestion)
from steward.services.categorizer_client import BATCH, Guess, NullModelClient, business_of, features_from
from steward.services.transfers import pair_transfers

PER_RUN = 1000
CAUGHT_UP = "Categorized {n} that came in while {gateway} was off."
TICK_BATCHES = 3                # per advisor tick, over all books
WAVE = "catchup_wave"           # watch_state key: when the current wave began (ISO datetime)


@dataclass
class CatchUp:
    asked: int = 0
    categorized: int = 0
    guessed: int = 0            # answered with a guess, left for Review
    ruled: int = 0              # a built-in rule answered for it (ruling F5 revised), no model asked
    stopped: bool = False       # the categorizer couldn't be asked; the client's miss stays set
    more: bool = False          # the per-run limit was reached with rows still to ask


def _untouched(now: datetime):
    """A snooze that has run out counts as none: Review shows the row again then, so it is asked and pending too."""
    return (Transaction.category_source == CategorySource.none, Transaction.category == "uncategorized",
            Transaction.reviewed_at.is_(None),
            or_(Transaction.snoozed_until.is_(None), Transaction.snoozed_until <= now), Transaction.is_transfer.is_(False))


def unasked_clauses(now: datetime):
    """Untouched, never answered about, and not a payment app's row (those stay for Review by design)."""
    return (*_untouched(now), Transaction.model_asked_at.is_(None),
            or_(Transaction.merchant.is_(None), Transaction.merchant.not_in(P2P_MERCHANTS)))


def pending_count(db: Session, now: datetime) -> int:
    return db.scalar(select(func.count()).select_from(Transaction).where(*unasked_clauses(now))) or 0


def begin_wave(db: Session, now: datetime) -> None:
    """Rows are about to appear (ingest) or be asked (the catch-up): with none pending, this is a new wave; with
    rows already pending and no wave ever stamped, the wave starts now."""
    row = db.get(WatchState, WAVE)
    if row is not None and pending_count(db, now) > 0:
        return
    if row is None:
        db.add(WatchState(key=WAVE, value=now.isoformat()))
    else:
        row.value, row.updated_at = now.isoformat(), now
    db.flush()


def progress(db: Session, now: datetime) -> dict:
    """{pending, done} for Review's and Home's line; done is 0 once nothing is pending."""
    pending = pending_count(db, now)
    if pending == 0:
        return {"pending": 0, "done": 0}
    row = db.get(WatchState, WAVE)
    if row is None:
        return {"pending": pending, "done": 0}
    start = datetime.fromisoformat(row.value)
    done = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.model_asked_at >= start)) or 0
    return {"pending": pending, "done": done}


def rule_answer(db: Session, t: Transaction, account_type: AccountType) -> Suggestion | None:
    """What a rule says about an old untouched row, or None to ask the model (ruling F5 revised). A built-in answers
    as at ingest: a card payment's checking side, worded the way phase 12 learned, becomes a transfer; a Zelle-style
    payment gets its app as the merchant. A household rule is not applied: the row goes to the model, which has the
    household's rules as examples, and spreading a person's rule onto old rows stays theirs to offer (decision 1).
    In an investment account a row never goes to the model: it takes investment_suggestion's answer, as
    sort_investment_rows gives it."""
    if account_type in INVESTMENT_TYPES:
        return investment_suggestion(db, t.raw_description)
    if household_rule(db, t.raw_description, t.amount_cents) is not None:
        return None
    return builtin_rule(t.raw_description, t.amount_cents)


def _apply_rules(engine: Engine, ruled: list[tuple[int, Suggestion]], now: datetime) -> int:
    """Write each rule's answer the way ingest does, only on rows still untouched and unasked, then pair the
    transfers. Returns rows changed."""
    applied, transfers = 0, []
    with Session(engine.execution_options(immediate=True)) as wdb:
        for tid, s in ruled:
            is_transfer = s.category == "transfer"
            values: dict = {"category": s.category, "is_transfer": is_transfer, "model_asked_at": now,
                            "category_source": CategorySource.rule if is_transfer else s.source,
                            "guess_category": None, "guess_pct": None}
            if s.merchant:
                values["merchant"] = s.merchant
            done = wdb.execute(update(Transaction).where(Transaction.id == tid, *unasked_clauses(now)).values(**values))
            if done.rowcount:
                applied += 1
                if is_transfer:
                    transfers.append(tid)
        pair_transfers(wdb, transfers)
        wdb.commit()
    return applied


def catch_up_book(engine: Engine, model, *, now: datetime, per_run: int = PER_RUN) -> CatchUp:
    out = CatchUp()
    key: tuple[date, int] | None = None     # the run's own place: (posted_at, id) of the last row read, newest first
    examples: list[tuple[str, str]] | None = None
    with Session(engine.execution_options(immediate=True)) as wdb:
        begin_wave(wdb, now)
        wdb.commit()
    while True:
        if out.asked >= per_run:
            out.more = True
            break
        want = min(BATCH, per_run - out.asked)
        items: list[tuple[int, str, int]] = []
        ruled: list[tuple[int, Suggestion]] = []
        with Session(engine.execution_options(immediate=False)) as rdb:
            if examples is None:
                from steward.services.ingest import teaching_examples      # ingest imports this module (begin_wave)
                examples = teaching_examples(rdb, model)
            q = (select(Transaction, Account.type).join(Account, Account.id == Transaction.account_id)
                 .where(*unasked_clauses(now)))
            if key is not None:
                q = q.where(or_(Transaction.posted_at < key[0],
                                and_(Transaction.posted_at == key[0], Transaction.id < key[1])))
            rows = rdb.execute(q.order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(want * 4)).all()
            for t, account_type in rows:
                key = (t.posted_at, t.id)
                answer = rule_answer(rdb, t, account_type)
                if answer is None:
                    items.append((t.id, t.raw_description, t.amount_cents))
                    if len(items) == want:
                        break
                else:
                    ruled.append((t.id, answer))
            rdb.rollback()
        if not rows:
            break
        if ruled:                                         # written before the model call, outside any read
            out.ruled += _apply_rules(engine, ruled, now)
        if not items:
            continue
        hits = model.categorize_batch([(d, a) for _, d, a in items], examples)
        if hits is None:
            out.stopped = True
            break
        out.asked += len(items)
        with Session(engine.execution_options(immediate=True)) as wdb:
            for (tid, _, amount), hit in zip(items, hits):
                values: dict = {"model_asked_at": now}
                if hit:
                    values.update(category=hit[0], category_source=CategorySource.model, guess_category=None, guess_pct=None)
                    if hit[1]:
                        values["merchant"] = hit[1]
                    if amount < 0 and business_of(hit) is not None:
                        values["business_hint"] = business_of(hit)
                elif isinstance(hit, Guess):
                    values.update(guess_category=hit.category, guess_pct=hit.pct)
                done = wdb.execute(update(Transaction).where(Transaction.id == tid, *_untouched(now),
                                                             Transaction.model_asked_at.is_(None)).values(**values))
                if done.rowcount and hit:
                    out.categorized += 1
                elif done.rowcount and isinstance(hit, Guess) and hit.category:
                    out.guessed += 1
            wdb.commit()
    return out


def _words(n: int) -> str:
    return "1 transaction" if n == 1 else f"{n:,} transactions"


def catch_up(books, model, now: datetime) -> int:
    total = 0
    budget = TICK_BATCHES * BATCH
    for book in books.books():
        if book.id in books.unavailable:
            continue
        if budget <= 0:
            model.missed = True                 # this tick's share is spent: the rest waits for the next tick
            break
        lock = books.sync_lock(book.id)
        if not lock.acquire(blocking=False):
            model.missed = True                 # syncing now: try this book again at the next tick
            continue
        lock.release()                          # only a probe: holding it across gateway calls would make Sync busy;
        try:                                    # the guarded per-row update makes an overlap with a sync safe
            engine = books.engine_for(book)
        except BookUnavailable:
            continue
        result = catch_up_book(engine, model, now=now, per_run=budget)
        budget -= result.asked
        if result.more or result.stopped:
            model.missed = True
        if result.categorized:
            with Session(engine) as db:
                log_event(db, "info", "categorizer",
                          gateway_name.fill(CAUGHT_UP).replace("{n}", _words(result.categorized)))
                db.commit()
        total += result.categorized
        if result.stopped:
            break
    return total


def _any_pending(books, now: datetime) -> bool:
    """One count per open book: rows can turn pending without a miss (an undone import or a removed row unpairs a
    transfer, a snooze runs out, a person moves a row off Transfer)."""
    for book in books.books():
        if book.id in books.unavailable:
            continue
        try:
            engine = books.engine_for(book)
        except BookUnavailable:
            continue
        with Session(engine) as db:
            if pending_count(db, now) > 0:
                return True
    return False


def maybe_catch_up(health: dict | None, model, books, now: datetime) -> int | None:
    """Runs on the advisor tick. The gateway's features are noted on every tick (ruling 15); the catch-up itself
    runs only when the gateway says the categorizer is ready and the client missed rows or a book has rows pending."""
    if hasattr(model, "features"):
        model.features = features_from(health)
    if not health or not health.get("categorizer") or not hasattr(model, "categorize_batch") \
            or isinstance(model, NullModelClient):
        return None
    if not getattr(model, "missed", False) and not _any_pending(books, now):
        return None
    model.missed = False
    return catch_up(books, model, now)
