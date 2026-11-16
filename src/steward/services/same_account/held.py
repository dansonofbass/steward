"""Held feeds (same-account spec, decision 2). A SimpleFIN account that looks like one already here isn't ingested at
all: no account, no transactions, no balance. Its latest balance and up to 400 transactions wait in held_feed, in the
book, until a person answers. Nothing reads them but this package."""
import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import HeldFeed
from steward.services.importers.base import ParsedRow
from steward.services.simplefin.client import SfAccount, SfTxn

PAYLOAD_MAX = 400


def _merged(payload: str, txns: list[SfTxn]) -> str:
    """The kept rows with today's merged in by id (a row sent again replaces itself), the newest 400, oldest first."""
    rows = {r["id"]: r for r in json.loads(payload)}
    for t in txns:
        rows[t.id] = {"id": t.id, "posted": t.posted_at.isoformat(), "amount_cents": t.amount_cents,
                      "description": t.description}
    newest = sorted(rows.values(), key=lambda r: (r["posted"], r["id"]), reverse=True)[:PAYLOAD_MAX]
    return json.dumps(sorted(newest, key=lambda r: (r["posted"], r["id"])))


def find(db: Session, ext: str) -> HeldFeed | None:
    return db.scalar(select(HeldFeed).where(HeldFeed.external_id == ext))


def hold(db: Session, a: SfAccount, institution_id: int, candidate_id: int, now: datetime) -> HeldFeed:
    h = HeldFeed(external_id=f"sfin:{a.id}", institution_id=institution_id, name=a.name, currency=a.currency[:3],
                 candidate_account_id=candidate_id, balance_cents=a.balance_cents, balance_date=a.balance_date,
                 payload=_merged("[]", a.transactions), first_seen_at=now, last_seen_at=now)
    db.add(h)
    db.flush()
    return h


def refresh(h: HeldFeed, a: SfAccount, now: datetime) -> None:
    """The next sync: a balance at least as new replaces the held one, the rows merge in, the name follows the bank's."""
    if a.balance_date >= h.balance_date:
        h.balance_cents, h.balance_date = a.balance_cents, a.balance_date
    h.name, h.payload, h.last_seen_at = a.name, _merged(h.payload, a.transactions), now


def rows(h: HeldFeed) -> list[ParsedRow]:
    return [ParsedRow(date.fromisoformat(r["posted"]), r["amount_cents"], r["description"], r["id"])
            for r in json.loads(h.payload)]


def days(h: HeldFeed) -> list[tuple[date, int]]:
    return [(r.posted_at, r.amount_cents) for r in rows(h)]
