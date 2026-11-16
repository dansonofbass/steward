"""Undo for a sort, a Snooze or an Ignore (sorting redesign spec, Undo), and for marking a trip, Settle and Not
reimbursed (reimbursable spec), a bulk sort (profile spec, Sorting several rows at once), and a merge or a "They're different" (same-account spec;
services/same_account/journal.py). An action runs inside capturing(). The first time the session is about to change a
transaction, a merchant rule, a reimburse rule or a settlement, the row's stored values are read and kept as "before":
ORM changes through before_flush, bulk UPDATEs (unpair_peers) through do_orm_execute. So every row the action touched is
caught, including the transfer peers that pairing chose while it ran. On the way out the "after" values are read back,
and both go into undo_entry in the same transaction. undo() puts every "before" value back, all or nothing: if any row
no longer matches its "after", nothing changes (409). The compare and the restore cover the fields an entry recorded,
so an entry made before a column was added still undoes. Entries hold categories, flags, times, payer and trip ids and
a rule's pattern and merchant, never a note or a name, and nothing here is sent to Claude or the gateway.

Also every Profile write (profile spec P26): a fact or a balance made is deleted, and an account's type, active flag, rate or loan, a kid's school, share, living costs, 529, monthly amount and removal, and a person's Later window are put back. Rows are kept by primary key ("12", or "12|2026-10-01" for a balance). A kid is captured without its name and an account without its name, so renaming either isn't undoable (P32).

And the polish round's spending writes: a category's kind, target and check_after (keyed by category), and set-asides made in one go with their matches (made rows are deleted, never named).

Names and notes (polish round P36): a made note is deleted by id, and the old text of a name, a rule's note and its author goes to undo_text with the text the action wrote; undo_entry never holds either. A rule the action deleted is made again. A merge's journal keeps the notes and names of the rows it deletes in undo_text too, and so does removing a note (remember_removed_note): Undo makes it again, in its place.

And Home's Dismiss (Home spec P20): an event's resolved_at, never its message. An event is kept for that change only:
Undo never deletes an event_log row, including the log lines a captured action writes.

And a remembered import layout's Edit and Forget (import/export spec P14): its choices and its forgotten_at, never its
header. Its label, and a statement layout's, is a bank's or an account's name, so a changed label goes to undo_text.
An entry written while undo_entry still kept the label compares and restores it as recorded."""
from __future__ import annotations

import json
import secrets
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from sqlalchemy import Date, String, delete, event, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from steward.db.models import (UNDO_MINUTES, Account, AccountType, BalanceSnapshot, CategorySource, Child, EventLog, Fact,
                               ImportLayout, MerchantRule, ReimburseRule, ReimburseSettlement, SetAside, SetAsideMatch,
                               SpendingTarget, StatementLayout, SsEarnings, Transaction, TransactionNote, UndoEntry, UndoText, UserSetup)

TTL = timedelta(minutes=UNDO_MINUTES)
# The spec's nine, model_asked_at (unpair_peers clears it), the business fields the card's switch sends with a sort,
# and the reimbursable spec's three.
TXN_FIELDS = ("category", "category_source", "merchant", "guess_category", "guess_pct", "reviewed_at", "snoozed_until",
              "is_transfer", "transfer_peer_id", "model_asked_at", "is_business", "business_pct", "business_source",
              "business_line", "reimburser_id", "trip_id", "reimburse_source")
RULE_FIELDS = ("pattern", "merchant", "category", "is_business", "source", "amount_cents", "created_at")
CHILD_FIELDS = ("birth_year", "cost_level", "account_id", "monthly_contribution_cents", "share_pct", "covers_living",
                "removed_at")
