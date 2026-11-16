"""The book's known identifiers (spec 4.3, 4.5): what the exact pass replaces in typed text, and what the turn's
fingerprints are made from. Names come from the book's owners, its members (the directory) and the inventory;
numbers, emails, phones and addresses from the inventory and the directory; dates of birth from the facts. Nothing
here is sent anywhere: only salted hashes leave the NAS. Identifiers made only of generic words are left out
(ruling 4)."""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from steward.advisor.aliases import Aliases
from steward.books.people import Person
from steward.books.registry import BookInfo
from steward.db.directory_models import User
from steward.db.models import Account, Child, Institution, InventoryItem, Source, Transaction
from steward.services.plan_inputs import latest_facts
from steward.watch.payees import payee
from steward_boundary.fingerprint import tokens
from steward_boundary.normal import plain
from steward_boundary.vocab import generic

PAYEE_DAYS = 400


@dataclass(frozen=True)
class Identifier:
    text: str
    kind: str            # name | account | institution | payee | email | phone | address | number | dob
    replacement: str
    name: bool = False   # its parts are fingerprinted and matched too


def dob_forms(d: date) -> list[str]:
    return [f"{d.month:02d}/{d.day:02d}/{d.year}", f"{d.month}/{d.day}/{d.year % 100:02d}", f"{d:%B} {d.day}, {d.year}",
            f"{d.day} {d:%B} {d.year}", d.isoformat(), f"{d:%b}. {d.day} {d.year}"]


def _generic(text: str) -> bool:
    toks = tokens(text)
    return not toks or generic(toks)


def load_identifiers(db: Session, book: BookInfo, people: Sequence[Person], directory: Engine | None, aliases: Aliases,
                     today: date) -> list[Identifier]:
    out: list[Identifier] = []

    def add(text: str | None, kind: str, replacement: str, name: bool = False) -> None:
        text = plain(text or "").strip()
        if len(text) < 2 or (kind in ("name", "account", "institution", "payee", "address") and _generic(text)):
            return
        out.append(Identifier(text, kind, replacement, name))

    def add_name(full: str, replacement: str) -> None:
        # name=True: each part of 3 or more letters is matched alone too (known.py), so no part is added separately
        add(re.sub(r"\([^)]*\)", " ", full), "name", replacement, name=True)

    household = book.kind == "household"
    for o in book.owner_names:
        if household or o.key in ("joint", "business"):     # a household's labels are never typed by a person
            continue
        add_name(o.label, aliases.owner(o.key))
    first = book.owner_names[0].key if book.owner_names else None
    add_name(book.name, aliases.owner(first) if not household and first else "[name]")   # "Margaret Ellis"
    emails: dict[int, str] = {}
    if directory is not None:
        with Session(directory) as ddb:
            emails = dict(ddb.execute(select(User.id, User.email).where(User.id.in_([p.id for p in people]))).all())
    for p in people:
        rep = aliases.user(p.id)
        add_name(p.display_name, rep)
        add(p.username, "name", rep, name=True)
        add(emails.get(p.id), "email", "[email]")
    if household:
        # Every kid, removed ones too: a removed kid's name is scrubbed until the row is purged (profile spec P27).
        for c in db.scalars(select(Child).order_by(Child.birth_year, Child.id)):
            add_name(c.label, aliases.child(c.id))
        facts = latest_facts(db)
        for key in ("jr.dob", "spouse.dob"):
            try:
                d = date.fromisoformat(facts[key].value) if key in facts else None
            except ValueError:
                d = None
            for form in dob_forms(d) if d else ():
                add(form, "dob", "[date of birth]")
    for a in db.scalars(select(Account).order_by(Account.id)):
        add(a.name, "account", aliases.account(a.id))
    for name in db.scalars(select(Institution.name).where(Institution.source != Source.manual)):
        add(name, "institution", "[institution]")
    for item in db.scalars(select(InventoryItem).order_by(InventoryItem.id)):
        d = json.loads(item.details or "{}")
        if item.kind == "contact":
            add_name(item.name, "[name]")
        if item.institution:
            add(item.institution, "address" if d.get("type") == "property" else "institution",
                "[address]" if d.get("type") == "property" else "[institution]")
        if item.full_number:
            add(item.full_number, "number", "[account number]")
        for key, kind, rep in (("phone", "phone", "[phone]"), ("email", "email", "[email]"),
                               ("address", "address", "[address]")):
            if isinstance(d.get(key), str):
                add(d[key], kind, rep)
        if isinstance(d.get("match_text"), str):
            add(d["match_text"], "payee", "[payee]")
    seen: set[str] = set()
    for raw, merchant in db.execute(select(Transaction.raw_description, Transaction.merchant)
                                    .where(Transaction.posted_at >= today - timedelta(days=PAYEE_DAYS)).distinct()):
        p = payee(raw, merchant)
        if not p.key or p.key in seen:
            continue
        seen.add(p.key)
        rep = aliases.existing("payee", p.key) or "[payee]"
        add(p.name, "payee", rep)
        if merchant:
            add(merchant, "payee", rep)
    return out
