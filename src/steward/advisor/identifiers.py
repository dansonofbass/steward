"""The book's known identifiers (spec 4.3, 4.5): what the exact pass replaces in typed text, and what the turn's
fingerprints are made from. Names come from the book's owners, its members (the directory) and the inventory;
numbers, emails, phones and addresses from the inventory and the directory; dates of birth from the facts; and, since
public issue #2, the other names the book stores (steward.services.held_names), institutions added by hand and every
payee the book has seen. Nothing here is sent anywhere: only salted hashes leave the NAS. Identifiers made only of
generic words are left out (ruling 4), except a person's name ("August"), which is kept as `everyday`."""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from steward.advisor.aliases import Aliases
from steward.books.people import Person
from steward.books.registry import BookInfo
from steward.db.directory_models import User
from steward.db.models import Account, Child, Institution, InventoryItem, Transaction
from steward.services.held_names import held_names
from steward.services.plan_inputs import latest_facts
from steward.watch.payees import payee
from steward_boundary.fingerprint import canon, tokens
from steward_boundary.normal import plain
from steward_boundary.vocab import generic

@dataclass(frozen=True)
class Identifier:
    text: str
    kind: str            # name | account | institution | payee | email | phone | address | number | dob
    replacement: str
    name: bool = False   # its parts are fingerprinted and matched too
    everyday: bool = False   # a person's name made only of everyday words, kept anyway (public issue #2)


def dob_forms(d: date) -> list[str]:
    """Each usual written form once; the last two, with and without leading zeros, came in review round 4."""
    return list(dict.fromkeys([
        f"{d.month:02d}/{d.day:02d}/{d.year}", f"{d.month}/{d.day}/{d.year % 100:02d}", f"{d:%B} {d.day}, {d.year}",
        f"{d.day} {d:%B} {d.year}", d.isoformat(), f"{d:%b}. {d.day} {d.year}", f"{d.month}/{d.day}/{d.year}",
        f"{d.month:02d}/{d.day:02d}/{d.year % 100:02d}"]))


# Both are cached by text: every call reads each name the book's payees have had, thousands in a book some years old,
# and merchant_detail's tool budget holds only with the work done once per name (the final review of public issue #1).
@lru_cache(maxsize=65_536)
def _generic(text: str) -> bool:
    toks = tokens(text)
    return not toks or generic(toks)


@lru_cache(maxsize=65_536)
def _form(text: str) -> str:
    return canon(tokens(text))


def load_identifiers(db: Session, book: BookInfo, people: Sequence[Person], directory: Engine | None, aliases: Aliases,
                     today: date) -> list[Identifier]:
    out: list[Identifier] = []

    def add(text: str | None, kind: str, replacement: str, name: bool = False, everyday_ok: bool = False) -> None:
        text = plain(text or "").strip()
        everyday = False
        if len(text) < 2:
            return
        if kind in ("name", "account", "institution", "payee", "address") and _generic(text):
            if not (everyday_ok and tokens(text)):
                return
            everyday = True
        out.append(Identifier(text, kind, replacement, name, everyday))

    def add_name(full: str, replacement: str, everyday_ok: bool = True) -> None:
        # name=True: each part of 3 or more characters, or 2 letters, is matched alone too (known.py), so no part is
        # added separately. A person's name made of everyday words is kept (public issue #2).
        add(re.sub(r"\([^)]*\)", " ", full), "name", replacement, name=True, everyday_ok=everyday_ok)

    household = book.kind == "household"
    for o in book.owner_names:
        if household or o.key in ("joint", "business"):     # a household's labels are never typed by a person
            continue
        add_name(o.label, aliases.owner(o.key))
    first = book.owner_names[0].key if book.owner_names else None
    # "Margaret Ellis"; a household book's own name ("Ours") is a label, not a person's, so everyday words drop
    add_name(book.name, aliases.owner(first) if not household and first else "[name]", everyday_ok=not household)
    emails: dict[int, str] = {}
    if directory is not None:
        with Session(directory) as ddb:
            emails = dict(ddb.execute(select(User.id, User.email).where(User.id.in_([p.id for p in people]))).all())
    for p in people:
        rep = aliases.user(p.id)
        add_name(p.display_name, rep)
        add(p.username, "name", rep, name=True, everyday_ok=True)      # "august" too (review round 4)
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
    for name in db.scalars(select(Institution.name).order_by(Institution.id)):    # those added by hand too (#2)
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
    payee_texts: set[str] = set()
    # Newest first, so if the fingerprints must stop short of the START frame's limit (redact.turn_hash_sets), the
    # payees left out are the oldest. Each distinct name is loaded, not one per payee key: an older row of the same
    # key can carry another name in its merchant field (review round 4).
    newest = (select(Transaction.raw_description, Transaction.merchant)
              .group_by(Transaction.raw_description, Transaction.merchant)
              .order_by(func.max(Transaction.posted_at).desc(), Transaction.raw_description, Transaction.merchant))
    for raw, merchant in db.execute(newest):
        p = payee(raw, merchant)
        if not p.key:
            continue
        for text in (p.name, merchant) if merchant else (p.name,):
            form = _form(text or "")
            if form in payee_texts:
                continue
            add(text, "payee", aliases.existing("payee", p.key) or "[payee]")
            payee_texts.add(form)
    # After the payees, and never one that is a payee's name: a set-aside or a name given to a row or rule is often a
    # store's ("Costco"), and that store keeps its payee alias in the question, its name in approved store rows, and
    # its approvable hash.
    for text, kind in held_names(db):
        if _form(text or "") not in payee_texts:
            add(text, kind, "[payee]" if kind == "payee" else "[name]")
    return out