# Besides transactions, what an action can make or change, by the key its JSON is kept under ("rules" since 0024). The
# Profile five (0030) never hold a name or a note (Engineering choice 9).
OTHERS: dict[str, tuple[type, tuple[str, ...]]] = {
    "rules": (MerchantRule, RULE_FIELDS),
    "reimburse_rules": (ReimburseRule, ("pattern", "reimburser_id")),
    "settlements": (ReimburseSettlement, ("reimburser_id", "amount_cents", "category", "settled_at")),
    "facts": (Fact, ("key", "value", "as_of")),
    "snapshots": (BalanceSnapshot, ("balance_cents",)),
    "children": (Child, CHILD_FIELDS),
    "accounts": (Account, ("type", "is_active", "rate_bp", "loan_id")),
    "marks": (UserSetup, ("later_until",)),
    "earnings": (SsEarnings, ("earnings_cents", "imported_at")),   # a record import: years, amounts and when, never the file
    "notes": (TransactionNote, ()),   # made notes are deleted by id; no field, so no body, is kept (P36)
    # Polish round: a category's kind, target and kept-until (keyed by category), and set-asides made in one go with
    # the matches made for them. A made match is deleted before the set-aside it points at (OTHERS' order). The
    # set-aside's name is never kept: a made row is deleted by id.
    "targets": (SpendingTarget, ("kind", "monthly_cents", "check_after")),
    "sa_matches": (SetAsideMatch, ("how",)),
    "set_asides": (SetAside, ("archived_at",)),
    # Home spec P20: Dismiss on For you resolves an event; Undo reopens it. Only the time is kept, never the message.
    "events": (EventLog, ("resolved_at",)),
    # Import/export spec P14: a remembered layout's Edit and Forget (plan Engineering choice 1: Forget sets
    # forgotten_at, Undo clears it). The header is never kept; the label (a bank's or an account's name) goes to
    # undo_text (LABELS).
    "layouts": (ImportLayout, ("mapping", "negate", "date_format", "account_id", "forgotten_at")),
    # PDF statements spec P23 (plan Engineering choice 8): Forget sets forgotten_at, Undo clears it. Never the anchors
    # or the rules, which Forget doesn't change; the label, a bank's name, goes to undo_text.
    "statement_layouts": (StatementLayout, ("account_id", "forgotten_at")),
}
# Kept for the fields an action changed, never as rows it made: Undo puts resolved_at back and never deletes an
# event_log row, so the log lines a captured action writes (set-asides, the target check) stay (audit log).
CHANGE_ONLY = frozenset({"events", "layouts", "statement_layouts"})
MADE = tuple(model for key, (model, _) in OTHERS.items() if key not in CHANGE_ONLY)
TIMES = frozenset({"reviewed_at", "snoozed_until", "model_asked_at", "settled_at", "removed_at", "later_until", "imported_at", "archived_at", "created_at", "resolved_at", "forgotten_at"})
DATES = frozenset({"as_of", "check_after"})
SOURCES = frozenset({"category_source", "source"})
ENUMS = {"type": AccountType}

# P36: text fields an action changes are kept in undo_text, never in undo_entry. Keys are the row's id.
TEXT_MODELS: dict[str, type] = {"txn": Transaction, "rule": MerchantRule, "layout": ImportLayout,
                                 "statement_layout": StatementLayout}
TEXT_INTS = frozenset({"note_by"})
# A layout's label is caught whatever writes it: read when the row is first about to change, kept if it differs at
# the end. By OTHERS key: (undo_text's model, the text field).
LABELS: dict[str, tuple[str, str]] = {"layouts": ("layout", "label"), "statement_layouts": ("statement_layout", "label")}


def _as_text(v) -> str | None:
    return None if v is None else str(v)


def _from_text(field_name: str, v: str | None):
    return int(v) if v is not None and field_name in TEXT_INTS else v

CHANGED_SINCE = "That changed since, so it can't be undone."
GONE = "Undo is no longer available for that."
NO_UNDO = "There's nothing to undo with that."


class UndoRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _enc(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _dec(name: str, v):
    if v is None:
        return None
    if name in TIMES:
        return datetime.fromisoformat(v)
    if name in DATES:
        return date.fromisoformat(v)
    if name in SOURCES:
        return CategorySource(v)
    if name in ENUMS:
        return ENUMS[name](v)
    return v


def _rows(conn, model, fields: tuple[str, ...], where) -> dict[int, dict]:
    """The stored values, as JSON-ready dicts by id, read with a core SELECT (never the session's copies)."""
    t = model.__table__
    q = select(t.c.id, *(t.c[f] for f in fields))
    if where is not None:
        q = q.where(where)
    return {r["id"]: {f: _enc(r[f]) for f in fields} for r in conn.execute(q).mappings()}


def _by_id(conn, model, fields, ids) -> dict[int, dict]:
    return _rows(conn, model, fields, model.__table__.c.id.in_(list(ids))) if ids else {}


def _pk(model) -> list:
    return list(model.__table__.primary_key.columns)


def _key(values) -> str:
    return "|".join(str(_enc(v)) for v in values)


def _ident(model, key: str):
    """A stored key back to what Session.get takes: 12, or (3, date(2026, 10, 1))."""
    parts = [date.fromisoformat(p) if isinstance(c.type, Date) else p if isinstance(c.type, String) else int(p)
             for c, p in zip(_pk(model), key.split("|"))]
    return parts[0] if len(parts) == 1 else tuple(parts)


def _key_of(obj) -> str | None:
    values = [getattr(obj, c.key) for c in _pk(type(obj))]
    return None if any(v is None for v in values) else _key(values)


def _by_keys(conn, model, fields: tuple[str, ...], keys) -> dict[str, dict]:
    """The stored values by key, read with a core SELECT (never the session's copies)."""
    keys = list(keys)
    if not keys:
        return {}
    t, pk = model.__table__, _pk(model)
    idents = [_ident(model, k) for k in keys]
    where = pk[0].in_(idents) if len(pk) == 1 else tuple_(*pk).in_(idents)
    q = select(*pk, *(t.c[f] for f in fields)).where(where)
    return {_key([r[c.name] for c in pk]): {f: _enc(r[f]) for f in fields} for r in conn.execute(q).mappings()}


def _linked_elsewhere(db: Session, account_id: int, child_id: int) -> bool:
    return db.scalar(select(Child.id).where(Child.account_id == account_id, Child.id != child_id,
                                            Child.removed_at.is_(None))) is not None


def _recorded(model, fields: tuple[str, ...], part: dict) -> tuple[str, ...]:
    """The fields to compare: today's, and any an older entry recorded that are no longer kept (a layout's label
    before it moved to undo_text), so that entry still compares and restores what it holds."""
    extra = sorted({f for v in part.values() if v for f in v} - set(fields))
    return fields + tuple(f for f in extra if f in model.__table__.c)


def _same(now: dict | None, then: dict | None) -> bool:
    """A row still as the action left it, over the fields the entry recorded (choice 9)."""
    if then is None:
        return now is None
    return now is not None and all(now.get(f) == v for f, v in then.items())


@dataclass
class Capture:
    db: Session
    txns: dict[int, dict] = field(default_factory=dict)
    others: dict[str, dict[str, dict | None]] = field(default_factory=lambda: {k: {} for k in OTHERS})
    made: list[object] = field(default_factory=list)
    target: int | None = None
    token: str | None = None
    texts: dict[tuple[str, str, str], list[str | None]] = field(default_factory=dict)
    labels: dict[tuple[str, str, str], str | None] = field(default_factory=dict)   # LABELS: the stored value first seen

    def keep_text(self, model: str, obj, field_name: str, old, new) -> None:
        """A text field this action changes on an existing row (a name, a note, who wrote it): the first old value and
        the last value written, for undo_text. Never call it for a row the action made: Undo deletes that row."""
        key = (model, str(obj.id), field_name)
        was = self.texts.get(key)
        self.texts[key] = [was[0] if was else _as_text(old), _as_text(new)]

    def before_flush(self, session, _flush_context, _instances) -> None:
        conn = session.connection()
        dirty = [o for o in session.dirty if session.is_modified(o, include_collections=False)]
        ids = [o.id for o in dirty if isinstance(o, Transaction) and o.id not in self.txns]
        for tid, vals in _by_id(conn, Transaction, TXN_FIELDS, ids).items():
            self.txns.setdefault(tid, vals)
        for key, (model, fields) in OTHERS.items():
            kept = self.others[key]
            changed = [k for o in dirty if isinstance(o, model) and (k := _key_of(o)) is not None and k not in kept]
            for k, vals in _by_keys(conn, model, fields, changed).items():
                kept.setdefault(k, vals)
            if key in LABELS:
                text_model, f = LABELS[key]
                for k, vals in _by_keys(conn, model, (f,), changed).items():
                    self.labels.setdefault((text_model, k, f), vals[f])
        rules = self.others["rules"]
        gone = [k for o in session.deleted if isinstance(o, MerchantRule) and (k := _key_of(o)) is not None and k not in rules]
        for k, vals in _by_keys(conn, MerchantRule, RULE_FIELDS, gone).items():
            rules.setdefault(k, vals)              # Engineering choice 6: Undo makes it again
        self.made += [o for o in session.new if isinstance(o, MADE) and o not in self.made]

    def on_execute(self, state) -> None:
        stmt = state.statement
        if state.is_update and getattr(getattr(stmt, "table", None), "name", None) == Transaction.__tablename__:
            state.session.flush()             # as autoflush would: the rows matched now are the rows it updates
            for tid, vals in _rows(state.session.connection(), Transaction, TXN_FIELDS, stmt.whereclause).items():
                self.txns.setdefault(tid, vals)
        elif state.is_delete and getattr(getattr(stmt, "table", None), "name", None) == SsEarnings.__tablename__:
            state.session.flush()             # a record import deletes the person's old years: keep them to bring back
            t, kept = SsEarnings.__table__, self.others["earnings"]
            q = select(t.c.person, t.c.year, t.c.earnings_cents, t.c.imported_at)
            if stmt.whereclause is not None:
                q = q.where(stmt.whereclause)
            for r in state.session.connection().execute(q).mappings():
                kept.setdefault(_key([r["person"], r["year"]]),
                                {"earnings_cents": r["earnings_cents"], "imported_at": _enc(r["imported_at"])})


@contextmanager
def capturing(db: Session, user_id: int, action: str, now: datetime) -> Iterator[Capture]:
    cap = Capture(db)
    before_flush, on_execute = cap.before_flush, cap.on_execute     # the same objects to listen and to remove
    event.listen(db, "before_flush", before_flush)
    event.listen(db, "do_orm_execute", on_execute)
    try:
        yield cap
        db.flush()                            # the last changes pass through before_flush while it still listens
    finally:
        event.remove(db, "before_flush", before_flush)
        event.remove(db, "do_orm_execute", on_execute)
    cap.token = _save(db, cap, user_id, action, now)


def purge_expired(db: Session, now: datetime) -> None:
    """Expired entries go, and their text with them (P36); text whose entry is already gone goes too."""
    live = select(UndoEntry.token).where(UndoEntry.expires_at > now)
    db.execute(delete(UndoText).where(UndoText.token.not_in(live)))
    db.execute(delete(UndoEntry).where(UndoEntry.expires_at <= now))


def _save(db: Session, cap: Capture, user_id: int, action: str, now: datetime) -> str:
    conn = db.connection()
    for o in cap.made:
        k = _key_of(o)
        if k is not None:                     # made by this action: undo removes it, whatever it went through after
            key = next(name for name, (model, _) in OTHERS.items() if isinstance(o, model))
            cap.others[key].setdefault(k, None)   # a row that replaced one keeps the old values to go back to
    for (text_model, k, f), old in cap.labels.items():
        new = _by_keys(conn, TEXT_MODELS[text_model], (f,), [k]).get(k, {}).get(f)
        if new != old and (text_model, k, f) not in cap.texts:
            cap.texts[(text_model, k, f)] = [_as_text(old), _as_text(new)]
    after_t = _by_id(conn, Transaction, TXN_FIELDS, cap.txns)
    txns = {k: v for k, v in cap.txns.items() if after_t.get(k) != v}
    before: dict = {"target": cap.target, "txns": {str(k): v for k, v in txns.items()}}
    after: dict = {"txns": {str(k): after_t.get(k) for k in txns}}
    for key, (model, fields) in OTHERS.items():
        kept = cap.others[key]
        now_vals = _by_keys(conn, model, fields, kept)
        changed = {k: v for k, v in kept.items() if v is None or now_vals.get(k) != v}
        before[key] = dict(changed)
        after[key] = {k: now_vals.get(k) for k in changed}
    purge_expired(db, now)                # cleanup: the next write that makes an entry
    token = secrets.token_urlsafe(32)
    db.add(UndoEntry(token=token, user_id=user_id, action=action, created_at=now, expires_at=now + TTL,
                     before=json.dumps(before), after=json.dumps(after)))
    for (model, key, field_name), (old, written) in cap.texts.items():
        db.add(UndoText(token=token, model=model, row_key=key, field=field_name, value=old, written=written))
    db.flush()
    return token


@dataclass(frozen=True)
class Undone:
    count: int
    target: Transaction | None
    action: str = ""


# Removing a note (JR: nothing vanishes unseen, always Undo). As a merge keeps the notes of rows it deletes: the entry
# holds the note's id, its transaction, who wrote it (a directory id) and when; its words and the author's name go to
# undo_text (P36). Undo makes it again with its id when free, so it returns to its place.
NOTE_REMOVE = "note_remove"
NOTE_TEXT = ("author_name", "body")


def remember_removed_note(db: Session, note: TransactionNote, user_id: int, now: datetime) -> str:
    """Call before deleting the note: one entry for its Undo, whose token the route answers."""
    purge_expired(db, now)                # cleanup: the next write that makes an entry
    token = secrets.token_urlsafe(32)
    kept = {"id": note.id, "transaction_id": note.transaction_id, "author_id": note.author_id,
            "created_at": _enc(note.created_at)}
    db.add(UndoEntry(token=token, user_id=user_id, action=NOTE_REMOVE, created_at=now, expires_at=now + TTL,
                     before=json.dumps({"target": note.transaction_id, "txns": {}, "note": kept}),
                     after=json.dumps({"txns": {}, "note": None})))
    for f in NOTE_TEXT:
        db.add(UndoText(token=token, model=TransactionNote.__tablename__, row_key=str(note.id), field=f,
                        value=getattr(note, f), written=None))
    db.flush()
    return token


def _restore_note(db: Session, token: str, before: dict) -> Undone:
    kept = before["note"]
    t = db.get(Transaction, kept["transaction_id"])
    if t is None:
        raise UndoRefused(409, CHANGED_SINCE)  # the transaction went, and its notes with it
    words = {x.field: x.value for x in db.scalars(select(UndoText).where(UndoText.token == token))}
    if any(f not in words for f in NOTE_TEXT):
        raise UndoRefused(410, GONE)
    n = TransactionNote(transaction_id=t.id, author_id=kept["author_id"], author_name=words["author_name"],
                        body=words["body"], created_at=datetime.fromisoformat(kept["created_at"]))
    if db.get(TransactionNote, kept["id"]) is None:
        n.id = kept["id"]
    db.add(n)
    db.flush()
    return Undone(1, t, NOTE_REMOVE)


def undo(db: Session, token: str, user_id: int, now: datetime) -> Undone:
    """Choice 3: the person who acted, in this book, within 15 minutes, once; 409 when anything changed since."""
    e = db.get(UndoEntry, token) if 0 < len(token) <= 64 else None
    if e is None or e.user_id != user_id:
        raise UndoRefused(404, NO_UNDO)
    if e.used_at is not None or e.expires_at <= now:
        raise UndoRefused(410, GONE)
    before, after = json.loads(e.before), json.loads(e.after)
    if e.action == NOTE_REMOVE:
        done = _restore_note(db, token, before)
        e.used_at = now
        db.execute(delete(UndoText).where(UndoText.token == token))
        db.flush()
        return done
    if e.action in ("merge", "different"):
        # Same-account spec, Undo: these change rows and tables a Review action never does, so their own handler
        # puts them back (imported here: the journal imports this module).
        from steward.services.same_account.journal import restore
        count = restore(db, token, before, after, now)
        e.used_at = now
        db.execute(delete(UndoText).where(UndoText.token == token))
        db.flush()
        return Undone(count, None)
    conn = db.connection()
    now_t = _by_id(conn, Transaction, TXN_FIELDS, [int(k) for k in after["txns"]])
    if not all(_same(now_t.get(int(k)), v) for k, v in after["txns"].items()):
        raise UndoRefused(409, CHANGED_SINCE)
    for key, (model, fields) in OTHERS.items():
        part = after.get(key, {})
        now_o = _by_keys(conn, model, _recorded(model, fields, part), part)
        if not all(_same(now_o.get(k), v) for k, v in part.items()):
            raise UndoRefused(409, CHANGED_SINCE)
    texts = db.scalars(select(UndoText).where(UndoText.token == token)).all()
    for x in texts:
        o = db.get(TEXT_MODELS[x.model], int(x.row_key))
        if (None if o is None else _as_text(getattr(o, x.field))) != x.written:
            raise UndoRefused(409, CHANGED_SINCE)
    old_text: dict[tuple[str, str], list[tuple[str, str | None]]] = defaultdict(list)
    for x in texts:
        old_text[(x.model, x.row_key)].append((x.field, x.value))
    try:
        for k, vals in before["txns"].items():
            t = db.get(Transaction, int(k))
            for f, v in vals.items():
                setattr(t, f, _dec(f, v))
        db.flush()
        for (model, key), vals in old_text.items():
            o = db.get(TEXT_MODELS[model], int(key))
            if o is not None:
                for f, v in vals:
                    setattr(o, f, _from_text(f, v))
        db.flush()
        for key, (model, _) in OTHERS.items():
            for k, vals in before.get(key, {}).items():
                o = db.get(model, _ident(model, k))
                if o is None and vals is not None and model is SsEarnings:
                    person, year = _ident(model, k)    # a year the import replaced away: it comes back
                    o = SsEarnings(person=person, year=year)
                    db.add(o)
                if o is None and vals is not None and model is MerchantRule:
                    o = MerchantRule(id=int(k))          # Engineering choice 6: deleted by the action, made again
                    for f, v in old_text.get(("rule", k), []):
                        setattr(o, f, _from_text(f, v))
                    db.add(o)
                if vals is None:
                    if o is not None and key not in CHANGE_ONLY:   # an entry made before CHANGE_ONLY: keep the line
                        db.delete(o)
                    continue
                for f, v in vals.items():
                    if model is Child and f == "account_id" and v is not None and _linked_elsewhere(db, v, o.id):
                        continue              # the 529 went to another kid since: the kid comes back without it
                    setattr(o, f, _dec(f, v))
            db.flush()                        # OTHERS' order: balances go before an account this action made
    except IntegrityError:
        raise UndoRefused(409, CHANGED_SINCE) from None   # something newer points at a row this action made
    e.used_at = now
    db.execute(delete(UndoText).where(UndoText.token == token))
    db.flush()
    target = db.get(Transaction, before["target"]) if before.get("target") else None
    return Undone(len(before["txns"]), target, e.action)
