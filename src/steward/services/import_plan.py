"""One preview for the whole batch (import/export spec, Batch preview and commit; P15-P18). Rows are counted by key
per account: (date, amount, tidied description, and the bank id when there is one). Already takes min(file count,
Steward count + earlier files' count); any extra copy within one file Looks the same; a fuzzy match (same amount and
description, ±2 days, another date) Looks the same; rows SimpleFIN covers are left out unless chosen (P16). The digest
is the SHA-256 of the plan: per file, its layout and the sorted rows to insert. The server never trusts the client's
counts: commit recomputes this and compares digests."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, ImportBatch, Transaction
from steward.services.import_staging import Staged
from steward.services.importers.base import ParsedRow
from steward.services.importers.layouts import Layout, Parsed
from steward.services.imports import WINDOW_DAYS, simplefin_since
from steward.services.transactions import tidy

LOOK_CAP = 200
STATEMENT_DAYS = 3                   # P37: Looks the same widens for statement rows only


@dataclass(frozen=True)
class Choice:
    staged: Staged
    account: Account
    layout: Layout | None
    parsed: Parsed
    include: frozenset[int]
    sent: bool                       # the person confirmed or answered this layout: saved at commit


@dataclass(frozen=True)
class StatementStaged:
    """A staged PDF statement in a batch's plan, where a CSV's Staged would stand (PDF statements spec, Batch preview
    and commit). The token is "s<stage id>"; version is the stage's updated_at, so a row edit after the preview changes
    the digest and the commit answers 409."""
    token: str
    name: str
    sha256: str
    stage_id: int
    version: str
    period: tuple[date, date]
    facts: dict = field(hash=False, compare=False)
    pages: int | None = None
    layout_id: int | None = None
    gap: int | None = None
    anyway: bool = False
    hint_key: str | None = None
    kind: str = "pdf"
    table: None = None
    last4: str | None = None
    card: bool = False
    scan: bool = False
    holdings: tuple[dict, ...] = field(default=(), hash=False, compare=False)


def is_statement(c: Choice) -> bool:
    return isinstance(c.staged, StatementStaged)


def _first(desc: str) -> str:
    words = tidy(desc).split()
    return words[0] if words else ""


@dataclass(frozen=True)
class Match:
    where: str                       # steward | file
    posted_at: date
    amount_cents: int
    description: str


@dataclass
class FilePlan:
    choice: Choice
    new: list[int] = field(default_factory=list)
    already: list[int] = field(default_factory=list)
    simplefin: list[int] = field(default_factory=list)
    same: list[tuple[int, Match]] = field(default_factory=list)


@dataclass
class Plan:
    files: list[FilePlan]
    since: dict[int, date | None]
    digest: str

    def new_rows(self) -> list[ParsedRow]:
        return [f.choice.parsed.rows[i] for f in self.files for i in f.new]


def _key(r: ParsedRow) -> tuple:
    return (r.posted_at, r.amount_cents, tidy(r.raw_description), r.external_id)


def _plan_file(c: Choice, steward: Counter, earlier: Counter, known_ids: set[str],
               near: dict[tuple[int, str], list[tuple[date, str]]], since: date | None, simplefin_on: bool,
               by_amount: dict[int, list[tuple[date, str]]]) -> FilePlan:
    fp = FilePlan(c)
    rows = c.parsed.rows
    groups: dict[tuple, list[int]] = defaultdict(list)
    first_id: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r.external_id and first_id.setdefault(r.external_id, i) != i:
            fp.already.append(i)                                # a bank id seen earlier in this same file
        else:
            groups[_key(r)].append(i)
    candidates: list[int] = []
    for k, idxs in groups.items():
        if k[3] and k[3] in known_ids:                          # the bank id is known
            fp.already += idxs
            continue
        from_batch = min(len(idxs), earlier[k])
        from_steward = min(len(idxs) - from_batch, steward[k[:3]])
        steward[k[:3]] -= from_steward
        n = from_batch + from_steward
        fp.already += idxs[:n]
        rest = idxs[n:]
        if not rest:
            continue
        if n == 0:
            candidates.append(rest[0])
            dupes, where = rest[1:], "file"
        else:
            dupes, where = rest, ("steward" if from_steward else "file")
        for i in dupes:
            r = rows[i]
            fp.same.append((i, Match(where, r.posted_at, r.amount_cents, r.raw_description)))
    for i in sorted(candidates):
        r = rows[i]
        if is_statement(c):
            close = next(((d, desc) for d, desc in by_amount.get(r.amount_cents, ())
                          if abs((d - r.posted_at).days) <= STATEMENT_DAYS and _first(desc) == _first(r.raw_description)
                          and (d, tidy(desc)) != (r.posted_at, tidy(r.raw_description))), None)
        else:
            close = next(((d, desc) for d, desc in near.get((r.amount_cents, tidy(r.raw_description)), ())
                          if d != r.posted_at and abs((d - r.posted_at).days) <= WINDOW_DAYS), None)
        if close is not None:
            fp.same.append((i, Match("steward", close[0], r.amount_cents, close[1])))
        elif since is not None and r.posted_at > since and not simplefin_on:
            fp.simplefin.append(i)
        else:
            fp.new.append(i)
    kept = []
    for i, m in fp.same:
        (fp.new.append(i) if i in c.include else kept.append((i, m)))
    fp.same = sorted(kept, key=lambda x: x[0])
    fp.new.sort()
    fp.already.sort()
    return fp


def _digest(files: list[FilePlan]) -> str:
    plan = [[f.choice.staged.token, f.choice.account.id, f.choice.layout.signature() if f.choice.layout else None,
             sorted(f.new), getattr(f.choice.staged, "version", None)] for f in files]
    return hashlib.sha256(json.dumps(plan, default=str).encode()).hexdigest()


def build(db: Session, choices: list[Choice], simplefin_include: set[int]) -> Plan:
    """At most two statements per account: its ±2-day window and its SimpleFIN start."""
    by_account: dict[int, list[Choice]] = defaultdict(list)
    for c in choices:
        if not c.parsed.held:
            by_account[c.account.id].append(c)
    plans: dict[int, FilePlan] = {id(c): FilePlan(c) for c in choices}
    since: dict[int, date | None] = {}
    for account_id, cs in by_account.items():
        rows = [r for c in cs for r in c.parsed.rows]
        if not rows:
            continue
        pad = timedelta(days=max(WINDOW_DAYS, STATEMENT_DAYS) if any(is_statement(c) for c in cs) else WINDOW_DAYS)
        lo = min(r.posted_at for r in rows) - pad
        hi = max(r.posted_at for r in rows) + pad
        existing = db.execute(select(Transaction.posted_at, Transaction.amount_cents, Transaction.raw_description,
                                     Transaction.external_id)
                              .where(Transaction.account_id == account_id, Transaction.posted_at >= lo,
                                     Transaction.posted_at <= hi)).all()
        known_ids = {e for *_, e in existing if e}               # grows with each planned file's ids (F4)
        steward = Counter((d, c, tidy(desc)) for d, c, desc, _ in existing)
        near: dict[tuple[int, str], list[tuple[date, str]]] = defaultdict(list)
        by_amount: dict[int, list[tuple[date, str]]] = defaultdict(list)
        for d, c, desc, _ in existing:
            near[(c, tidy(desc))].append((d, desc))
            by_amount[c].append((d, desc))
        periods = {(s, e) for s, e in db.execute(select(ImportBatch.period_start, ImportBatch.period_end).where(
            ImportBatch.account_id == account_id, ImportBatch.period_end.is_not(None),
            ImportBatch.rolled_back_at.is_(None))).all()}
        since[account_id] = simplefin_since(db, cs[0].account)
        earlier: Counter = Counter()
        for c in cs:
            if is_statement(c) and c.staged.period in periods:          # the same statement twice: every row Already
                plans[id(c)] = FilePlan(c, already=list(range(len(c.parsed.rows))))
                earlier.update(_key(r) for r in c.parsed.rows)
                continue
            plans[id(c)] = _plan_file(c, steward, earlier, known_ids, near, since[account_id],
                                      account_id in simplefin_include, by_amount)
            earlier.update(_key(r) for r in c.parsed.rows)
            known_ids.update(r.external_id for r in c.parsed.rows if r.external_id)
    files = [plans[id(c)] for c in choices]
    return Plan(files, since, _digest(files))


def months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _row(f: FilePlan, i: int) -> dict:
    r = f.choice.parsed.rows[i]
    return {"token": f.choice.staged.token, "row": i, "posted_at": r.posted_at.isoformat(), "amount_cents": r.amount_cents,
            "description": r.raw_description}


def preview_out(plan: Plan) -> dict:
    files, same, already = [], [], []
    simplefin: dict[int, list[dict]] = defaultdict(list)
    days: list[date] = []
    for f in plan.files:
        p = f.choice.parsed
        mine = [p.rows[i].posted_at for i in f.new]
        days += mine
        files.append({"token": f.choice.staged.token, "name": f.choice.staged.name, "account_id": f.choice.account.id,
                      "new": len(f.new), "already": len(f.already), "simplefin": len(f.simplefin), "same": len(f.same),
                      "from": min(mine).isoformat() if mine else None, "to": max(mine).isoformat() if mine else None,
                      "errors": [{"row": e.row, "text": e.text} for e in p.errors[:3]], "unreadable": len(p.errors),
                      "held": p.held_text if p.held else None,
                      "left_out": {k: p.left_out.get(k, 0) for k in ("pending", "balance", "totals", "currency")}})
        for i, m in f.same:
            same.append({**_row(f, i), "match": {"where": m.where, "posted_at": m.posted_at.isoformat(),
                                                 "amount_cents": m.amount_cents, "description": m.description,
                                                 "account": f.choice.account.name}})
        already += [_row(f, i) for i in f.already]
        simplefin[f.choice.account.id] += [_row(f, i) for i in f.simplefin]
    covered = {a: rows for a, rows in simplefin.items() if rows}
    names = {f.choice.account.id: f.choice.account.name for f in plan.files}
    only = next(iter(covered)) if len(covered) == 1 else None
    start, end = (min(days), max(days)) if days else (None, None)
    return {
        "digest": plan.digest, "new": sum(len(f.new) for f in plan.files),
        "already": sum(len(f.already) for f in plan.files),
        "simplefin": {"n": sum(len(r) for r in covered.values()),
                      "since": plan.since[only].isoformat() if only is not None and plan.since.get(only) else None},
        "same": sum(len(f.same) for f in plan.files), "unreadable": sum(len(f.choice.parsed.errors) for f in plan.files),
        "from": start.isoformat() if start else None, "to": end.isoformat() if end else None,
        "accounts": len({f.choice.account.id for f in plan.files if f.new}),
        "months": months(start, end) if start else 0, "files": files,
        "look": {"same": same[:LOOK_CAP], "same_more": max(0, len(same) - LOOK_CAP),
                 "simplefin": [{"account_id": a, "account": names[a], "since": plan.since[a].isoformat(),
                                "rows": rows[:LOOK_CAP], "more": max(0, len(rows) - LOOK_CAP)} for a, rows in covered.items()],
                 "already": already[:LOOK_CAP], "already_more": max(0, len(already) - LOOK_CAP)}}
