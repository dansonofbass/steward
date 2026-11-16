"""The transaction checks (spec 4.1; watching decisions 1-3; plan rulings 1, 2, 12, 14-16). Pure functions over plain
values: run.py hands them a whole book at once, tests hand them fixtures. History is indexed once per run (by payee,
by category and month, cash by month), so 10,000 transactions check well inside spec 12's 2 s."""
from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from steward.inventory.present import mask_numbers, usd
from steward.watch import vocab as V
from steward.watch.payees import Payee, is_cash, payee, scam_kind

Month = tuple[int, int]


@dataclass(frozen=True)
class Txn:
    id: int
    account_id: int
    posted_at: date
    amount_cents: int
    raw: str
    merchant: str | None = None
    category: str = "uncategorized"
    is_transfer: bool = False
    paired: bool = False          # a transfer paired with another of the book's own accounts

    @property
    def out(self) -> bool:
        return self.amount_cents < 0

    @property
    def cents(self) -> int:
        return abs(self.amount_cents)

    @property
    def transfer(self) -> bool:
        return self.is_transfer or self.paired or self.category in ("transfer", "investment")   # money moving, not spent


@dataclass(frozen=True)
class Known:
    payee_key: str
    low_cents: int | None = None
    high_cents: int | None = None

    def covers(self, key: str, cents: int) -> bool:
        if not key or key != self.payee_key:
            return False
        if self.low_cents is None or self.high_cents is None:
            return True
        return self.low_cents <= cents <= self.high_cents


@dataclass(frozen=True)
class Rules:
    large_cents: int = V.DEFAULT_LARGE_CENTS
    cash_floor_cents: int = V.DEFAULT_CASH_FLOOR_CENTS
    known: tuple[Known, ...] = ()
    kept_pairs: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class Hit:
    check: str
    severity: str
    summary: str          # the fact after the check's name
    title: str            # the flag page's heading
    detail: str           # what "Also matched" says in brackets
    facts: dict = field(default_factory=dict)


def day(d: date) -> str:
    return f"{d:%b} {d.day}"


def _month(d: date) -> Month:
    return (d.year, d.month)


def _back(m: Month, n: int) -> Month:
    y, mo = m[0], m[1] - n
    while mo <= 0:
        y, mo = y - 1, mo + 12
    return (y, mo)


def _order(t: Txn) -> tuple[date, int]:
    return (t.posted_at, t.id)


class History:
    """Every transaction in the book, indexed once. `before` and `near` are bisects on a payee's sorted list."""

    def __init__(self, txns: list[Txn]):
        self.txns = sorted(txns, key=_order)
        self.first_day: date | None = self.txns[0].posted_at if self.txns else None
        self.payees: dict[int, Payee] = {}
        self.by_payee: dict[str, list[Txn]] = defaultdict(list)
        self.by_category: dict[tuple[str, Month], list[int]] = defaultdict(list)
        self.cash: dict[Month, list[Txn]] = defaultdict(list)
        for t in self.txns:
            p = payee(t.raw, t.merchant)
            self.payees[t.id] = p
            if p.key:
                self.by_payee[p.key].append(t)
            cash = t.out and not t.paired and is_cash(t.raw)
            if cash:
                self.cash[_month(t.posted_at)].append(t)
            elif t.out and not t.transfer and t.category not in V.NO_MEDIAN_CATEGORIES:
                self.by_category[(t.category, _month(t.posted_at))].append(t.cents)
        self._keys = {k: [_order(t) for t in v] for k, v in self.by_payee.items()}
        self._medians: dict[tuple[str, Month], int | None] = {}
        self._usual_cash: dict[Month, int | None] = {}

    def payee_of(self, t: Txn) -> Payee:
        return self.payees.get(t.id) or payee(t.raw, t.merchant)

    def before(self, key: str, t: Txn, days: int) -> list[Txn]:
        """This payee's money-out transactions in the `days` before t, oldest first; t itself and anything later
        excluded. A refund or a payment from the payee is not paying them."""
        rows, keys = self.by_payee.get(key, []), self._keys.get(key, [])
        lo = bisect.bisect_left(keys, (t.posted_at - timedelta(days=days), -1))
        hi = bisect.bisect_left(keys, _order(t))
        return [o for o in rows[lo:hi] if o.out]

    def near(self, key: str, t: Txn, days: int) -> list[Txn]:
        rows, keys = self.by_payee.get(key, []), self._keys.get(key, [])
        lo = bisect.bisect_left(keys, (t.posted_at - timedelta(days=days), -1))
        hi = bisect.bisect_right(keys, (t.posted_at + timedelta(days=days), 1 << 62))
        return [o for o in rows[lo:hi] if o.id != t.id]

    def category_median(self, category: str, month: Month) -> int | None:
        k = (category, month)
        if k not in self._medians:
            amounts = [a for n in range(1, 13) for a in self.by_category.get((category, _back(month, n)), ())]
            self._medians[k] = int(median(amounts)) if len(amounts) >= V.UNUSUAL_MIN_SAMPLES else None
        return self._medians[k]

    def usual_cash(self, month: Month) -> int | None:
        if month not in self._usual_cash:
            first = _month(self.first_day) if self.first_day else month
            months = [m for m in (_back(month, n) for n in range(1, 13)) if m >= first]
            self._usual_cash[month] = (int(median(sum(t.cents for t in self.cash.get(m, ())) for m in months))
                                       if len(months) >= V.CASH_MIN_MONTHS else None)
        return self._usual_cash[month]


