"""Tools in every book (spec 4.2). Each reads through the services the screens use; a household book's cash flow is
Spending's own (services.spending.flow_months). Amounts are cents; people, accounts and payees are Refs the executor
turns into aliases."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from sqlalchemy import case, func, select

from steward.advisor.tools import Ref, ToolEnv, ToolError, register
from steward.advisor.tools.recurring import find_recurring
from steward.books.people import household_people
from steward.db.models import (
    LIABILITY_TYPES, Account, AccountType, AdvisorAlias, BalanceSnapshot, InventoryItem, Source, Transaction,
    active_children,
)
from steward import clock
from steward.services import networth
from steward.services.accounts import debt_rate_bp, import_kinds, latest_balance
from steward.services.asset_classes import BUILTIN, TARGET_DATE, latest_holdings, overrides
from steward.services.plan_inputs import latest_facts
from steward.services.spending import flow_months
from steward.services.vault_flows import (
    BUSINESS_TYPES, CASH_FLOW_TYPES, account_clauses, business_clauses, month_add, personal_amount, personal_clauses,
)

BAD_INPUT = "That input wasn't understood."
TAX = {"unknown": "none", "checking": "none", "savings": "none", "credit": "none", "brokerage_taxable": "taxable",
       "k401": "tax_deferred", "traditional_ira": "tax_deferred", "roth_ira": "tax_free", "hsa": "tax_free",
       "plan529": "tax_free", "mortgage": "none", "property": "none", "loan": "none", "business_checking": "none",
       "business_credit": "none", "vehicle": "none"}
DEBT_KIND = {AccountType.credit: "credit_card", AccountType.mortgage: "mortgage", AccountType.loan: "loan",
             AccountType.business_credit: "business_credit"}
SYMBOL = re.compile(r"^[A-Z]{1,5}$")   # plan ruling 25: letters only, anything else is sent as null
MONTH = func.strftime("%Y-%m", Transaction.posted_at)
MONEY_IN = func.coalesce(func.sum(case((Transaction.amount_cents > 0, Transaction.amount_cents), else_=0)), 0)
MONEY_OUT = func.coalesce(func.sum(case((Transaction.amount_cents < 0, -Transaction.amount_cents), else_=0)), 0)


def age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def clauses(kind: str) -> tuple:
    """Which transactions count as the book's own money in and out: the Cash flow page's in a household book; every
    cash account but business ones in a parent book (its owners aren't the household's)."""
    if kind == "household":
        return personal_clauses()
    return (Account.type.not_in(BUSINESS_TYPES), Account.type.in_(CASH_FLOW_TYPES), Transaction.is_business.is_(False),
            Transaction.is_transfer.is_(False))


def _months(n: object) -> int:
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 60:
        raise ToolError(BAD_INPUT)
    return n


def account_of(env: ToolEnv, alias: object) -> int | None:
    """An account alias from Claude, back to its id (Ask about this P15), as merchant_detail turns payee aliases back.
    None when there is none; an alias this book never gave to an account is the input error."""
    if alias is None:
        return None
    target = env.db.scalar(select(AdvisorAlias.target).where(AdvisorAlias.kind == "account", AdvisorAlias.alias == alias))
    if target is None or not target.isdigit() or env.db.scalar(select(Account.id).where(Account.id == int(target))) is None:
        raise ToolError(BAD_INPUT)
    return int(target)


def _type_totals(d: dict[str, int]) -> list[dict]:
    return [{"account_type": k, "balance_cents": v} for k, v in sorted(d.items())]


def _dob(facts, key: str) -> date | None:
    try:
        return date.fromisoformat(facts[key].value) if key in facts else None
    except ValueError:
        return None


@register("book_summary")
def book_summary(inp: dict, env: ToolEnv) -> dict:
    db, t = env.db, env.today
    people: list[dict] = []
    state = filing = None
    if env.book.kind == "household":
        facts = latest_facts(db)
        jr, spouse = household_people(env.people)
        for key, who in (("jr", jr), ("spouse", spouse)):
            if key == "spouse" and spouse is None and "spouse.dob" not in facts:
                continue                        # a household of one: Ask never hears of a second person
            dob = _dob(facts, f"{key}.dob")
            people.append({"alias": Ref("owner", key), "age": age(dob, t) if dob else None, "role": "owner",
                           "is_asker": who is not None and who.id == env.user_id})
        for key in ("joint", "business"):
            people.append({"alias": Ref("owner", key), "age": None, "role": key, "is_asker": False})
        for c in db.scalars(active_children()):
            people.append({"alias": Ref("child", c.id), "age": max(0, t.year - c.birth_year), "role": "child",
                           "is_asker": False})
        others = [p for p in env.people if p not in (jr, spouse)]
        state = facts["state"].value if "state" in facts else None
        filing = facts["filing_status"].value if "filing_status" in facts else None
    else:
        for o in env.book.owner_names:
            people.append({"alias": Ref("owner", o.key), "age": None,
                           "role": o.key if o.key in ("joint", "business") else "owner", "is_asker": False})
        others = list(env.people)
    for p in others:
        people.append({"alias": Ref("user", p.id), "age": None, "role": "member", "is_asker": p.id == env.user_id})
    return {"book_kind": env.book.kind, "today": t.isoformat(), "asker": Ref("user", env.user_id), "people": people[:40],
            "state": state, "filing_status": filing, "net_worth_cents": networth.net_worth_on(db, t),
            "totals_by_account_type": _type_totals(networth.by_type_on(db, t))}


def _arrives(a: Account, items: dict[int, InventoryItem], imported: dict[int, str]) -> str:
    """feed, statement, file or manual. An account that isn't a bank feed says how its newest import came in, a PDF
    statement or a file (CSV or OFX), so Claude never hears an imported account is typed in (install gate INS-17). Only
    the kind: never the file's name, date or rows (P12)."""
    item = items.get(a.id)
    if item is not None and item.data_source in ("feed", "statement", "manual"):
        return item.data_source
    if a.source == Source.simplefin:
        return "feed"
    return imported.get(a.id, "manual")


