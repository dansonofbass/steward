"""The open same-account questions (same-account spec, Asking and API): a held feed with an account it looks like, or
a pair the one-time check raised. A question's id is "held-<id>" or "pair-<id>"."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.db.models import Account, HeldFeed, Institution, SameAccountAnswer
from steward.services.accounts import latest_balance
from steward.services.same_account import detect
from steward.services.same_account import held as held_feeds


def get(db: Session, question: str) -> HeldFeed | SameAccountAnswer | None:
    """The open question with this id, or None (answered, unknown, or not an id at all)."""
    kind, _, num = question.partition("-")
    if not (num.isascii() and num.isdigit()) or len(num) > 12:
        return None
    if kind == "held":
        h = db.get(HeldFeed, int(num))
        return h if h is not None and h.candidate_account_id is not None else None
    if kind == "pair":
        a = db.get(SameAccountAnswer, int(num))
        return a if a is not None and a.answer == "open" else None
    return None


def open_count(db: Session) -> int:
    held = db.scalar(select(func.count()).select_from(HeldFeed).where(HeldFeed.candidate_account_id.is_not(None)))
    pairs = db.scalar(select(func.count()).select_from(SameAccountAnswer).where(SameAccountAnswer.answer == "open"))
    return (held or 0) + (pairs or 0)


def _balance(db: Session, account_id: int) -> int | None:
    lb = latest_balance(db, account_id)
    return lb[1] if lb else None


def open_questions(db: Session) -> list[dict]:
    """Every open question as the card shows it, newest first (spec, Asking)."""
    out: list[dict] = []
    for h in db.scalars(select(HeldFeed).where(HeldFeed.candidate_account_id.is_not(None))):
        cand = db.get(Account, h.candidate_account_id)
        m = detect.money(db, cand.id, held_feeds.days(h), (h.balance_date, h.balance_cents))
        out.append({"id": f"held-{h.id}", "kind": "held", "name": h.name,
                    "bank": db.get(Institution, h.institution_id).name, "balance_cents": h.balance_cents,
                    "candidate_id": cand.id, "candidate_name": cand.name, "candidate_bank": cand.institution.name,
                    "candidate_balance_cents": _balance(db, cand.id), "matches": m.matches,
                    "same_balance": m.same_balance, "since": h.first_seen_at.isoformat()})
    for q in db.scalars(select(SameAccountAnswer).where(SameAccountAnswer.answer == "open")):
        keep, other = db.get(Account, q.account_id), db.get(Account, q.other_account_id)
        m = detect.in_book(db, keep.id, other.id)              # counted now: syncs since it was raised add matches
        out.append({"id": f"pair-{q.id}", "kind": "in_book", "name": other.name, "bank": other.institution.name,
                    "balance_cents": _balance(db, other.id), "candidate_id": keep.id, "candidate_name": keep.name,
                    "candidate_bank": keep.institution.name, "candidate_balance_cents": _balance(db, keep.id),
                    "matches": m.matches, "same_balance": m.same_balance, "since": q.created_at.isoformat()})
    return sorted(out, key=lambda x: x["since"], reverse=True)