def _monthly(h: History, key: str, t: Txn) -> Txn | None:
    lo, hi = V.MONTHLY_GAP
    prior = h.before(key, t, 365 + hi)
    if not prior:
        return None
    p = prior[-1]
    if not p.out or not lo <= (t.posted_at - p.posted_at).days <= hi:
        return None
    if abs(p.cents - t.cents) > max(V.MONTHLY_SLACK_CENTS, p.cents // 10):
        return None
    if any((p.posted_at - o.posted_at).days <= 365 for o in prior[:-1]):
        return None            # it was charging before
    return p


def _duplicate(h: History, key: str, t: Txn, kept: frozenset[tuple[int, int]]) -> Txn | None:
    for o in reversed(h.near(key, t, V.DUPLICATE_DAYS)):
        if (_order(o) < _order(t) and o.out and o.cents == t.cents and not o.transfer
                and (min(o.id, t.id), max(o.id, t.id)) not in kept):
            return o
    return None


def check(h: History, t: Txn, rules: Rules) -> list[Hit]:
    """Every check that fires on one transaction. Money in is never checked."""
    if not t.out:
        return []
    p = h.payee_of(t)
    amount = usd(t.cents)
    pn = mask_numbers(p.name)        # free text goes into a summary or title only through here
    base = {"amount_cents": t.cents, "payee": p.name, "payee_key": p.key, "method": p.method}
    seasoned = h.first_day is not None and (t.posted_at - h.first_day).days >= V.BASELINE_DAYS
    cash = is_cash(t.raw)
    known = any(k.covers(p.key, t.cents) for k in rules.known)
    hits: list[Hit] = []
    if not t.paired:
        s = scam_kind(t.raw)
        if s:
            title = s["title"].format(amount=amount, payee=pn)
            hits.append(Hit("scam", "urgent", title, title, s["word"], {**base, "kind": s["kind"]}))
    if not t.transfer and not known and t.cents >= rules.large_cents:
        fact = f"{amount} to {pn}"
        hits.append(Hit("large", "normal", fact, fact, f"{usd(rules.large_cents)} or more",
                        {**base, "large_cents": rules.large_cents}))
    if cash:
        if seasoned and not t.paired:
            month = _month(t.posted_at)
            usual = h.usual_cash(month)
            earlier = [o for o in h.cash.get(month, ()) if _order(o) < _order(t)]
            before = sum(o.cents for o in earlier)
            if usual == 0:        # no usual cash: only a withdrawal of the floor or more alerts, once a month
                if t.cents >= rules.cash_floor_cents and not any(o.cents >= rules.cash_floor_cents for o in earlier):
                    hits.append(Hit("cash", "normal", f"A {amount} cash withdrawal. Usually there's none.",
                                    f"{amount} cash withdrawal", "usually none",
                                    {**base, "month_cents": before + t.cents, "usual_cents": 0}))
            elif usual is not None and before <= usual < before + t.cents:
                total = before + t.cents
                hits.append(Hit("cash", "normal",
                                f"{amount} cash withdrawal brings this month to {usd(total)}, over the usual {usd(usual)}",
                                f"{amount} cash withdrawal", f"this month {usd(total)}, usually {usd(usual)}",
                                {**base, "month_cents": total, "usual_cents": usual}))
        return hits
    if t.transfer:
        return hits
    if seasoned and not known:
        if p.key and (p.method != "card" or t.cents >= V.CARD_PAYEE_MIN_CENTS) and not h.before(p.key, t, V.NEW_PAYEE_DAYS):
            urgent = p.method != "card" and t.cents > V.URGENT_PAYEE_OVER_CENTS
            fact = " ".join(w for w in (amount, V.METHOD_WORDS[p.method], "to", pn) if w)
            hits.append(Hit("payee", "urgent" if urgent else "normal", fact, fact, "not paid in the last 18 months", base))
        if t.cents > V.UNUSUAL_MIN_CENTS and t.category not in V.NO_MEDIAN_CATEGORIES:
            med = h.category_median(t.category, _month(t.posted_at))
            if med and t.cents > V.UNUSUAL_TIMES * med:
                cat = t.category.replace("_", " ")
                hits.append(Hit("unusual", "normal", f"{amount} to {pn}, more than 3 times the usual for {cat}",
                                f"{amount} to {pn}", f"3 times the usual for {cat}",
                                {**base, "category": t.category, "median_cents": med}))
        if p.key:
            prev = _monthly(h, p.key, t)
            if prev is not None:
                hits.append(Hit("monthly", "normal", f"{pn}, {amount} on {day(prev.posted_at)} and {day(t.posted_at)}",
                                f"{pn}, {amount} a month", "a second month in a row",
                                {**base, "prev_id": prev.id, "prev_posted": prev.posted_at.isoformat()}))
    if p.key:
        dup = _duplicate(h, p.key, t, rules.kept_pairs)
        if dup is not None:
            hits.append(Hit("duplicate", "normal",
                            f"{amount} at {pn} on {day(dup.posted_at)} and again on {day(t.posted_at)}",
                            f"{amount} at {pn}, twice", f"also on {day(dup.posted_at)}",
                            {**base, "other_id": dup.id, "other_posted": dup.posted_at.isoformat()}))
    return hits


def check_all(h: History, new: list[Txn], rules: Rules) -> dict[int, list[Hit]]:
    out: dict[int, list[Hit]] = {}
    for t in new:
        hits = check(h, t, rules)
        if hits:
            out[t.id] = hits
    return out


def primary(hits: list[Hit]) -> tuple[Hit, list[Hit]]:
    """Decision 3: the most serious check names the flag; urgent comes first, then RANK."""
    ordered = sorted(hits, key=lambda x: (x.severity != "urgent", V.RANK.index(x.check)))
    return ordered[0], ordered[1:]