def _behind(a: Account, today: date) -> bool:
    if a.source != Source.simplefin:
        return False
    inst = a.institution
    if inst.last_error:
        return True
    return inst.last_sync_at is None or (today - inst.last_sync_at.astimezone(clock.household_tz()).date()).days > 2


def _linked(env: ToolEnv) -> dict[int, InventoryItem]:
    return {i.account_id: i for i in env.db.scalars(select(InventoryItem).where(InventoryItem.account_id.is_not(None)))}


@register("accounts")
def accounts(inp: dict, env: ToolEnv) -> dict:
    q = select(Account).order_by(Account.id)
    if not inp["include_closed"]:
        q = q.where(Account.is_active.is_(True))
    items, imported = _linked(env), import_kinds(env.db)
    out = []
    for a in env.db.scalars(q):
        lb = latest_balance(env.db, a.id)
        out.append({"account": Ref("account", a.id), "account_type": a.type.value, "tax_treatment": TAX[a.type.value],
                    "owner": Ref("owner", a.owner), "balance_cents": lb[1] if lb else None,
                    "as_of": lb[0].isoformat() if lb else None, "arrives": _arrives(a, items, imported),
                    "sync_behind": _behind(a, env.today), "active": a.is_active})
    return {"accounts": out[:300]}


@register("balance_history")
def balance_history(inp: dict, env: ToolEnv) -> dict:
    """Month-end net worth as networth.net_worth_on computes it (each active account's latest balance on or before the
    day), in one pass over the snapshots instead of a query per month. With `account`, that account's own month-end
    balance by the same rule, whether or not it is active (P15)."""
    n = _months(inp["months"])
    aid = account_of(env, inp.get("account"))
    first = env.today.replace(day=1)
    ends = []
    for i in range(n - 1, -1, -1):
        start = month_add(first, -i)
        ends.append((start.strftime("%Y-%m"), min(env.today, month_add(start, 1) - timedelta(days=1))))
    types = dict(env.db.execute(select(Account.id, Account.type).where(Account.is_active.is_(True))).all())
    ids = list(types) if aid is None else sorted(set(types) | {aid})
    rows = env.db.execute(select(BalanceSnapshot.account_id, BalanceSnapshot.as_of, BalanceSnapshot.balance_cents)
                          .where(BalanceSnapshot.account_id.in_(ids), BalanceSnapshot.as_of <= ends[-1][1])
                          .order_by(BalanceSnapshot.as_of, BalanceSnapshot.account_id)).all()
    latest: dict[int, int] = {}
    out, i = [], 0
    for month, end in ends:
        while i < len(rows) and rows[i][1] <= end:
            latest[rows[i][0]] = rows[i][2]
            i += 1
        worth = {a: c for a, c in latest.items() if a in types}
        by_type: dict[str, int] = {}
        for account_id, cents in worth.items():
            by_type[types[account_id].value] = by_type.get(types[account_id].value, 0) + cents
        out.append({"month": month, "net_worth_cents": sum(worth.values()),
                    "by_account_type": _type_totals(by_type) if inp["by_account_type"] else None,
                    "account_cents": latest.get(aid) if aid is not None else None})
    return {"months": out}


def _window(today: date, n: int) -> tuple[date, date]:
    first = today.replace(day=1)
    return month_add(first, -(n - 1)), month_add(first, 1)


