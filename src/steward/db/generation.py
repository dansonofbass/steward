"""The vault write generation (controller ruling, M2-B final fix wave): a process-wide counter that goes up after
every commit that changed the vault, so caches of figures built from the vault (the plan's engine inputs) know
when to rebuild.

The hooks sit on the Session class, so request sessions, test sessions and the SimpleFIN scheduler's sessions all
bump it. A flush, or an ORM-enabled INSERT, UPDATE or DELETE run through a session, marks the session; the mark is
turned into a bump by after_commit and dropped by an outermost rollback. A savepoint rollback keeps the mark, since
the outer transaction may still commit earlier changes (an extra bump only costs one rebuild).

Rows of the auth sessions table are ignored: every signed-in request writes last_seen_at there, and nothing built
from the vault reads it. Writes from another process, or outside a Session, are not seen; such a cache is still
keyed on the day, so it is stale at most until the next write here or midnight.

Phase 18: a request session names its book (deps._book_session) and bumps only that book, so another book's writes leave
this book's cache alone; a session that names no book bumps every book, as before. Home's visit stamp is ignored like the
auth sessions table: nothing built from the vault reads it."""
from __future__ import annotations

import itertools
import threading

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState
from sqlalchemy.orm import Session as OrmSession

from steward.db.directory_models import Session as AuthSession
from steward.db.models import HomeVisit

BOOK = "steward.book_id"            # session.info: the book whose database the session writes (deps._book_session)
_MARK = "steward.vault_changed"
_IGNORED = (AuthSession, HomeVisit)
_IGNORED_TABLES = frozenset(m.__tablename__ for m in _IGNORED)
_lock = threading.Lock()
_generation = 0                     # every bump
_unscoped = 0                       # bumps from sessions that name no book
_books: dict[int, int] = {}         # bumps from each book's own sessions


def current(book_id: int | None = None):
    """No book: a number that moves with every write anywhere. A book: a pair that moves with writes from sessions that
    name no book and with that book's own, never with another book's."""
    with _lock:
        if book_id is None:
            return _generation
        return (_unscoped, _books.get(book_id, 0))


def bump(book_id: int | None = None) -> int:
    global _generation, _unscoped
    with _lock:
        _generation += 1
        if book_id is None:
            _unscoped += 1
        else:
            _books[book_id] = _books.get(book_id, 0) + 1
        return _generation


def _counts(obj: object) -> bool:
    return not isinstance(obj, _IGNORED)


@event.listens_for(OrmSession, "after_flush")
def _after_flush(session: OrmSession, flush_context) -> None:
    if any(_counts(o) for o in itertools.chain(session.new, session.dirty, session.deleted)):
        session.info[_MARK] = True


@event.listens_for(OrmSession, "do_orm_execute")
def _on_execute(state: ORMExecuteState) -> None:
    if not (state.is_insert or state.is_update or state.is_delete):
        return
    table = getattr(state.statement, "table", None)
    if getattr(table, "name", None) not in _IGNORED_TABLES:
        state.session.info[_MARK] = True


@event.listens_for(OrmSession, "after_commit")
def _after_commit(session: OrmSession) -> None:
    if session.info.pop(_MARK, False):
        bump(session.info.get(BOOK))


@event.listens_for(OrmSession, "after_rollback")
def _after_rollback(session: OrmSession) -> None:
    if not session.in_nested_transaction():
        session.info.pop(_MARK, None)
