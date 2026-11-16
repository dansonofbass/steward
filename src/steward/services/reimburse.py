"""Reimbursable work expenses (reimbursable spec): who pays the household back, what each one owes, and marking a
charge. A charge keeps its own category and carries its payer in reimburser_id; a repayment is category
"reimbursement" with its payer there too. "Owed to you" is a running balance (decision 2): marked charges, less refunds
marked with them (R2), less repayments, less settlements. Which trip a repayment paid back is worked out oldest first,
for display only: nothing is stored per charge."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from steward.business.tagging import set_business
from steward.db.models import CATEGORIES, ReimburseSettlement, Reimburser, Transaction
from steward.services.transactions import normalize
from steward.services.vault_flows import REPAYMENT

NAME_MAX = 60
SETTLE_OFFER_UNDER_CENTS = 10_000       # spec: a repayment's receipt offers Settle when under $100 is left
KEEP = object()

NO_PAYER = "Say who pays you back first."
CHOOSE_PAYER = "Choose who pays you back."
NO_SUCH_PAYER = "No such payer."
NAME_RULE = "Give a name from 1 to 60 characters."
NAME_TAKEN = "Another payer already has that name."
EITHER = "A charge is either business or reimbursable."
NOT_FOR_TRANSFERS = "A transfer moves money between your own accounts, so it isn't reimbursable."
NOT_REIMBURSABLE = "Only money out, or a refund from a merchant you've marked reimbursable, can be reimbursable."
HOUSEHOLD_ONLY = "Reimbursements are for household books."
NOTHING_TO_SETTLE = "There's nothing to settle."
BALANCE_CHANGED = "The balance changed since. Look again."
SETTLE_CATEGORY = "Choose a spending category."


class ReimburseError(ValueError):
    """A refusal in plain words; the API answers 422 with it."""


def clean_name(raw: object) -> str:
    """A payer's name as kept: spaces tidied, 1-60 characters."""
    if not isinstance(raw, str):
        raise ReimburseError(NAME_RULE)
    name = " ".join(raw.split())
    if not 1 <= len(name) <= NAME_MAX:
        raise ReimburseError(NAME_RULE)
    return name


def _named(db: Session, name: str) -> Reimburser | None:
    return db.scalar(select(Reimburser).where(func.lower(Reimburser.name) == name.lower()))


def payers(db: Session) -> list[Reimburser]:
    return list(db.scalars(select(Reimburser).order_by(Reimburser.id)))


def add_payer(db: Session, raw: object, at: datetime) -> tuple[Reimburser, bool]:
    """Made on first use (decision 6). The same name again, in any case, is the payer already there, so one employer
    never becomes two (Review Focus 5). Returns (payer, made)."""
    name = clean_name(raw)
    found = _named(db, name)
    if found is not None:
        return found, False
    p = Reimburser(name=name, created_at=at)
    db.add(p)
    db.flush()
    return p, True


def rename_payer(db: Session, p: Reimburser, raw: object) -> Reimburser:
    name = clean_name(raw)
    other = _named(db, name)
    if other is not None and other.id != p.id:
        raise ReimburseError(NAME_TAKEN)
    p.name = name
    db.flush()
    return p


def payer_for(db: Session, chosen: object = None) -> Reimburser:
    """Who a mark or a repayment goes to: the one chosen, else the only one. Refused with no payer yet, and with two or
    more and none chosen: Steward never guesses between payers."""
    if chosen is not None:
        p = db.get(Reimburser, chosen) if isinstance(chosen, int) and not isinstance(chosen, bool) else None
        if p is None:
            raise ReimburseError(NO_SUCH_PAYER)
        return p
    every = payers(db)
    if not every:
        raise ReimburseError(NO_PAYER)
    if len(every) > 1:
        raise ReimburseError(CHOOSE_PAYER)
    return every[0]


def refundable_patterns(db: Session) -> set[str]:
    """R2: the descriptions of reimbursable charges. Money in on one of them can be marked reimbursable too."""
    raws = db.scalars(select(Transaction.raw_description).distinct().where(
        Transaction.reimburser_id.is_not(None), Transaction.amount_cents < 0, Transaction.category != REPAYMENT))
    return {p for p in map(normalize, raws) if p}


