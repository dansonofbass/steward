"""Directory facts the change record needs (spec 5): the names of people, including ones who have since left a book,
and a book's membership changes, which are kept in the directory so a removal stays on record."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from steward.books.people import RESTORED_BY, RESTORED_NAME
from steward.db.directory_models import MembershipChange, User


@dataclass(frozen=True)
class MemberChange:
    id: int
    at: datetime
    user_id: int
    action: str
    role_after: str | None
    by_user_id: int | None


def names_for(directory: Engine, ids: Iterable[int | None]) -> dict[int, str]:
    """Names by directory id, including people who have left; a restored book's RESTORED_BY is named for what it is."""
    wanted = {i for i in ids if i is not None}
    restored = {RESTORED_BY: RESTORED_NAME} if RESTORED_BY in wanted else {}
    wanted.discard(RESTORED_BY)
    if not wanted:
        return restored
    with Session(directory) as s:
        return {**dict(s.execute(select(User.id, User.display_name).where(User.id.in_(wanted))).all()), **restored}


def membership_changes(directory: Engine, book_id: int, *, by: int | None = None, before: datetime | None = None,
                       limit: int = 50) -> list[MemberChange]:
    with Session(directory) as s:
        q = select(MembershipChange).where(MembershipChange.book_id == book_id)
        if by is not None:
            q = q.where(MembershipChange.by_user_id == by)
        if before is not None:
            q = q.where(MembershipChange.at < before)
        rows = s.scalars(q.order_by(MembershipChange.at.desc(), MembershipChange.id.desc()).limit(limit))
        return [MemberChange(r.id, r.at, r.user_id, r.action, r.role_after, r.by_user_id) for r in rows]
