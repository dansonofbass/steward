"""Parent tools (spec 4.2): the inventory, money coming in, insurance premiums and flags. Only the allowed fields
(spec 4.1): kinds, types, statuses, amounts, frequencies, usual days, account aliases, renewal months, counts. Never
policy numbers, contacts, phones, emails, where documents are kept, logins or notes."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import select

from steward.advisor.tools import Ref, ToolEnv, ToolError, register
from steward.advisor.tools.common import BAD_INPUT
from steward.db.models import Flag, Transaction
from steward import clock
from steward.inventory import kinds as K
from steward.inventory.views import Loaded, load
from steward.services.vault_flows import month_add
from steward.watch import vocab as WV
from steward.watch.due import due_date, nominal
from steward.watch.payees import payee
from steward_boundary import vocab as V

STATUS = {"open": "open", "checking": "open", "expected": "expected", "handled": "handled", "arrived": "handled"}


def _load(env: ToolEnv) -> Loaded:
    return load(env.db, {o.key: o.label for o in env.book.owner_names})


def _type(L: Loaded, item) -> str | None:
    t = L.details[item.id].get(K.TYPE_FIELD[item.kind])
    return t if t in V.ITEM_TYPES else None


def _numbers(L: Loaded) -> dict[int, int]:
    seen: dict[tuple, int] = {}
    out = {}
    for item in L.items:
        key = (item.kind, _type(L, item))
        seen[key] = seen.get(key, 0) + 1
        out[item.id] = seen[key]
    return out


def _via(L: Loaded, ref_id) -> tuple[Ref | None, str | None]:
    ref = L.by_id.get(ref_id)
    if ref is None:
        return None, None
    if ref.kind == "account" and ref.account_id:
        return Ref("account", ref.account_id), None
    if ref.kind == "income":
        src = L.details[ref.id].get("source")
        return None, src if src in V.INCOME_SOURCES else None
    return None, None


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _freq(d: dict) -> str | None:
    return d.get("frequency") if d.get("frequency") in V.FREQUENCIES else None


def _renewal(d: dict) -> str | None:
    r = d.get("renewal_on")
    return r[:7] if isinstance(r, str) and len(r) >= 7 else None


def _matching(account_id: int, match: str, deposits: bool):
    sign = Transaction.amount_cents > 0 if deposits else Transaction.amount_cents < 0
    return select(Transaction).where(Transaction.account_id == account_id, sign,
                                     Transaction.raw_description.icontains(match, autoescape=True))


def _source(L: Loaded, item, field: str) -> tuple[int | None, str]:
    d = L.details[item.id]
    via = L.by_id.get(d.get(field))
    account_id = via.account_id if via is not None and via.kind == "account" else None
    return account_id, (d.get("match_text") or item.institution or "").strip()


@register("inventory")
def inventory(inp: dict, env: ToolEnv) -> dict:
    L = _load(env)
    n = _numbers(L)
    rows = []
    for item in L.items:
        if inp["kind"] and item.kind != inp["kind"]:
            continue
        d = L.details[item.id]
        paid, paid_income = _via(L, d.get("paid_from_id"))
        lands, _ = _via(L, d.get("lands_in_id"))
        bal = L.balances.get(item.account_id) if item.account_id else None
        rows.append({"kind": item.kind, "type": _type(L, item), "n": n[item.id], "status": item.status,
                     "owner": Ref("owner", item.owner),
                     "account": Ref("account", item.account_id) if item.kind == "account" and item.account_id else None,
                     "amount_cents": _int(d.get("amount_cents")), "frequency": _freq(d),
                     "usual_day": _int(d.get("usual_day")), "lands_in": lands, "paid_from": paid,
                     "paid_from_income": paid_income, "renewal_month": _renewal(d),
                     "balance_cents": bal[1] if bal else None, "as_of": bal[0].isoformat() if bal else None})
    accounts = [i for i in L.items if i.kind == "account" and i.status != "closed"]
    totals = [{"group": key, "cents": sum(L.balances[i.account_id][1] for i in accounts
                                          if K.TOTAL_GROUP.get(L.details[i.id].get("type")) == key
                                          and i.account_id in L.balances)} for key, _label in K.TOTALS]
    return {"items": rows[:300], "needs_checking": sum(1 for i in L.items if i.status == "needs_checking"),
            "totals": totals}


def _month_of(posted: date, usual: int | None) -> str:
    """A deposit counts for the month whose usual day it is nearest, so a payment that comes early over a weekend
    still counts for its own month."""
    if not usual:
        return posted.strftime("%Y-%m")
    first = posted.replace(day=1)
    best = min((month_add(first, k) for k in (-1, 0, 1)),
               key=lambda m: abs((nominal(m.year, m.month, usual) - posted).days))
    return best.strftime("%Y-%m")


@register("money_in_monthly")
def money_in_monthly(inp: dict, env: ToolEnv) -> dict:
    months = inp["months"]
    if not 1 <= months <= 24:
        raise ToolError(BAD_INPUT)
    L = _load(env)
    n = _numbers(L)
    start = month_add(env.today.replace(day=1), -(months - 1))
    out = []
    for item in L.items:
        if item.kind != "income" or item.status == "closed":
            continue
        d = L.details[item.id]
        usual = _int(d.get("usual_day"))
        account_id, match = _source(L, item, "lands_in_id")
        arrived: dict[str, tuple[int, date | None]] = {}
        if account_id and match:
            for t in env.db.scalars(_matching(account_id, match, True)
                                    .where(Transaction.posted_at >= start - timedelta(days=WV.EARLY_DAYS))
                                    .order_by(Transaction.posted_at)):
                key = _month_of(t.posted_at, usual)
                cents, on = arrived.get(key, (0, None))
                arrived[key] = (cents + t.amount_cents, on or t.posted_at)
        rows, missed = [], []
        for i in range(months):
            m = month_add(start, i)
            key = m.strftime("%Y-%m")
            cents, on = arrived.get(key, (0, None))
            rows.append({"month": key, "arrived_cents": cents, "arrived_on": on.isoformat() if on else None})
            if (account_id and match and usual and _freq(d) == "monthly" and cents == 0
                    and due_date(m.year, m.month, usual) + timedelta(days=WV.GRACE_DAYS) <= env.today):
                missed.append(key)
        src = d.get("source") if d.get("source") in V.INCOME_SOURCES else "other"
        out.append({"source": src, "n": n[item.id], "owner": Ref("owner", item.owner),
                    "expected_cents": _int(d.get("amount_cents")), "usual_day": usual,
                    "lands_in": Ref("account", account_id) if account_id else None, "months": rows, "missed": missed})
    return {"items": out[:40]}


@register("premiums")
def premiums(inp: dict, env: ToolEnv) -> dict:
    L = _load(env)
    n = _numbers(L)
    missed = {f.item_id for f in env.db.scalars(select(Flag).where(Flag.check == "premium",
                                                                   Flag.status.in_(("open", "checking"))))}
    out = []
    for item in L.items:
        t = _type(L, item)
        if item.kind != "insurance" or item.status == "closed" or t not in V.INSURANCE_TYPES:
            continue
        d = L.details[item.id]
        paid, paid_income = _via(L, d.get("paid_from_id"))
        account_id, match = _source(L, item, "paid_from_id")
        last = None
        if account_id and match:
            last = env.db.scalar(_matching(account_id, match, False)
                                 .order_by(Transaction.posted_at.desc(), Transaction.id.desc()).limit(1))
        out.append({"type": t, "n": n[item.id], "owner": Ref("owner", item.owner),
                    "premium_cents": _int(d.get("amount_cents")), "frequency": _freq(d), "paid_from": paid,
                    "paid_from_income": paid_income, "last_paid_on": last.posted_at.isoformat() if last else None,
                    "last_paid_cents": abs(last.amount_cents) if last else None, "missed": item.id in missed,
                    "renewal_month": _renewal(d)})
    return {"items": out[:40]}


def flag_day(posted: date | None, due_on: date | None, made: datetime) -> date:
    """The day a flag is about (Ask about this P16): its transaction's posted day, else the day it was due, else the
    household day it was made. The flags tool and the about line both use it, so they agree."""
    return posted or due_on or made.astimezone(clock.household_tz()).date()


@register("flags")
def flags(inp: dict, env: ToolEnv) -> dict:
    q = select(Flag).order_by(Flag.created_at.desc(), Flag.id.desc()).limit(200)
    if not inp["include_done"]:
        q = q.where(Flag.status.in_(("open", "checking")))
    out = []
    for f in env.db.scalars(q):
        facts = json.loads(f.facts or "{}")
        t = env.db.get(Transaction, f.transaction_id) if f.transaction_id else None
        when = flag_day(t.posted_at if t else None, f.due_on, f.created_at)
        p = payee(t.raw_description, t.merchant) if t else None
        amount = facts.get("amount_cents")
        amount = abs(amount) if isinstance(amount, int) else (abs(t.amount_cents) if t else None)
        account_id = f.account_id or (t.account_id if t else None)
        out.append({"check": f.check, "severity": f.severity, "status": STATUS[f.status], "amount_cents": amount,
                    "date": when.isoformat(), "account": Ref("account", account_id) if account_id else None,
                    "payee": Ref("payee", p.key) if p and p.key else None})
    return {"flags": out}