def can_reimburse(t: Transaction, patterns: set[str], category: str | None = None) -> bool:
    """Whether the Reimbursable switch is offered (spec, Marking): money out, or money in on a description with a
    reimbursable charge (R2); never a transfer or a repayment. `category` is the one the row is about to take."""
    c = category or t.category
    if t.is_transfer or c in ("transfer", REPAYMENT):
        return False
    if t.amount_cents < 0:
        return True
    return t.amount_cents > 0 and normalize(t.raw_description) in patterns


def mark(t: Transaction, payer: Reimburser, *, source: str = "manual", trip_id: object = KEEP) -> None:
    """Reimbursable for `payer`. Business goes off: a charge is either business or reimbursable."""
    if t.business_pct:
        set_business(t, 0, source="manual")
    t.reimburser_id, t.reimburse_source = payer.id, source
    if trip_id is not KEEP:
        t.trip_id = trip_id


def unmark(t: Transaction) -> None:
    """Not reimbursed (spec, Settling and Not reimbursed): the payer and the trip go, and the person's choice is kept so
    no rule marks the row again."""
    t.reimburser_id, t.trip_id, t.reimburse_source = None, None, "manual"


@dataclass(frozen=True)
class Owed:
    reimburser_id: int
    marked_cents: int = 0           # reimbursable charges, all time
    refunds_cents: int = 0          # money in marked with the payer (R2)
    repaid_cents: int = 0           # repayments (Reimbursement rows; a reversal counts against them)
    settled_cents: int = 0          # leftovers settled as spending
    since: date | None = None       # the first reimbursable charge
    last_repaid_on: date | None = None

    @property
    def owed_cents(self) -> int:
        """The spec's formula. Below $0 means the payer has paid more than has been marked."""
        return self.marked_cents - self.refunds_cents - self.repaid_cents - self.settled_cents

    @property
    def cleared_cents(self) -> int:
        """What came back one way or another: the owed bar's fill."""
        return self.refunds_cents + self.repaid_cents + self.settled_cents


def owed_by(db: Session) -> dict[int, Owed]:
    """Every payer's balance (spec, Owed to you): one grouped query, and the settlements. A payer with nothing yet owes
    $0. A charge is money out not in Reimbursement (engineering choice 1)."""
    a, repay = Transaction.amount_cents, Transaction.category == REPAYMENT
    charge, refund = and_(a < 0, Transaction.category != REPAYMENT), and_(a > 0, Transaction.category != REPAYMENT)
    rows = db.execute(
        select(Transaction.reimburser_id,
               func.coalesce(func.sum(case((charge, -a), else_=0)), 0),
               func.coalesce(func.sum(case((refund, a), else_=0)), 0),
               func.coalesce(func.sum(case((repay, a), else_=0)), 0),
               func.min(case((charge, Transaction.posted_at))),
               func.max(case((and_(repay, a > 0), Transaction.posted_at))))
        .where(Transaction.reimburser_id.is_not(None), Transaction.is_transfer.is_(False))
        .group_by(Transaction.reimburser_id)).all()
    settled = dict(db.execute(select(ReimburseSettlement.reimburser_id, func.sum(ReimburseSettlement.amount_cents))
                              .group_by(ReimburseSettlement.reimburser_id)).all())
    out = {pid: Owed(pid, settled_cents=int(settled.get(pid, 0))) for pid in db.scalars(select(Reimburser.id))}
    for pid, marked, refunds, repaid, since, last in rows:
        out[pid] = Owed(pid, int(marked), int(refunds), int(repaid), int(settled.get(pid, 0)), since, last)
    return out


def owed_map(db: Session) -> dict[int, int]:
    return {pid: o.owed_cents for pid, o in owed_by(db).items()}


