"""Aliases (spec 4.2). Claude sees "Person 1", "Account 3", "Payee 4"; Steward shows the real labels. An alias is given
the first time it's needed and never changes. Owners get theirs all at once in owner-name order, children all at once
oldest first, accounts all at once in id order, payees as they first appear (the executor asks in key order). save=False
works out what an alias would be without writing it (the preview)."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.books.owners import owner_options
from steward.books.people import Person, household_people
from steward.books.registry import BookInfo
from steward.db.models import Account, AdvisorAlias, Child, InventoryItem
from steward.inventory.present import clean_account, mask
from steward.watch.payees import display as payee_display
from steward.watch.vocab import METHOD_TITLES
from steward_boundary.aliases import ALIAS_TOKEN_RE, number_of, protected_spans

HOUSEHOLD_OWNERS = {"jr": "Person 1", "spouse": "Person 2", "joint": "Joint", "business": "Business"}


class Aliases:
    def __init__(self, db: Session, book: BookInfo, people: Sequence[Person], *, save: bool = True):
        self.db, self.book, self.people, self.save = db, book, tuple(people), save
        self._map: dict[tuple[str, str], str] = {(r.kind, r.target): r.alias for r in db.scalars(select(AdvisorAlias))}
        self._children_done = False
        self._accounts_done = False
        self._issued: set[str] = set()
        self._ensure_owners()

    @property
    def _household(self) -> bool:
        return self.book.kind == "household"

    def _next(self, prefix: str, floor: int = 1) -> str:
        used = [p[1] for a in self._map.values() if (p := number_of(a)) and p[0] == prefix]
        return f"{prefix} {max([floor - 1, *used]) + 1}"

    def _next_person(self) -> str:
        return self._next("Person", 3 if self._household else 2)

    def _add(self, kind: str, target: object, alias: str) -> str:
        self._map[(kind, str(target))] = alias
        if self.save:
            self.db.add(AdvisorAlias(kind=kind, target=str(target), alias=alias))
        return alias

    def existing(self, kind: str, target: object) -> str | None:
        return self._map.get((kind, str(target)))

    def _ensure_owners(self) -> None:
        for i, o in enumerate(self.book.owner_names):
            if ("owner", o.key) in self._map:
                continue
            if self._household:
                alias = HOUSEHOLD_OWNERS.get(o.key) or self._next_person()
            elif o.key in ("joint", "business"):
                alias = o.key.title()
            elif i == 0:
                alias = "Parent"
            else:
                alias = self._next_person()
            self._add("owner", o.key, alias)

    def _owner(self, key: str) -> str:
        return self.existing("owner", key) or self._add("owner", key, self._next_person())

    def _user(self, user_id: int) -> str:
        found = self.existing("user", user_id)
        if found:
            return found
        if self._household:
            jr, spouse = household_people(self.people)
            if jr is not None and jr.id == user_id:
                return self._add("user", user_id, self._owner("jr"))
            if spouse is not None and spouse.id == user_id:
                return self._add("user", user_id, self._owner("spouse"))
        return self._add("user", user_id, self._next_person())

    def _child(self, child_id: int) -> str:
        if self.existing("child", child_id) is None and not self._children_done:
            for c in self.db.scalars(select(Child).order_by(Child.birth_year, Child.id)):
                if self.existing("child", c.id) is None:
                    self._add("child", c.id, self._next("Child"))
            self._children_done = True
        return self.existing("child", child_id) or self._add("child", child_id, self._next("Child"))

    def _account(self, account_id: int) -> str:
        """Accounts without an alias get theirs all at once in id order, as children do, so the number doesn't depend
        on which is asked for first: /about, /preview and the turn hand out the same ones (Argon follow-up 2)."""
        if self.existing("account", account_id) is None and not self._accounts_done:
            for aid in self.db.scalars(select(Account.id).order_by(Account.id)):
                if self.existing("account", aid) is None:
                    self._add("account", aid, self._next("Account"))
            self._accounts_done = True
        return self.existing("account", account_id) or self._add("account", account_id, self._next("Account"))

    def _payee(self, key: str) -> str:
        return self.existing("payee", key) or self._add("payee", key, self._next("Payee"))

    def _give(self, alias: str) -> str:
        self._issued.add(alias)
        return alias

    @property
    def issued(self) -> frozenset[str]:
        """The aliases handed out by this object, i.e. issued in this turn. Only these are protected (boundary 2.5)."""
        return frozenset(self._issued)

    def protected(self, text: str) -> list[tuple[int, int]]:
        """Spans of `text` (plain) holding an alias issued this turn exactly as issued; nothing else shields anything."""
        return protected_spans(text, self._issued)

    def owner(self, key: str) -> str:
        return self._give(self._owner(key))

    def user(self, user_id: int) -> str:
        return self._give(self._user(user_id))

    def child(self, child_id: int) -> str:
        return self._give(self._child(child_id))

    def account(self, account_id: int) -> str:
        return self._give(self._account(account_id))

    def payee(self, key: str) -> str:
        return self._give(self._payee(key))

    def labels(self) -> dict[str, str]:
        owners = {o.key: o.label for o in owner_options(self.book.kind, self.book.owner_names, self.people)}
        names = {str(p.id): p.display_name for p in self.people}
        children = {str(c.id): c.label for c in self.db.scalars(select(Child))}
        accounts = {str(a.id): a.name for a in self.db.scalars(select(Account))}
        last4 = {str(i.account_id): i.last4 for i in self.db.scalars(
            select(InventoryItem).where(InventoryItem.account_id.is_not(None)))}
        out: dict[str, str] = {}
        for (kind, target), alias in self._map.items():
            if kind == "owner":
                label = owners.get(target)
            elif kind == "user":
                label = names.get(target)
            elif kind == "child":
                label = children.get(target)
            elif kind == "account":
                name, l4 = accounts.get(target), last4.get(target)
                label = None if name is None else " ".join([clean_account(name, l4)] + ([mask(l4)] if l4 else []))
            else:
                label = payee_label(target)
            if label:
                out.setdefault(alias, label)
        return out


def payee_label(key: str) -> str:
    if ":" in key:
        channel, name = key.split(":", 1)
        title = METHOD_TITLES.get(channel) or channel.replace("_", " ").title()
        return f"{title} to {payee_display(name)}"
    return payee_display(key)


def display(text: str, labels: dict[str, str]) -> str:
    """Whole alias tokens become real labels on screen (spec 4.2): "Account 3" is "Joint checking ••4417"."""
    return ALIAS_TOKEN_RE.sub(lambda m: labels.get(m.group(0), m.group(0)), text)
