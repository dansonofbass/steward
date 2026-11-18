"""Names the book stores outside the people, accounts and inventory that steward.advisor.identifiers reads itself
(public issue #2): who pays the household back, set-asides, the nicknames people gave rows and rules, as (text, kind).
The exact pass replaces each with "[payee]" or "[name]" before a question leaves, and only their salted hashes reach the
gateway. They are read here, outside steward.advisor, because a nickname is a label a person typed: no module on the way
to Claude reads that field (tests/advisor/test_tools_never_read_notes.py), and this one only hands it to the exact pass
as something to remove."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import MerchantRule, Reimburser, SetAside, Transaction


def held_names(db: Session) -> list[tuple[str, str]]:
    """("Acme", "payee"), ("Grandma's care", "name"), ... in a fixed order. A set-aside's name can hold a person's, so
    it is replaced as a name, matched whole; a reimburser or a nickname names who was paid or who pays, so as a payee."""
    out: list[tuple[str, str]] = [(n, "payee") for n in db.scalars(select(Reimburser.name).order_by(Reimburser.id))]
    out += [(n, "name") for n in db.scalars(select(SetAside.name).order_by(SetAside.id))]
    out += [(n, "payee") for n in db.scalars(select(MerchantRule.nickname).where(MerchantRule.nickname.is_not(None))
                                              .order_by(MerchantRule.id))]
    out += [(n, "payee") for n in db.scalars(select(Transaction.nickname).where(Transaction.nickname.is_not(None))
                                              .distinct().order_by(Transaction.nickname))]
    return out