@dataclass(frozen=True)
class Item:
    kind: str           # "trip" or "charge"
    id: int             # the trip's id, or the charge's transaction id
    reimburser_id: int
    first_on: date      # its earliest charge
    total_cents: int    # what it adds to the balance: its charges less its refunds, never below $0
    covered_cents: int  # how much of it has come back, filled oldest first

    @property
    def status(self) -> str:
        if self.covered_cents >= self.total_cents:
            return "paid"
        return "partly" if self.covered_cents > 0 else "waiting"


def statuses(db: Session, owed: dict[int, Owed] | None = None) -> dict[int, list[Item]]:
    """Which repayment pays which trip (spec): per payer, its trips and single charges by their earliest charge date,
    each filled in turn from what came back (repayments, settlements, and refunds on no trip; a refund on a trip nets
    inside it). Display only."""
    owed = owed_by(db) if owed is None else owed
    pool = {pid: o.repaid_cents + o.settled_cents for pid, o in owed.items()}
    parts: dict[int, dict[tuple[str, int], list[tuple[date, int]]]] = defaultdict(dict)
    rows = db.execute(select(Transaction.id, Transaction.reimburser_id, Transaction.trip_id, Transaction.posted_at,
                             Transaction.amount_cents)
                      .where(Transaction.reimburser_id.is_not(None), Transaction.is_transfer.is_(False),
                             Transaction.category != REPAYMENT)
                      .order_by(Transaction.posted_at, Transaction.id))
    for tid, pid, trip, on, cents in rows:
        if trip is None and cents > 0:
            pool[pid] = pool.get(pid, 0) + cents
            continue
        key = ("trip", trip) if trip is not None else ("charge", tid)
        parts[pid].setdefault(key, []).append((on, cents))
    out: dict[int, list[Item]] = {}
    for pid, items in parts.items():
        built = []
        for (kind, iid), rs in items.items():
            charges = [on for on, c in rs if c < 0] or [on for on, _ in rs]
            built.append((min(charges), kind, iid, max(0, -sum(c for _, c in rs))))
        built.sort(key=lambda b: (b[0], b[1] != "trip", b[2]))
        left, done = pool.get(pid, 0), []
        for first_on, kind, iid, total in built:
            covered = min(total, max(0, left))
            left -= covered
            done.append(Item(kind, iid, pid, first_on, total, covered))
        out[pid] = done
    return out


def settle_category(db: Session, pid: int, items: list[Item]) -> str:
    """Rule 2's default for Settle: the spending category with the most dollars among the payer's charges not yet paid
    back; ties in CATEGORIES order. Travel when there is none."""
    from steward.services.spending import SPENDING_CATEGORIES   # spending reaches setasides and deps: not at import time
    trips = [i.id for i in items if i.kind == "trip" and i.status != "paid"]
    charges = [i.id for i in items if i.kind == "charge" and i.status != "paid"]
    if not trips and not charges:
        return "travel"
    rows = db.execute(select(Transaction.category, func.sum(-Transaction.amount_cents))
                      .where(Transaction.reimburser_id == pid, Transaction.amount_cents < 0,
                             or_(Transaction.trip_id.in_(trips), Transaction.id.in_(charges)))
                      .group_by(Transaction.category)).all()
    ranked = sorted(((c, int(s)) for c, s in rows if c in SPENDING_CATEGORIES),
                    key=lambda r: (-r[1], CATEGORIES.index(r[0])))
    return ranked[0][0] if ranked else "travel"


def after_sort(t: Transaction, was_category: str, payer: Reimburser | None, reimbursable: bool | None) -> None:
    """The PATCH's reimbursable part, once the category is set (spec, Marking; engineering choice 6). A repayment takes
    its payer and no trip. The switch marks or un-marks. A row moved off Reimbursement, or onto Transfer, loses its
    payer."""
    if t.category == REPAYMENT:
        if payer is not None:
            mark(t, payer, trip_id=None)
    elif reimbursable is True and payer is not None:
        mark(t, payer)
    elif reimbursable is False or (t.reimburser_id is not None and (t.is_transfer or was_category == REPAYMENT)):
        unmark(t)
