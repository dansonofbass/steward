"""Everything a merge or a "They're different" changes, kept so Undo can put it all back (same-account spec, Undo).

The journal records each row the action makes (by its key), each row it deletes (in full, as stored) and each field
it changes (as it was). Transaction fields that pairing, unpairing and categorizing change through the ORM or a bulk
UPDATE are caught the way services/undo.py's capture catches them. save() writes it all, with what each row looked
like afterwards, into one undo_entry (action merge or different); restore() puts it back. Entries hold amounts,
bank descriptions and ids, never a note or a name: the person-entered text on a deleted row (TEXT) goes to undo_text
under the entry's token, as services/undo.py's keep_text does (polish round P36), and goes with the entry, as does a
name the action writes on a row it keeps (change_text: the old text and the text written) and the name on a row it
makes (the account a "They're different" makes): a made row is kept by its key and its other fields, and Undo checks
its name in undo_text before deleting it. They stay in the book, and nothing sends them to Claude or the gateway.

A log line the action writes (the "New account" notice) is kept by its id only, never as a row it made: Undo never
deletes an event_log row (audit log). It resolves the line if it is still open, since what it asked about went."""
from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, and_, delete, event, insert, select, update
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from steward.db.models import (Account, AccountFeed, AdvisorAlias, BalanceSnapshot, BusinessRule, Child, DuplicateKeep,
                               EventLog, Fact, FeedTxnAlias, Flag, FlagEvent, HeldFeed, Holding, ImportBatch,
                               InventoryItem, MailOutbox, PositionsImport, SameAccountAnswer, SetAside, SetAsideMatch, StatementLayout, StatementStage,
                               TaxState, Transaction, TransactionNote, TZDateTime, UndoEntry, UndoText, WatchKnown)
from steward.services.undo import CHANGED_SINCE, TTL, TXN_FIELDS, Capture, UndoRefused, _by_id, _same, purge_expired

# Deleted rows go back in this order, and made rows come out in the reverse: a row comes after what it points at.
TABLES = (Account, HeldFeed, AccountFeed, StatementLayout, ImportBatch, StatementStage, Transaction, TransactionNote, BalanceSnapshot, FeedTxnAlias,
          DuplicateKeep, SetAsideMatch, Flag, FlagEvent, WatchKnown, MailOutbox, TaxState, AdvisorAlias, SameAccountAnswer, EventLog,
          PositionsImport, Holding, Child, InventoryItem, BusinessRule, SetAside, Fact)
BY_NAME = {m.__tablename__: m for m in TABLES}
ORDER = {m.__tablename__: i for i, m in enumerate(TABLES)}
ACTIONS = frozenset({"merge", "different"})
# Columns a sync refreshes without changing anything that matters (feeds.seen, and what the bank sent at the last sync
# and when); Undo doesn't check them on a row the action made or changed, and still puts back what it changed.
VOLATILE = {"account_feed": ("name", "last_seen_at"),
            "account": ("sends_holdings", "sends_transactions", "holdings_seen_at", "transactions_seen_at")}
# What a person typed or named on a row, by table, kept out of undo_entry: a deleted row's values go to undo_text (row
# key = the journal's key) and come back from there, a made row's go there as the text Undo checks before deleting it,
# and change() refuses them. An account's name is one whoever gave it, a feed's and a held feed's too (the bank's name
# for the account). Bank text stays in the entry: a row's raw_description and merchant (as services/undo.py keeps
# them), a held feed's rows, a holding's name, a flag's summary, title and facts (the checks write those), and every id.
TEXT: dict[str, tuple[str, ...]] = {
    "transaction": ("nickname",), "transaction_note": ("author_name", "body"), "account": ("name",),
    "account_feed": ("name",), "held_feed": ("name",), "flag": ("note",),
    "watch_known": ("note",), "fact": ("note",), "child": ("label",), "set_aside": ("name", "notes"),
    "business_rule": ("label",), "statement_layout": ("label",),
    "inventory_item": ("name", "full_number", "login_kept_in", "notes", "check_reason", "closed_reason", "details")}


