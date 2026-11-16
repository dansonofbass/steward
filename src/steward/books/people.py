"""The people of a book, as the book's services see them. A book never stores names (spec 2.2), so a book
session carries a function that returns its members from the directory."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

PEOPLE_KEY = "steward.people"
# Who did something in a book restored from an export: the ids were the old NAS's directory's, so the restore puts
# this in their place (services/book_restore.py). The directory never issues 0: a SQLite rowid starts at 1.
RESTORED_BY = 0
RESTORED_NAME = "Someone, before this book was restored"       # starting a line, or a value on its own
RESTORED_BY_NAME = "someone, before this book was restored"    # mid-sentence: "saved by someone, before ..."
PERSON_1, PERSON_2 = "Person 1", "Person 2"     # spec 2026-11-05, section 7: a household's labels with no one to name


@dataclass(frozen=True)
class Person:
    id: int
    username: str
    display_name: str
    role: str = "manager"


def attach_people(db: Session, fn: Callable[[], Iterable[Person]]) -> None:
    db.info[PEOPLE_KEY] = fn


def people_of(db: Session) -> tuple[Person, ...]:
    fn = db.info.get(PEOPLE_KEY)
    return tuple(fn()) if fn is not None else ()


def names_of(people: Iterable[Person], *, mid: bool = False) -> dict[int, str]:
    """Display names by directory id, for naming who did something: a restored book's RESTORED_BY too, in lowercase
    when the name goes mid-sentence ("by {name}")."""
    return {RESTORED_BY: RESTORED_BY_NAME if mid else RESTORED_NAME, **{p.id: p.display_name for p in people}}


def mid_sentence(name: str | None) -> str | None:
    """A name from names_of or history.names_for, as it reads after "by" or "to"."""
    return RESTORED_BY_NAME if name == RESTORED_NAME else name


def household_people(people: Iterable[Person]) -> tuple[Person | None, Person | None]:
    """Person 1 is the book's earliest manager by directory id (its earliest member when it has none); Person 2 is
    the earliest member after them. Owner keys jr and spouse are theirs. A third person is neither."""
    ordered = sorted(people, key=lambda p: p.id)
    first = next((p for p in ordered if p.role == "manager"), ordered[0] if ordered else None)
    second = next((p for p in ordered if p != first), None)
    return first, second


def household_labels(people: Iterable[Person]) -> dict[str, str]:
    first, second = household_people(people)
    return {"jr": first.display_name if first else PERSON_1, "spouse": second.display_name if second else PERSON_2}


# guided setup spec 8.2: a Sample's household shows as Alex and Sam, whoever looks; negative ids never match a real
# user (plan D2).
SAMPLE_PEOPLE = (Person(-2, "alex", "Alex", "manager"), Person(-1, "sam", "Sam", "manager"))


def sample_people(real: tuple[Person, ...]) -> tuple[Person, ...]:
    return SAMPLE_PEOPLE + real