def _monthly_where(env: ToolEnv, n: int, where: tuple) -> list[dict]:
    start, end = _window(env.today, n)
    rows = env.db.execute(select(MONTH, Transaction.category, MONEY_IN, MONEY_OUT)
                          .join(Account, Account.id == Transaction.account_id)
                          .where(Transaction.posted_at >= start, Transaction.posted_at < end, *where)
                          .group_by(MONTH, Transaction.category)).all()
    months = {month_add(start, i).strftime("%Y-%m"): {"in": 0, "out": 0, "cats": []} for i in range(n)}
    for m, cat, i, o in rows:
        months[m]["in"] += int(i)
        months[m]["out"] += int(o)
        months[m]["cats"].append({"category": cat, "in_cents": int(i), "out_cents": int(o)})
    return [{"month": m, "in_cents": e["in"], "out_cents": e["out"], "net_cents": e["in"] - e["out"],
             "categories": sorted(e["cats"], key=lambda c: (-c["out_cents"], -c["in_cents"], c["category"]))}
            for m, e in months.items()]


def _monthly(env: ToolEnv, n: int) -> list[dict]:
    """A household book's months are Spending's own (spending.flow_months: Home's figure and Spending's head, to the
    cent); a parent book, which has no Spending, counts its cash accounts' rows."""
    if env.book.kind == "household":
        return flow_months(env.db, env.today, n)
    return _monthly_where(env, n, clauses(env.book.kind))


def _grouped(env: ToolEnv, n: int, column, where: tuple) -> dict[str, dict]:
    start, end = _window(env.today, n)
    out: dict[str, dict] = {}
    for m, key, i, o in env.db.execute(select(MONTH, column, MONEY_IN, MONEY_OUT)
                                       .join(Account, Account.id == Transaction.account_id)
                                       .where(Transaction.posted_at >= start, Transaction.posted_at < end, *where)
                                       .group_by(MONTH, column)):
        out.setdefault(m, {})[key] = (int(i), int(o))
    return out


def _in_out(share) -> tuple:
    """Money in and money out of a share of each row (a row's sign decides which), as MONEY_IN and MONEY_OUT are."""
    return (func.coalesce(func.sum(case((Transaction.amount_cents > 0, share), else_=0)), 0),
            func.coalesce(func.sum(case((Transaction.amount_cents < 0, -share), else_=0)), 0))


def _business(env: ToolEnv, n: int) -> dict[str, tuple[int, int]]:
    """The business share of every row that has one: all of an all-business row, the rest of a split once
    Spending's personal share is taken (personal_amount; Argon follow-up 4), over the personal side's rows
    (business_clauses: no transfers, reimbursables, repayments or investment accounts)."""
    start, end = _window(env.today, n)
    rows = env.db.execute(select(MONTH, *_in_out(Transaction.amount_cents - personal_amount()))
                          .join(Account, Account.id == Transaction.account_id)
                          .where(Transaction.posted_at >= start, Transaction.posted_at < end, *business_clauses())
                          .group_by(MONTH))
    return {m: (int(i), int(o)) for m, i, o in rows}


def _account_shares(env: ToolEnv, n: int, where: tuple) -> dict[str, dict[bool, tuple[int, int]]]:
    """One account's rows split by share: each row's personal share (personal_amount) under False and the rest under
    True, so a 50% split counts half on each side and the two always add up to the account's totals."""
    start, end = _window(env.today, n)
    pa = personal_amount()
    rows = env.db.execute(select(MONTH, *_in_out(pa), *_in_out(Transaction.amount_cents - pa))
                          .join(Account, Account.id == Transaction.account_id)
                          .where(Transaction.posted_at >= start, Transaction.posted_at < end, *where)
                          .group_by(MONTH))
    return {m: {False: (int(pi), int(po)), True: (int(bi), int(bo))} for m, pi, po, bi, bo in rows}