def enc(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def dec(col, v):
    """A stored JSON value back to what the column takes."""
    if v is None:
        return None
    t = col.type
    if isinstance(t, (TZDateTime, DateTime)):
        return datetime.fromisoformat(v)
    if isinstance(t, Date):
        return date.fromisoformat(v)
    if isinstance(t, SqlEnum) and t.enum_class is not None:
        return t.enum_class(v)
    return v


def _pk(model) -> list:
    return list(model.__table__.primary_key.columns)


def where_key(model, key: str):
    return and_(*(c == dec(c, v) for c, v in zip(_pk(model), json.loads(key), strict=True)))


def row(db: Session, model, key: str) -> dict | None:
    """The stored row with this key, JSON-ready, or None."""
    r = db.execute(select(model.__table__).where(where_key(model, key))).mappings().first()
    return None if r is None else {c: enc(v) for c, v in r.items()}


def _key(model, values) -> str:
    return json.dumps([enc(values[c.name]) for c in _pk(model)])


@dataclass
class Journal:
    db: Session
    cap: Capture
    made: list[tuple[str, str]] = field(default_factory=list)      # (table, key), in the order made
    gone: dict[str, dict[str, dict]] = field(default_factory=dict)  # table → key → the row as stored
    was: dict[str, dict[str, dict]] = field(default_factory=dict)   # table → key → {column: before}
    texts: dict[tuple[str, str, str], str] = field(default_factory=dict)  # (table, key, column) → a deleted row's text
    logged: list[int] = field(default_factory=list)                 # event_log ids the action wrote
    edits: dict[tuple[str, str, str], list] = field(default_factory=dict)  # (table, key, column) → [old, written]

    def add(self, *objs) -> None:
        """Rows the action made (flushed here, so they have keys)."""
        self.db.flush()
        for o in objs:
            values = o.__mapper__.primary_key_from_instance(o)
            self.made.append((o.__tablename__, json.dumps([enc(v) for v in values])))

    def log(self, *events: EventLog) -> None:
        """Log lines the action wrote: Undo keeps them (it never deletes an event_log row) and resolves any still open."""
        self.db.flush()
        self.logged += [e.id for e in events]

    def add_key(self, model, **pk) -> None:
        """A row the action made through a helper that returns nothing (record_balance)."""
        self.made.append((model.__tablename__, _key(model, pk)))

    def remove(self, model, where) -> int:
        """Delete the matching rows, keeping each as stored. A row this action made is just gone again."""
        self.db.flush()
        rows = self.db.execute(select(model.__table__).where(where)).mappings().all()
        name = model.__tablename__
        for r in rows:
            k = _key(model, r)
            if (name, k) in self.made:
                self.made.remove((name, k))
            elif k not in self.gone.get(name, {}):
                text = TEXT.get(name, ())
                self.gone.setdefault(name, {})[k] = {c: enc(v) for c, v in r.items() if c not in text}
                self.texts.update({(name, k, c): r[c] for c in text if r[c] is not None})
        if rows:
            self.db.execute(delete(model.__table__).where(where))
            self.db.expire_all()
        return len(rows)

    def change(self, model, where, **values) -> int:
        """Set these columns on the matching rows, keeping what each was the first time it changed."""
        self.db.flush()
        table = model.__table__
        name = model.__tablename__
        if text := sorted(set(values) & set(TEXT.get(name, ()))):
            raise ValueError(f"The journal keeps no note or name: {name}.{', '.join(text)}")
        rows = self.db.execute(select(table).where(where)).mappings().all()
        for r in rows:
            before = self.was.setdefault(name, {}).setdefault(_key(model, r), {})
            for f in values:
                before.setdefault(f, enc(r[f]))
        if rows:
            self.db.execute(update(table).where(where).values(**values))
            self.db.expire_all()
        return len(rows)

    def change_text(self, obj, column: str, value: str) -> None:
        """Write a note or name on a row the action keeps (a dropped copy's nickname carried onto its match). The old
        text and the text written go to undo_text, as services/undo.py's keep_text does, never into the entry: Undo puts
        the old text back, and refuses once the field no longer holds what was written. Never for a row it made."""
        self.db.flush()
        model, name = type(obj), obj.__tablename__
        k = json.dumps([enc(v) for v in obj.__mapper__.primary_key_from_instance(obj)])
        col = model.__table__.c[column]
        old = self.db.execute(select(col).where(where_key(model, k))).scalar_one()
        was = self.edits.get((name, k, column))
        self.edits[(name, k, column)] = [was[0] if was else old, value]
        self.db.execute(update(model.__table__).where(where_key(model, k)).values({column: value}))
        self.db.expire_all()

    def save(self, user_id: int, action: str, now: datetime) -> str:
        """One undo entry for all of it, with what every touched row looks like now, for restore's checks."""
        db = self.db
        db.flush()
        made = set(self.made)
        made_after: dict[str, dict[str, dict]] = {}
        made_texts: dict[tuple[str, str, str], str | None] = {}   # a made row's name, as Undo checks it, for undo_text
        for name, k in self.made:
            now_row = row(db, BY_NAME[name], k)
            if now_row is not None:
                fields = (TXN_FIELDS if name == "transaction"
                          else tuple(f for f in now_row if f not in VOLATILE.get(name, ())))
                text = TEXT.get(name, ())
                made_after.setdefault(name, {})[k] = {f: now_row[f] for f in fields if f not in text}
                made_texts.update({(name, k, f): now_row[f] for f in fields if f in text})
        was_before: dict[str, dict[str, dict]] = {}
        was_after: dict[str, dict[str, dict]] = {}
        for name, rows in self.was.items():
            for k, before in rows.items():
                if (name, k) in made:
                    continue                                   # undo removes the row; its fields don't matter
                if k in self.gone.get(name, {}):
                    was_before.setdefault(name, {})[k] = before   # changed, then deleted: put back after re-inserting
                    continue
                now_row = row(db, BY_NAME[name], k)
                if now_row is None:
                    continue                                   # not there any more: nothing to check or put back
                after = {f: now_row[f] for f in before}
                if after != before:
                    was_before.setdefault(name, {})[k] = before
                    was_after.setdefault(name, {})[k] = {f: v for f, v in after.items()
                                                         if f not in VOLATILE.get(name, ())}
        skip = ({json.loads(k)[0] for t, k in self.made if t == "transaction"}
                | {json.loads(k)[0] for k in self.gone.get("transaction", {})})
        ids = [i for i in self.cap.txns if i not in skip]
        after_t = _by_id(db.connection(), Transaction, TXN_FIELDS, ids)
        txns = {i: self.cap.txns[i] for i in ids if after_t.get(i) != self.cap.txns[i]}
        before = {"made": self.made, "gone": self.gone, "was": was_before,
                  "txns": {str(i): v for i, v in txns.items()}, "logged": self.logged,
                  "texts": [list(x) for x in self.edits],           # where the text changed; the text is in undo_text
                  "made_texts": [list(x) for x in made_texts]}      # where a made row's text is checked; ditto
        after = {"made": made_after, "was": was_after, "txns": {str(i): after_t.get(i) for i in txns}}
        purge_expired(db, now)
        token = secrets.token_urlsafe(32)
        db.add(UndoEntry(token=token, user_id=user_id, action=action, created_at=now, expires_at=now + TTL,
                         before=json.dumps(before), after=json.dumps(after)))
        db.add_all(UndoText(token=token, model=name, row_key=k, field=f, value=v, written=None)
                   for (name, k, f), v in self.texts.items())
        db.add_all(UndoText(token=token, model=name, row_key=k, field=f, value=old, written=written)
                   for (name, k, f), (old, written) in self.edits.items())
        db.add_all(UndoText(token=token, model=name, row_key=k, field=f, value=None, written=written)
                   for (name, k, f), written in made_texts.items())
        db.flush()
        return token


@contextmanager
def recording(db: Session) -> Iterator[Journal]:
    """Listen as undo.capturing does, so pairing and unpairing are caught too; the caller saves."""
    j = Journal(db, Capture(db))
    before_flush, on_execute = j.cap.before_flush, j.cap.on_execute
    event.listen(db, "before_flush", before_flush)
    event.listen(db, "do_orm_execute", on_execute)
    try:
        yield j
        db.flush()
    finally:
        event.remove(db, "before_flush", before_flush)
        event.remove(db, "do_orm_execute", on_execute)


def _refuse() -> UndoRefused:
    return UndoRefused(409, CHANGED_SINCE)


def _check(db: Session, before: dict, after: dict, made_txns: list[int], made_feeds: list[int],
           made_aliases: list[int]) -> None:
    """Everything the action left is still as it left it (Engineering choice 16), or nothing is put back."""
    for part in ("was", "made"):
        for name, rows in after[part].items():
            for k, vals in rows.items():
                now_row = row(db, BY_NAME[name], k)
                if now_row is None or any(now_row.get(f) != v for f, v in vals.items()):
                    raise _refuse()
    for name, rows in before["gone"].items():
        if any(row(db, BY_NAME[name], k) is not None for k in rows):
            raise _refuse()                                          # a deleted row's key was taken again
    now_t = _by_id(db.connection(), Transaction, TXN_FIELDS, [int(k) for k in after["txns"]])
    if not all(_same(now_t.get(int(k)), v) for k, v in after["txns"].items()):
        raise _refuse()
    if made_txns:
        for col in (TransactionNote.transaction_id, SetAsideMatch.transaction_id, DuplicateKeep.a_id,
                    DuplicateKeep.b_id, FeedTxnAlias.transaction_id):
            if db.scalar(select(col).where(col.in_(made_txns)).limit(1)) is not None:
                raise _refuse()                                      # something new points at a row it brought in
        known = set(made_txns) | {int(k) for k in after["txns"]}
        if db.scalar(select(Transaction.id).where(Transaction.transfer_peer_id.in_(made_txns),
                                                  Transaction.id.not_in(known)).limit(1)) is not None:
            raise _refuse()                                          # a row was paired with a merged-in row since
    if made_feeds:
        if db.scalar(select(Transaction.id).where(Transaction.feed_id.in_(made_feeds),
                                                  Transaction.id.not_in(made_txns)).limit(1)) is not None:
            raise _refuse()                                          # a sync used the feed it added
        if db.scalar(select(FeedTxnAlias.id).where(FeedTxnAlias.feed_id.in_(made_feeds),
                                                   FeedTxnAlias.id.not_in(made_aliases)).limit(1)) is not None:
            raise _refuse()
    moved = [json.loads(k)[0] for k in before["was"].get("account_feed", {})]
    if moved:                                                        # feeds the merge handed to the kept account
        known_t = (set(made_txns) | {json.loads(k)[0] for k in before["was"].get("transaction", {})}
                   | {int(k) for k in before["txns"]})
        if db.scalar(select(Transaction.id).where(Transaction.feed_id.in_(moved),
                                                  Transaction.id.not_in(known_t)).limit(1)) is not None:
            raise _refuse()                                          # a sync used a feed the merge moved
        known_a = set(made_aliases) | {json.loads(k)[0] for k in before["was"].get("feed_txn_alias", {})}
        if db.scalar(select(FeedTxnAlias.id).where(FeedTxnAlias.feed_id.in_(moved),
                                                   FeedTxnAlias.id.not_in(known_a)).limit(1)) is not None:
            raise _refuse()


def restore(db: Session, token: str, before: dict, after: dict, now: datetime) -> int:
    """Put back everything one entry recorded, all or nothing: made rows out, deleted rows in (transfer links last) with
    their text from undo_text, changed fields back, and the log lines it wrote resolved, never deleted. Returns how many
    transactions it put back or took out. The caller deletes the entry's undo_text once it is used."""
    # An entry written while the journal counted a log line as a row it made names it in made: it is kept all the same.
    log = EventLog.__tablename__
    logged = list(before.get("logged", [])) + [json.loads(k)[0] for t, k in before["made"] if t == log]
    made = [(t, k) for t, k in before["made"] if t != log]
    after = {**after, "made": {t: rows for t, rows in after["made"].items() if t != log}}
    gone: dict[str, dict[str, dict]] = before["gone"]
    ids_of = lambda table: [json.loads(k)[0] for t, k in made if t == table]  # noqa: E731
    made_txns, made_feeds, made_aliases = ids_of("transaction"), ids_of("account_feed"), ids_of("feed_txn_alias")
    _check(db, before, after, made_txns, made_feeds, made_aliases)
    edited = {tuple(x) for x in before.get("texts", [])}
    checked = {tuple(x) for x in before.get("made_texts", [])}   # an entry from before then has them in after["made"]
    texts: dict[tuple[str, str], dict[str, str | None]] = {}
    edits: list[UndoText] = []
    unchanged: list[UndoText] = []
    for x in db.scalars(select(UndoText).where(UndoText.token == token)):
        if (x.model, x.row_key, x.field) in edited:
            edits.append(x)
        elif (x.model, x.row_key, x.field) in checked:
            unchanged.append(x)
        else:
            texts.setdefault((x.model, x.row_key), {})[x.field] = x.value
    for x in edits + unchanged:                       # a name it wrote, or on a row it made, is still what it wrote
        model = BY_NAME[x.model]
        if db.execute(select(model.__table__.c[x.field]).where(where_key(model, x.row_key))).scalar() != x.written:
            raise _refuse()
    t = Transaction.__table__
    try:
        with db.begin_nested():
            if made_txns:
                db.execute(update(t).where(t.c.transfer_peer_id.in_(made_txns)).values(transfer_peer_id=None))
            for name, k in sorted(made, key=lambda x: ORDER[x[0]], reverse=True):
                db.execute(delete(BY_NAME[name].__table__).where(where_key(BY_NAME[name], k)))
            links: dict[int, int] = {}
            for name in sorted(gone, key=ORDER.__getitem__):
                table = BY_NAME[name].__table__
                for k, full in gone[name].items():
                    vals = {c.name: dec(c, full[c.name]) for c in table.columns if c.name in full}
                    kept = texts.get((name, k), {})       # an entry made before undo_text held them has them in full
                    vals |= {f: kept.get(f) for f in TEXT.get(name, ()) if f not in full}
                    if name == "transaction" and vals.get("transfer_peer_id") is not None:
                        links[vals["id"]] = vals.pop("transfer_peer_id")
                    db.execute(insert(table).values(**vals))
            for tid, peer in links.items():
                db.execute(update(t).where(t.c.id == tid).values(transfer_peer_id=peer))
            for name in sorted(before["was"], key=ORDER.__getitem__):
                model = BY_NAME[name]
                table = model.__table__
                for k, vals in before["was"][name].items():
                    db.execute(update(table).where(where_key(model, k))
                               .values(**{f: dec(table.c[f], v) for f, v in vals.items()}))
            for k, vals in before["txns"].items():
                db.execute(update(t).where(t.c.id == int(k)).values(**{f: dec(t.c[f], v) for f, v in vals.items()}))
            for x in edits:
                model = BY_NAME[x.model]
                db.execute(update(model.__table__).where(where_key(model, x.row_key)).values({x.field: x.value}))
            if logged:
                e = EventLog.__table__
                db.execute(update(e).where(e.c.id.in_(logged), e.c.resolved_at.is_(None)).values(resolved_at=now))
    except IntegrityError:
        raise _refuse() from None
    db.expire_all()
    return len(gone.get("transaction", {})) + len(made_txns)
