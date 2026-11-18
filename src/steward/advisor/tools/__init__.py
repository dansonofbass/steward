"""The tool executor (spec 4.2, 8.2). A call's input is checked against its schema; the tool runs on a read session
(no write lock held while it computes) and returns plain values with Ref(kind, target) where an alias goes; a short
write session then gives any new aliases and swaps them in; the result is checked against its schema before it
leaves the NAS. Errors are the fixed words in steward_boundary.tools.ERRORS. Every tool is read-only."""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from steward.advisor.aliases import Aliases
from steward.books.people import Person, attach_people
from steward.books.registry import BookInfo
from steward.services.plan_cache import PlanCache
from steward_boundary import tools as T
from steward_boundary.text import is_stored_safe
from steward_boundary.validate import walk_strings

log = logging.getLogger("steward.advisor.tools")
LOOKUP_FAILED = "This couldn't be looked up just now."
REGISTRY: dict[str, Callable[[dict, "ToolEnv"], dict]] = {}


@dataclass(frozen=True)
class Ref:
    kind: str       # owner | user | child | account | payee
    target: Any


@dataclass
class ToolEnv:
    db: Session
    book: BookInfo
    user_id: int
    people: tuple[Person, ...]
    today: date
    plan_cache: PlanCache
    directory: Engine | None = None     # the directory, for the store-name cleaning's member names and emails


@dataclass(frozen=True)
class HomeOnly:
    """A tool result plus text that stays on the NAS (public issue #1): merchant_detail's rows go as "Zelle to [name]",
    and `home` holds the name each such row or payee could carry instead, keyed "r<i>" or "p<i>", for the card. Only a
    manager's tick swaps one in (turn.py). run_call returns it as the result's "home" key, which is never sent."""
    content: dict
    home: dict[str, str]


class ToolError(Exception):
    """The tool can't answer; the message is one of steward_boundary.tools.ERRORS."""

    def __init__(self, message: str):
        assert message in T.ERRORS, message
        super().__init__(message)
        self.message = message


class PlanFailed(Exception):
    def __init__(self, exc: BaseException):
        super().__init__(type(exc).__name__)
        self.exc = exc


def register(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


def _refs(value: Any, out: list[Ref]) -> None:
    if isinstance(value, Ref):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _refs(v, out)
    elif isinstance(value, list):
        for v in value:
            _refs(v, out)


def resolve(value: Any, aliases: Aliases) -> Any:
    if isinstance(value, Ref):
        return {"owner": aliases.owner, "user": aliases.user, "child": aliases.child, "account": aliases.account,
                "payee": aliases.payee}[value.kind](value.target)
    if isinstance(value, dict):
        return {k: resolve(v, aliases) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, aliases) for v in value]
    return value


def _error(call: dict, message: str) -> dict:
    return {"id": call["id"], "name": call["name"], "content": None, "error": message}


def run_call(call: dict, *, bind: Engine, book: BookInfo, user_id: int, people: Sequence[Person], today: date,
             plan_cache: PlanCache, directory: Engine | None = None) -> dict:
    name, inp = call["name"], call.get("input")
    spec = T.BY_NAME.get(name)
    if spec is None or T.validate_input(name, inp):
        return _error(call, "That input wasn't understood.")
    if book.kind not in spec.books:
        return _error(call, "Not in this book.")
    people = tuple(people)
    try:
        with Session(bind.execution_options(immediate=False)) as rdb:
            attach_people(rdb, lambda: people)
            draft = REGISTRY[name](inp, ToolEnv(rdb, book, user_id, people, today, plan_cache, directory))
            rdb.rollback()
        draft, home = (draft.content, draft.home) if isinstance(draft, HomeOnly) else (draft, None)
    except ToolError as e:
        return _error(call, e.message)
    except PlanFailed as e:
        from steward.services.plan import record_failure
        with Session(bind) as wdb:
            attach_people(wdb, lambda: people)          # the log line names Person 1 by their label
            record_failure(wdb, e.exc)
        return _error(call, "The plan couldn't be worked out.")
    except Exception:  # noqa: BLE001 - a failing tool answers is_error; the turn goes on (spec 10)
        log.exception("The %s tool failed", name)
        return _error(call, LOOKUP_FAILED)
    refs: list[Ref] = []
    _refs(draft, refs)
    with Session(bind) as wdb:
        aliases = Aliases(wdb, book, people)
        for r in sorted(set(refs), key=lambda r: (r.kind, isinstance(r.target, str), r.target if isinstance(r.target, int) else 0, str(r.target))):
            resolve(r, aliases)
        content = resolve(draft, aliases)
        wdb.commit()
    errs = T.validate_result(name, content)
    if errs:
        log.error("The %s tool's result didn't match its schema at %s", name, errs[0].split(":")[0])
        return _error(call, LOOKUP_FAILED)
    # Bank and inventory text goes through the strict stored-text path (no keep-list), so it fails here, early.
    for path, kind, text in walk_strings(T.result_schema(name), content):
        if kind == "free_text" and not is_stored_safe(text):
            log.error("The %s tool's result held text the stored-text rule would change at %s", name, path)
            return _error(call, LOOKUP_FAILED)
    if home is None:
        return {"id": call["id"], "name": name, "content": content, "error": None}
    if any(not isinstance(v, str) or len(v) > T.MERCHANT_STORE_CHARS or not is_stored_safe(v) for v in home.values()):
        log.error("The %s tool kept text at home that couldn't be sent if ticked", name)
        return _error(call, LOOKUP_FAILED)
    return {"id": call["id"], "name": name, "content": content, "error": None, "home": dict(home)}


def run_calls(calls: Sequence[dict], **kw) -> list[dict]:
    """Parallel tool calls run together and come back in one message (spec 8.2), in the order asked."""
    return [run_call(c, **kw) for c in calls]


from steward.advisor.tools import care, common, household, merchant, parent  # noqa: E402,F401 - registers the tools
