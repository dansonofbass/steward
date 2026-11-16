"""What went into retirement accounts this year, against the year's limits (investment views spec, Contributions and
limits).

A row in the account counts by what it is: money out that is a transfer only nets "You put in"; a rollover (its
description says so, or it's a transfer from another retirement account or HSA) is shown but never counts toward a
limit; the employer's deposits ("MATCH", "EMPLOYER") are the match; a transfer in, or a description that says
CONTRIBUTION or DEFERRAL, is yours. Person 1's own 401(k) falls back on the pay facts when it shows none of their deferrals or the
match this year: the payroll figure for the year to date, else salary times the deferral percent for the months gone,
labelled as estimated; the match the same way. The first HSA falls back on the payroll HSA figure. Limits come from
steward.services.limits, the tables Next dollar reads."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from steward.db.models import RETIREMENT_TYPES, Account, AccountType, Child, Fact, Owner, Transaction
from steward.services import limits as L
from steward.services.contributions import TAX_ADVANTAGED
from steward.services.plan_inputs import latest_facts, owner_names

ROLLOVER = re.compile(r"ROLL\s*-?\s*OVER")
EMPLOYER = re.compile(r"\bMATCH|EMPLOYER")
YOURS = re.compile(r"CONTRIBUT|DEFERRAL")
PAYROLL_K401, PAYROLL_HSA = "jr.payroll_k401_cents", "jr.payroll_hsa_cents"
LABELS = {"k401": "401(k)", "ira": "IRA", "hsa": "HSA"}


@dataclass(frozen=True)
class Deposit:
    day: date
    cents: int      # signed: money out is negative
    kind: str       # you | match | rollover | out


def deposits(db: Session, account_ids: list[int], start: date, end: date) -> list[Deposit]:
    """The rows that are money put in or taken out, over [start, end), oldest first. Dividends, trades and fees are
    not."""
    if not account_ids:
        return []
    peer, peer_account = aliased(Transaction), aliased(Account)
    rows = db.execute(
        select(Transaction.posted_at, Transaction.amount_cents, Transaction.raw_description, Transaction.is_transfer,
               peer_account.type)
        .outerjoin(peer, peer.id == Transaction.transfer_peer_id)
        .outerjoin(peer_account, peer_account.id == peer.account_id)
        .where(Transaction.account_id.in_(account_ids), Transaction.posted_at >= start, Transaction.posted_at < end)
        .order_by(Transaction.posted_at, Transaction.id)).all()
    out: list[Deposit] = []
    for day, cents, raw, is_transfer, peer_type in rows:
        text = " ".join((raw or "").upper().split())
        if cents < 0:
            if is_transfer:
                out.append(Deposit(day, cents, "out"))
        elif ROLLOVER.search(text) or (is_transfer and peer_type in TAX_ADVANTAGED):
            out.append(Deposit(day, cents, "rollover"))
        elif EMPLOYER.search(text):
            out.append(Deposit(day, cents, "match"))
        elif is_transfer or YOURS.search(text):
            out.append(Deposit(day, cents, "you"))
    return out


@dataclass(frozen=True)
class Contributed:
    you_cents: int
    you_from: str          # deposits | payroll | estimate | none
    match_cents: int
    match_from: str        # deposits | estimate | none
    rollover_cents: int
    out_cents: int         # money taken out, as a positive amount
    through: date          # the day the figures run to: today, a payroll figure's date, or an estimate's month end

    @property
    def net_cents(self) -> int:
        return self.you_cents + self.match_cents + self.rollover_cents - self.out_cents

    @property
    def estimated(self) -> bool:
        return self.you_from == "estimate" or self.match_from == "estimate"


def _int(facts: dict[str, Fact], key: str) -> int | None:
    f = facts.get(key)
    try:
        return int(f.value) if f is not None else None
    except ValueError:
        return None


def _this_years(facts: dict[str, Fact], key: str, year: int) -> Fact | None:
    """A payroll figure counts only in the year it is dated (Next dollar's rule)."""
    f = facts.get(key)
    return f if f is not None and f.as_of.year == year else None


def _days(year: int) -> int:
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


def _through_days(through: date, year: int) -> int:
    return max(1, min(_days(year), (through - date(year, 1, 1)).days + 1))


def employer_401k(db: Session) -> Account | None:
    """Person 1's own 401(k), where their W-2 deferrals go (Next dollar's reading): the first active one they own."""
    return db.scalar(select(Account).where(Account.is_active.is_(True), Account.type == AccountType.k401,
                                           Account.owner == Owner.jr.value).order_by(Account.id).limit(1))


def _first_hsa(db: Session) -> Account | None:
    return db.scalar(select(Account).where(Account.is_active.is_(True), Account.type == AccountType.hsa)
                     .order_by(Account.id).limit(1))


def _from_pay(facts: dict[str, Fact], today: date, rollover: int, out: int) -> Contributed:
    year = today.year
    salary, pct = _int(facts, "jr.salary_cents"), _int(facts, "jr.k401_pct_bp")
    rate, cap = _int(facts, "employer.match_rate_bp"), _int(facts, "employer.match_cap_bp")
    f = _this_years(facts, PAYROLL_K401, year)
    if f is not None:
        you, you_from, through = int(f.value), "payroll", f.as_of
    elif salary is not None and pct is not None:
        months = today.month - 1
        you, you_from = salary * pct // 10_000 * months // 12, "estimate"
        through = date(year, today.month, 1) - timedelta(days=1) if months else date(year, 1, 1)
    else:
        return Contributed(0, "none", 0, "none", rollover, out, today)
    match = 0
    if salary is not None and rate is not None and cap is not None:
        earned = salary * _through_days(through, year) // _days(year)
        match = min(you, earned * cap // 10_000) * rate // 10_000
    return Contributed(you, you_from, match, "estimate" if match else "none", rollover, out, through)


def this_year(db: Session, account: Account, today: date, facts: dict[str, Fact] | None = None) -> Contributed:
    facts = latest_facts(db) if facts is None else facts
    ds = deposits(db, [account.id], date(today.year, 1, 1), today + timedelta(days=1))
    you = sum(d.cents for d in ds if d.kind == "you")
    match = sum(d.cents for d in ds if d.kind == "match")
    rollover = sum(d.cents for d in ds if d.kind == "rollover")
    out = -sum(d.cents for d in ds if d.kind == "out")
    if you or match:
        return Contributed(you, "deposits", match, "deposits" if match else "none", rollover, out, today)
    if account.type == AccountType.k401 and (emp := employer_401k(db)) is not None and emp.id == account.id:
        return _from_pay(facts, today, rollover, out)
    if account.type == AccountType.hsa and (first := _first_hsa(db)) is not None and first.id == account.id:
        f = _this_years(facts, PAYROLL_HSA, today.year)
        if f is not None:
            return Contributed(int(f.value), "payroll", 0, "none", rollover, out, f.as_of)
    return Contributed(0, "none", 0, "none", rollover, out, today)


@dataclass(frozen=True)
class LimitLine:
    kind: str                  # k401 | ira | hsa
    owner: str                 # jr | spouse | household
    name: str                  # the person's name; "" for the household
    year: int
    limit_cents: int | None    # None: this year's limits aren't in Steward yet
    in_cents: int
    on_pace_cents: int
    short_cents: int
    raise_pct: int | None
    maxed: bool
    estimated: bool
    account_ids: tuple[int, ...]


def _pace(cents: int, through: date, year: int) -> int:
    """What the year comes to at this rate: cents x days in the year / days so far, rounded half up."""
    days, so_far = _days(year), _through_days(through, year)
    return (cents * days * 2 + so_far) // (2 * so_far)


def _raise(short: int, salary: int | None, through: date, year: int) -> int | None:
    """The whole percent of salary, over the days left, that would cover what's short."""
    if short <= 0 or not salary:
        return None
    days = _days(year)
    left = days - _through_days(through, year)
    if left <= 0:
        return None
    n = -(-short * 100 * days // (salary * left))
    return n if 1 <= n <= 100 else None


def _line(kind: str, owner: str, name: str, accounts: list[Account], per: dict[int, Contributed], year: int,
          limit: int | None, salary: int | None) -> LimitLine:
    cs = [per[a.id] for a in accounts]

    def counted(c: Contributed) -> int:   # the HSA limit counts the employer's deposits; a 401(k)'s and an IRA's don't
        return c.you_cents + (c.match_cents if kind == "hsa" else 0)

    in_cents = sum(counted(c) for c in cs)
    pace = sum(_pace(counted(c), c.through, year) for c in cs)
    short = max(0, limit - pace) if limit is not None else 0
    maxed = limit is not None and in_cents >= limit
    estimated = any(c.you_from == "estimate" or (kind == "hsa" and c.match_from == "estimate") for c in cs)
    raise_pct = _raise(short, salary, min(c.through for c in cs), year) if limit is not None and not maxed else None
    return LimitLine(kind, owner, name, year, limit, in_cents, pace, short, raise_pct, maxed, estimated,
                     tuple(a.id for a in accounts))


def _age(facts: dict[str, Fact], person: str, year: int) -> int:
    f = facts.get(f"{person}.dob")
    try:
        return year - date.fromisoformat(f.value).year if f is not None else 0
    except ValueError:
        return 0


def limit_lines(db: Session, today: date) -> list[LimitLine]:
    facts = latest_facts(db)
    names = owner_names(db)
    year = today.year
    have = L.have_year(year)
    active = list(db.scalars(select(Account).where(Account.is_active.is_(True), Account.type.in_(RETIREMENT_TYPES))
                             .order_by(Account.id)))
    per = {a.id: this_year(db, a, today, facts) for a in active}
    ages = {p: _age(facts, p, year) for p in ("jr", "spouse")}
    salary = _int(facts, "jr.salary_cents")
    lines: list[LimitLine] = []
    for person in ("jr", "spouse"):
        mine = [a for a in active if a.owner == person]
        k401 = [a for a in mine if a.type == AccountType.k401]
        if k401:
            lines.append(_line("k401", person, names[person], k401, per, year,
                               L.k401_cents(ages[person], year) if have else None, salary if person == "jr" else None))
        iras = [a for a in mine if a.type in (AccountType.roth_ira, AccountType.traditional_ira)]
        if iras:
            lines.append(_line("ira", person, names[person], iras, per, year,
                               L.ira_cents(ages[person], year) if have else None, None))
    hsas = [a for a in active if a.type == AccountType.hsa]
    if hsas:
        filing = facts.get("filing_status")
        mfj = filing is not None and filing.value == "mfj"
        family = mfj or db.scalar(select(Child.id).where(Child.removed_at.is_(None)).limit(1)) is not None   # Next dollar's rule
        ages_hsa = (ages["jr"], ages["spouse"]) if mfj else (ages["jr"],)
        lines.append(_line("hsa", "household", "", hsas, per, year, L.hsa_cents(family, ages_hsa, year) if have else None, None))
    return lines


def line_for(lines: list[LimitLine], account_id: int) -> LimitLine | None:
    return next((x for x in lines if account_id in x.account_ids), None)


def line_out(x: LimitLine) -> dict:
    return {"kind": x.kind, "owner": x.owner, "name": x.name, "label": LABELS[x.kind], "year": x.year,
            "limit_cents": x.limit_cents, "in_cents": x.in_cents, "on_pace_cents": x.on_pace_cents,
            "short_cents": x.short_cents, "raise_pct": x.raise_pct, "maxed": x.maxed, "estimated": x.estimated}


def contributed_out(c: Contributed) -> dict:
    return {"you_cents": c.you_cents, "you_from": c.you_from, "match_cents": c.match_cents, "match_from": c.match_from,
            "rollover_cents": c.rollover_cents, "out_cents": c.out_cents}


def limits_out(db: Session, today: date) -> dict:
    return {"year": today.year, "missing": not L.have_year(today.year),
            "lines": [line_out(x) for x in limit_lines(db, today)]}
