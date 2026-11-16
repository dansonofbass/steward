"""Money in and money out by calendar month (spec 5), with each month's categories, in one grouped query."""
from __future__ import annotations

from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from steward.db.models import Account, Transaction
from steward.services.vault_flows import month_add, personal_amount, personal_clauses


def cashflow(db: Session, today: date, months: int, *, leave_out_transfers: bool = False) -> list[dict]:
    """`leave_out_transfers` also drops rows only categorized as a transfer (a card payment the feed didn't pair),
    as Care's spending does; the Cash flow screen keeps them."""
    first = today.replace(day=1)
    start, end = month_add(first, -(months - 1)), month_add(first, 1)
    month = func.strftime("%Y-%m", Transaction.posted_at)
    pa = personal_amount()
    extra = (Transaction.category != "transfer",) if leave_out_transfers else ()
    rows = db.execute(
        select(month, Transaction.category,
               func.coalesce(func.sum(case((Transaction.amount_cents > 0, pa), else_=0)), 0),
               func.coalesce(func.sum(case((Transaction.amount_cents < 0, -pa), else_=0)), 0))
        .join(Account, Account.id == Transaction.account_id)
        .where(Transaction.posted_at >= start, Transaction.posted_at < end, *personal_clauses(), *extra)
        .group_by(month, Transaction.category)).all()
    by_month: dict[str, dict] = {month_add(start, i).strftime("%Y-%m"): {"in": 0, "out": 0, "categories": []}
                                 for i in range(months)}
    for m, category, money_in, money_out in rows:
        if not money_in and not money_out:
            continue
        e = by_month[m]
        e["in"] += int(money_in)
        e["out"] += int(money_out)
        e["categories"].append({"category": category, "in_cents": int(money_in), "out_cents": int(money_out)})
    out = []
    for m, e in by_month.items():
        e["categories"].sort(key=lambda c: (-c["out_cents"], -c["in_cents"], c["category"]))
        out.append({"month": m, "in_cents": e["in"], "out_cents": e["out"], "net_cents": e["in"] - e["out"],
                    "categories": e["categories"]})
    return out
