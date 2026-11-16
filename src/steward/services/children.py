"""Kids and their 529s (profile spec, Kids and college): which account looks like whose (P18), what each 529 holds,
puts in and earns (the consequence line, P16-P17), making an account a 529 plan, and purging removed kids once the
undo window has passed (P27)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from steward.db.models import LIABILITY_TYPES, Account, AccountType, Child, Source, active_children
from steward.engine import college
from steward.engine.inputs import Bucket, Child as EngineChild
from steward.events import resolve_events_matching
from steward.services import asset_classes as ac
from steward.services.accounts import latest_balance
from steward.services.categorize import sort_investment_rows
from steward.services.contributions import contributions
from steward.services.transfers import account_type_changed
from steward.services.undo import TTL

NOT_A_529 = frozenset(LIABILITY_TYPES | {AccountType.business_checking, AccountType.business_credit,
                                         AccountType.property, AccountType.vehicle})


def fold(s: str) -> str:
    """Accents dropped and case folded, so "Zoë" and "ZOE" meet (Engineering choice 22)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).casefold()


def first_name(label: str) -> str:
    words = label.split()
    return fold(words[0]) if words else ""


def suggest(db: Session) -> list[dict]:
    """P18: an unlinked kid's first name as a whole word in exactly one active, unlinked account of an allowed type,
    and that account names no other kid."""
    kids = list(db.scalars(active_children()))
    linked = {k.account_id for k in kids if k.account_id is not None}
    accounts = [a for a in db.scalars(select(Account).where(Account.is_active.is_(True)).order_by(Account.id))
                if a.type not in NOT_A_529 and a.id not in linked]

    def names(k: Child) -> list[Account]:
        n = first_name(k.label)
        return [a for a in accounts if n and re.search(rf"\b{re.escape(n)}\b", fold(a.name))] if n else []

    hits = {k.id: names(k) for k in kids}
    per_account = Counter(a.id for found in hits.values() for a in found)
    out = []
    for k in kids:
        found = hits[k.id]
        if k.account_id is None and len(found) == 1 and per_account[found[0].id] == 1:
            a = found[0]
            out.append({"child_id": k.id, "account_id": a.id, "account_name": a.name, "account_type": a.type.value})
    return out


def plans_out(db: Session, today: date) -> list[dict]:
    """Every active 529: its balance, whether a bank sends it, its deposits over the last 12 months as a monthly amount
    to the dollar (P17; connected accounts only) and its mix's real return (P16)."""
    holdings, overrides = ac.latest_holdings(db), ac.overrides(db)
    out = []
    for a in db.scalars(select(Account).where(Account.is_active.is_(True), Account.type == AccountType.plan529)
                        .order_by(Account.id)):
        lb = latest_balance(db, a.id)
        mix = ac.account_mix(holdings.get(a.id, []), a.type, overrides, today.year).mix
        if a.advisory_fee_bp:
            mix = replace(mix, fee_bp=mix.fee_bp + a.advisory_fee_bp)
        connected = a.source == Source.simplefin
        deposits = contributions(db, [a.id], today - timedelta(days=365), today) if connected else None
        out.append({"account_id": a.id, "name": a.name, "balance_cents": max(0, lb[1]) if lb else 0,
                    "connected": connected,
                    "deposits_monthly_cents": (deposits + 600) // 1200 * 100 if deposits else None,
                    "real_return": college.real_return(mix)})
    return out


def outlook_out(c: Child, plan: dict | None, plan_year: int) -> dict:
    """The consequence line's numbers for one kid, with their 529 (or none yet)."""
    eng = EngineChild(c.label, c.birth_year, c.cost_level, Bucket(plan["balance_cents"] if plan else 0, ac.RETIREMENT_DEFAULT),
                      c.monthly_contribution_cents, c.share_pct, c.covers_living)
    r = plan["real_return"] if plan else college.real_return(ac.RETIREMENT_DEFAULT)
    o = college.outlook(eng, plan_year, r)
    return {"years": o.years, "total_cents": o.total_cents, "covered_cents": o.covered_cents}


def make_529(db: Session, a: Account, now: datetime) -> None:
    """P18's "Link it and make it a 529 plan": the type changes as PATCH /accounts changes it."""
    was = a.type
    a.type = AccountType.plan529
    account_type_changed(db, a, was)
    sort_investment_rows(db, a)
    if was == AccountType.unknown:
        resolve_events_matching(db, "system", f"New account '{a.name}' from ", now)


def purge_removed(db: Session, now: datetime) -> None:
    """P27: a removed kid's row goes once its Undo can no longer bring it back (no commit)."""
    db.execute(delete(Child).where(Child.removed_at.is_not(None), Child.removed_at <= now - TTL))
