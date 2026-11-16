"""Recurring payments and deposits (spec 4.2), found from the last 13 months: transactions grouped by payee and
direction, kept when their spacing is steady (weekly, every 2 weeks, monthly or yearly)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, Transaction
from steward.watch.payees import payee

CADENCES = (("weekly", 5, 9, 3), ("every_2_weeks", 12, 16, 4), ("monthly", 26, 35, 7), ("yearly", 350, 380, 30))


def find_recurring(db: Session, today: date) -> list[dict]:
    rows = db.execute(select(Transaction.posted_at, Transaction.amount_cents, Transaction.raw_description,
                             Transaction.merchant, Transaction.category)
                      .join(Account, Account.id == Transaction.account_id)
                      .where(Transaction.posted_at >= today - timedelta(days=400), Transaction.is_transfer.is_(False))
                      .order_by(Transaction.posted_at)).all()
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for posted, cents, raw, merchant, category in rows:
        p = payee(raw, merchant)
        if p.key and cents:
            groups[(p.key, "in" if cents > 0 else "out")].append((posted, abs(cents), category))
    out = []
    for (key, direction), items in groups.items():
        dates = sorted({d for d, _, _ in items})
        if len(dates) < 2:
            continue
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        typical = median(gaps)
        for cadence, lo, hi, grace in CADENCES:
            if not lo <= typical <= hi:
                continue
            steady = sum(lo <= g <= hi for g in gaps) / len(gaps)
            if (cadence != "yearly" and len(dates) < 3) or steady < 0.6:
                break
            amounts = [c for _, c, _ in items]
            out.append({"payee": key, "direction": direction,
                        "category": Counter(c for _, _, c in items).most_common(1)[0][0],
                        "cadence": cadence, "low_cents": min(amounts), "high_cents": max(amounts),
                        "usual_day": int(median(d.day for d in dates)) if cadence == "monthly" else None,
                        "last_seen": dates[-1].isoformat(),
                        "late": today > dates[-1] + timedelta(days=int(typical) + grace)})
            break
    return sorted(out, key=lambda r: (r["direction"], -r["high_cents"], r["payee"]))
