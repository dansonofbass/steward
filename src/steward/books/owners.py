"""Owner names per book (spec 2.1). Each name has a key, stored in account.owner, and a label people see. "Ours"
keeps the four household keys and labels jr and spouse with its people's names, as before. A parent book's keys
come from its labels when the book is made and never change (ruling 2)."""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MAX_OWNERS = 8
MAX_LABEL = 40
CHOOSE_NAMES = "Enter one to eight owner names of up to 40 characters."
NAMES_DIFFER = "Each owner name must be different."


@dataclass(frozen=True)
class OwnerName:
    key: str
    label: str


HOUSEHOLD_OWNER_NAMES: tuple[OwnerName, ...] = (
    OwnerName("jr", "Person 1"), OwnerName("spouse", "Person 2"), OwnerName("joint", "Joint"),
    OwnerName("business", "Business"),
)


def owner_key(label: str) -> str:
    """Lowercase ASCII letters and digits joined by hyphens. Apostrophes vanish rather than split a word."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    plain = plain.replace("'", "").lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:MAX_LABEL].strip("-")


def parse_owner_names(labels: object) -> tuple[OwnerName, ...]:
    if not isinstance(labels, list) or not 1 <= len(labels) <= MAX_OWNERS:
        raise ValueError(CHOOSE_NAMES)
    out: list[OwnerName] = []
    for raw in labels:
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > MAX_LABEL:
            raise ValueError(CHOOSE_NAMES)
        label = raw.strip()
        out.append(OwnerName(owner_key(label) or f"owner-{len(out) + 1}", label))
    keys = [o.key for o in out]
    if len(set(keys)) != len(keys):
        raise ValueError(NAMES_DIFFER)
    return tuple(out)


def to_json(names: Iterable[OwnerName]) -> str:
    return json.dumps([{"key": o.key, "label": o.label} for o in names])


def from_json(text: str) -> tuple[OwnerName, ...]:
    return tuple(OwnerName(d["key"], d["label"]) for d in json.loads(text))


def owner_options(kind: str, names: Sequence[OwnerName], people) -> tuple[OwnerName, ...]:
    """What a book's owner picker shows. A household's two people are named from its members (household_labels); a
    household of one offers no second person."""
    if kind != "household":
        return tuple(names)
    from steward.books.people import household_labels, household_people
    labels = household_labels(people)
    alone = household_people(people)[1] is None
    return tuple(OwnerName(o.key, labels.get(o.key, o.label)) for o in names if not (alone and o.key == "spouse"))


def default_owner(names: Sequence[OwnerName]) -> str:
    """Who owns an account the bank feed brings in before anyone says: Joint when the book has it."""
    keys = [o.key for o in names]
    return "joint" if "joint" in keys else keys[0]