@register("cash_flow")
def cash_flow(inp: dict, env: ToolEnv) -> dict:
    n, by = _months(inp["months"]), inp["by"]
    aid = account_of(env, inp.get("account"))
    where = clauses(env.book.kind) if aid is None else account_clauses(aid)
    owners = _grouped(env, n, Account.owner, where) if by == "owner" else {}
    if by != "business":
        business: dict = {}
    elif aid is None:
        business = _business(env, n)
    else:                                   # that account's rows, each split into its personal and business shares
        business = _account_shares(env, n, where)
    out = []
    for r in (_monthly(env, n) if aid is None else _monthly_where(env, n, where)):
        if by == "category":
            groups = [{"category": c["category"], "owner": None, "business": None, "in_cents": c["in_cents"],
                       "out_cents": c["out_cents"]} for c in r["categories"]][:40]
        elif by == "owner":
            groups = [{"category": None, "owner": Ref("owner", k), "business": None, "in_cents": v[0], "out_cents": v[1]}
                      for k, v in sorted(owners.get(r["month"], {}).items())]
        elif by == "business":
            if aid is None:
                no, yes = (r["in_cents"], r["out_cents"]), business.get(r["month"], (0, 0))
            else:
                split = business.get(r["month"], {})
                no, yes = split.get(False, (0, 0)), split.get(True, (0, 0))
            groups = [{"category": None, "owner": None, "business": False, "in_cents": no[0], "out_cents": no[1]},
                      {"category": None, "owner": None, "business": True, "in_cents": yes[0], "out_cents": yes[1]}]
        else:
            groups = None
        out.append({"month": r["month"], "in_cents": r["in_cents"], "out_cents": r["out_cents"],
                    "net_cents": r["net_cents"], "groups": groups})
    return {"months": out}


def _spending(env: ToolEnv, start: date, end: date) -> dict:
    rows = env.db.execute(select(Transaction.category, func.sum(-Transaction.amount_cents), func.count())
                          .join(Account, Account.id == Transaction.account_id)
                          .where(Transaction.posted_at >= start, Transaction.posted_at <= end,
                                 Transaction.amount_cents < 0, *clauses(env.book.kind))
                          .group_by(Transaction.category)).all()
    cats = sorted(({"category": c, "out_cents": int(s), "count": int(k)} for c, s, k in rows),
                  key=lambda r: (-r["out_cents"], r["category"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "total_out_cents": sum(r["out_cents"] for r in cats),
            "categories": cats[:30]}


@register("spending_by_category")
def spending_by_category(inp: dict, env: ToolEnv) -> dict:
    try:
        start, end = date.fromisoformat(inp["start"]), date.fromisoformat(inp["end"])
    except ValueError:
        raise ToolError(BAD_INPUT) from None
    if end < start:
        raise ToolError(BAD_INPUT)
    if (end - start).days > 365:
        raise ToolError("That period is too long.")
    previous = None
    if inp["compare_previous"]:
        prev_end = start - timedelta(days=1)
        previous = _spending(env, prev_end - (end - start), prev_end)
    return {"period": _spending(env, start, end), "previous": previous}


@register("recurring")
def recurring(inp: dict, env: ToolEnv) -> dict:
    return {"items": [{**i, "payee": Ref("payee", i["payee"])} for i in find_recurring(env.db, env.today)][:150]}


@register("holdings")
def holdings(inp: dict, env: ToolEnv) -> dict:
    ovr = overrides(env.db)
    rows, totals = [], {}
    for account_id, hs in sorted(latest_holdings(env.db).items()):
        for h in hs:
            s = (h.symbol or "").strip().upper()
            symbol = s if SYMBOL.fullmatch(s) else None
            cls = (ovr.get(s) or BUILTIN.get(s) or ("target_date" if s in TARGET_DATE else "other")) if symbol else "other"
            rows.append({"symbol": symbol, "asset_class": cls, "account": Ref("account", account_id),
                         "value_cents": h.market_value_cents, "cost_basis_cents": h.cost_basis_cents,
                         "as_of": h.as_of.isoformat()})
            totals[cls] = totals.get(cls, 0) + h.market_value_cents
    return {"holdings": rows[:500],
            "totals_by_asset_class": [{"asset_class": k, "value_cents": v} for k, v in sorted(totals.items())]}


@register("debts")
def debts(inp: dict, env: ToolEnv) -> dict:
    facts = latest_facts(env.db) if env.book.kind == "household" else {}
    details = {a: json.loads(i.details or "{}") for a, i in _linked(env).items()}
    out = []
    for a in env.db.scalars(select(Account).where(Account.is_active.is_(True), Account.type.in_(LIABILITY_TYPES))
                            .order_by(Account.id)):
        lb = latest_balance(env.db, a.id)
        kind = DEBT_KIND[a.type]
        if kind == "mortgage" and details.get(a.id, {}).get("type") == "loan":
            kind = "loan"
        rate = debt_rate_bp(a, facts)            # the account's own rate first, then the mortgage fact (minor a)
        payment = payoff = None
        if kind == "mortgage" and facts:
            payment = int(facts["mortgage.payment_cents"].value) if "mortgage.payment_cents" in facts else None
            payoff = facts["mortgage.payoff_date"].value[:7] if "mortgage.payoff_date" in facts else None
        out.append({"account": Ref("account", a.id), "kind": kind, "balance_cents": abs(lb[1]) if lb else 0,
                    "rate_bp": rate, "payment_cents": payment, "payoff_month": payoff})
    return {"debts": out}
