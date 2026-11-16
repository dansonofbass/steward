"""Staged statements in the book's encrypted DB (PDF statements spec P2-P5, P34-P36). Book-wide: every manager sees
every staged statement ("Added by Jane"); viewers never do (the routes). Seven days from the last change; a day-6
event on For you; at expiry the rows, lines and facts go and the name stays seven more days ("Cleared after a week");
Remove's ten minutes. Row review's operations change only this row's JSON, never undo_entry. Nothing here talks to a
model or reads a PDF."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, joinedload

from steward import gateway_name
from steward.db.models import (INVESTMENT_TYPES, Account, AccountFeed, AccountType, EventLog, ImportHint,
                               StatementStage)
from steward import clock
from steward.events import log_event
from steward.services.statements import check
from steward.services.statements.copy import CLEARED_LOG, CLEARED_LOG_ONE, ERRORS, WARN_EVENT, WARN_EVENT_ONE
from steward.services.statements.extract import norm
from steward.services.statements.rules import MAX_ROWS
from steward_boundary.statements_wire import MAX_CENTS

TTL = timedelta(days=7)
WARN_BEFORE = timedelta(days=1)
CLEARED_KEEP = timedelta(days=7)
REMOVE_WINDOW = timedelta(minutes=10)
SCAN_MARK = '{"scan": true'                  # a stage's proposal while it reads as a scan (plan Engineering choice 7)
MAX_FILES = 30
MAX_OPS = 100
HOLDING_KINDS = ("investment", "retirement")
MAX_HOLDINGS = 200
DESCRIPTION_MAX = 200
OUTSIDE = timedelta(days=7)
READY_STATES = ("ready",)
FITTING = {
    "bank": frozenset({AccountType.checking, AccountType.savings, AccountType.business_checking}),
    "card": frozenset({AccountType.credit, AccountType.business_credit}),
    "investment": INVESTMENT_TYPES, "retirement": INVESTMENT_TYPES,
    "loan": frozenset({AccountType.loan, AccountType.mortgage}),
}


def _day(at: datetime) -> str:
    d = at.astimezone(clock.household_tz())
    return f"{d:%b} {d.day}"


def is_scanning(s: StatementStage) -> bool:
    return bool(s.proposal) and s.proposal.startswith(SCAN_MARK)


def touch(s: StatementStage, now: datetime) -> None:
    """P4: every change moves the seven days on (and a warning already given is due again later)."""
    s.updated_at, s.expires_at, s.warned_at = now, now + TTL, None


def live_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StatementStage)
                     .where(StatementStage.state != "cleared", StatementStage.removed_at.is_(None))) or 0


def same_file(db: Session, sha: str) -> StatementStage | None:
    return db.scalar(select(StatementStage).where(StatementStage.content_sha256 == sha,
                                                  StatementStage.removed_at.is_(None)).order_by(StatementStage.id))


def add(db: Session, *, user_id: int, filename: str, size: int, sha: str, now: datetime) -> StatementStage:
    s = StatementStage(added_by=user_id, added_at=now, filename=filename[:200], bytes=size, content_sha256=sha,
                       state="queued", pages_done=0, tries=0, anyway=False, part=0)
    touch(s, now)
    db.add(s)
    db.flush()
    return s


def sweep(db: Session, now: datetime) -> int:
    """P4, P5: Remove's window, the day-6 event, expiry and the cleared name's end. Returns how many rows it changed."""
    changed = db.execute(delete(StatementStage).where(StatementStage.removed_at.is_not(None),
                                                      StatementStage.removed_at <= now - REMOVE_WINDOW)).rowcount
    changed += db.execute(delete(StatementStage).where(StatementStage.state == "cleared",
                                                       StatementStage.expires_at <= now - CLEARED_KEEP)).rowcount
    due = db.scalars(select(StatementStage).where(StatementStage.state != "cleared",
                                                  StatementStage.expires_at <= now)).all()
    for s in due:
        s.state, s.rows, s.lines, s.statement, s.holdings, s.proposal, s.error = "cleared", None, None, None, None, None, None
    if due:
        log_event(db, "info", "import", CLEARED_LOG_ONE if len(due) == 1 else CLEARED_LOG.format(n=len(due)))
    soon = db.scalars(select(StatementStage).where(StatementStage.state != "cleared", StatementStage.removed_at.is_(None),
                                                   StatementStage.warned_at.is_(None),
                                                   StatementStage.expires_at <= now + WARN_BEFORE)).all()
    if soon:
        day = _day(min(s.expires_at for s in soon))
        message = WARN_EVENT_ONE.format(day=day) if len(soon) == 1 else WARN_EVENT.format(n=len(soon), day=day)
        open_one = db.scalar(select(EventLog.id).where(EventLog.kind == "import", EventLog.actionable.is_(True),
                                                       EventLog.message == message, EventLog.resolved_at.is_(None)))
        if open_one is None:
            log_event(db, "info", "import", message, actionable=True)
        for s in soon:
            s.warned_at = now
    db.flush()
    return changed + len(due) + len(soon)


def sweep_due(db: Session, now: datetime) -> bool:
    """Whether sweep() would change anything now, in one read: GET /import/statements takes the book's write lock only
    then (phase 18), so opening Import, and its poll while a statement reads, are plain reads."""
    return db.scalar(select(StatementStage.id).where(or_(
        and_(StatementStage.removed_at.is_not(None), StatementStage.removed_at <= now - REMOVE_WINDOW),
        and_(StatementStage.state == "cleared", StatementStage.expires_at <= now - CLEARED_KEEP),
        and_(StatementStage.state != "cleared", StatementStage.expires_at <= now + WARN_BEFORE,
             or_(StatementStage.expires_at <= now,
                 and_(StatementStage.removed_at.is_(None), StatementStage.warned_at.is_(None)))),
    )).limit(1)) is not None


def hint_key(institution: str | None, last4: str | None) -> str | None:
    """Plan Engineering choice 24: "pdf:<normalized institution>:<last 4>"; never more of the number."""
    if not institution or not last4 or not re.fullmatch(r"\d{4}", last4):
        return None
    return f"pdf:{norm(institution)[:60]}:{last4}"


def suggest(db: Session, kind: str | None, institution: str | None, last4: str | None,
            layout_account_id: int | None) -> tuple[int | None, str | None]:
    """P36: a remembered statement hint, then a unique last-4 match in account names and SimpleFIN feed names, then the
    layout's last account when no other account carries those last 4, then the institution's name with exactly one
    fitting account."""
    accounts = list(db.scalars(select(Account).options(joinedload(Account.institution)).where(Account.is_active.is_(True))))
    ids = {a.id for a in accounts}
    key = hint_key(institution, last4)
    if key:
        hint = db.get(ImportHint, key)
        if hint is not None and hint.account_id in ids:
            return hint.account_id, "hint"
    carrying: set[int] = set()
    if last4:
        carrying = {a.id for a in accounts if re.search(rf"(?<!\d){last4}(?!\d)", a.name)}
        carrying |= {aid for aid, name in db.execute(select(AccountFeed.account_id, AccountFeed.name))
                     if aid in ids and re.search(rf"(?<!\d){last4}(?!\d)", name)}
        if len(carrying) == 1:
            return next(iter(carrying)), "digits"
    if layout_account_id in ids and not (carrying - {layout_account_id}):
        return layout_account_id, "layout"
    if institution:
        n = f" {norm(institution)} "
        fits = [a for a in accounts if len(norm(a.institution.name)) >= 3 and f" {norm(a.institution.name)} " in n
                and a.type in FITTING.get(kind or "", frozenset())]
        if len(fits) == 1:
            return fits[0].id, "name"
    return None, None


def rows_of(s: StatementStage) -> list[dict]:
    return json.loads(s.rows) if s.rows else []


def facts_of(s: StatementStage) -> dict:
    return json.loads(s.statement) if s.statement else {}


def holdings_of(s: StatementStage) -> list[dict]:
    return json.loads(s.holdings) if s.holdings else []


def _live(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["state"] != "removed"]


def regap(s: StatementStage) -> int | None:
    """P20 over the rows as they stand (P34: the server recomputes the gap after each change)."""
    f = facts_of(s)
    if not f:
        return None
    if f.get("kind") == "loan":
        return 0 if f.get("closing_cents") is not None else None
    if f.get("kind") in HOLDING_KINDS:
        live = [h for h in holdings_of(s) if h["state"] != "removed"]
        total = f.get("total_cents") if f.get("total_cents") is not None else f.get("closing_cents")
        return check.holdings_gap(total, [h["value_cents"] for h in live]) if live else None
    return check.gap(f.get("kind"), f.get("opening_cents"), f.get("closing_cents"),
                     [r["amount_cents"] for r in _live(rows_of(s))])


def sections_of(s: StatementStage) -> list[dict]:
    f, rows = facts_of(s), _live(rows_of(s))
    out = []
    for sec in f.get("sections", []):
        mine = [r for r in rows if r.get("section") == sec["title"]]
        out.append({"title": sec["title"], "rows": len(mine), "sum_cents": sum(r["amount_cents"] for r in mine),
                    "total_cents": sec.get("total_cents")})
    return out


class OpsRefused(ValueError):
    pass


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _day_ok(value, period: tuple[date, date]) -> date:
    try:
        d = date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        d = None
    if d is None or d < period[0] - OUTSIDE or d > period[1] + OUTSIDE:
        raise OpsRefused("date")
    return d


def _text(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > DESCRIPTION_MAX or not value.isprintable():
        raise OpsRefused("description")
    return " ".join(value.split())


def _cents(value) -> int:
    if not _int(value) or abs(value) > MAX_CENTS // 100:
        raise OpsRefused("amount")
    return value


def apply_ops(s: StatementStage, ops, pages: int | None) -> None:
    """P34: edit, add, remove (kept as removed, so Undo can put it back) and restore. All or nothing: a bad op leaves
    the rows as they were. At most 100 ops; each index once among edits, removals and restores, and within the rows."""
    if not isinstance(ops, list) or len(ops) > MAX_OPS or not all(isinstance(o, dict) for o in ops):
        raise OpsRefused("ops")
    rows = [dict(r) for r in rows_of(s)]
    f = facts_of(s)
    period = (date.fromisoformat(f["period"][0]), date.fromisoformat(f["period"][1])) if f.get("period") else None
    if period is None:
        raise OpsRefused("period")
    touched: set[int] = set()
    n = len(rows)
    for o in ops:
        kind = o.get("op")
        if kind in ("edit", "remove", "restore"):
            i = o.get("i")
            if not _int(i) or not 0 <= i < n or i in touched:
                raise OpsRefused("index")
            touched.add(i)
            r = rows[i]
            if kind == "remove":
                if r["state"] == "removed":   # a second remove would overwrite was, and restore could never put it back
                    raise OpsRefused("remove")
                r["was"], r["state"] = r["state"], "removed"
            elif kind == "restore":
                if r["state"] != "removed":
                    raise OpsRefused("restore")
                r["state"] = r.pop("was", "read")
            else:
                if set(o) - {"op", "i", "date", "description", "amount_cents"} or len(o) < 3:
                    raise OpsRefused("edit")
                if "date" in o:
                    r["date"] = _day_ok(o["date"], period).isoformat()
                if "description" in o:
                    r["description"] = _text(o["description"])
                if "amount_cents" in o:
                    r["amount_cents"] = _cents(o["amount_cents"])
                if r["state"] == "read":
                    r["state"] = "edited"
        elif kind == "add":
            if set(o) - {"op", "date", "description", "amount_cents", "page"}:
                raise OpsRefused("add")
            page = o.get("page")
            if page is not None and (not _int(page) or not 1 <= page <= (pages or 1)):
                raise OpsRefused("page")
            rows.append({"date": _day_ok(o.get("date"), period).isoformat(), "description": _text(o.get("description")),
                         "amount_cents": _cents(o.get("amount_cents")), "page": page, "section": None, "state": "added"})
        else:
            raise OpsRefused("op")
    if len(rows) > MAX_ROWS:
        raise OpsRefused("rows")
    s.rows = json.dumps(rows)


def apply_holding_ops(s: StatementStage, ops) -> None:
    """Holdings review (spec: "Not right" opens the holdings as row review opens rows): edit, add, remove (kept as
    removed) and restore; all or nothing; at most 100 ops, each index once and within the holdings."""
    from steward.services.statements.holdings import MAX_SHARES_MILLI
    if not isinstance(ops, list) or len(ops) > MAX_OPS or not all(isinstance(o, dict) for o in ops):
        raise OpsRefused("ops")
    hs = [dict(h) for h in holdings_of(s)]
    touched, n = set(), len(hs)

    def fields(o: dict, h: dict) -> None:
        if "symbol" in o:
            v = o["symbol"]
            if v is not None and (not isinstance(v, str) or len(v) > 20 or not v.isprintable()):
                raise OpsRefused("symbol")
            h["symbol"] = (v.strip() or None) if v is not None else None
        if "name" in o:
            h["name"] = _text(o["name"])
        if "shares_milli" in o:
            if not _int(o["shares_milli"]) or abs(o["shares_milli"]) > MAX_SHARES_MILLI:
                raise OpsRefused("shares")
            h["shares_milli"] = o["shares_milli"]
        if "value_cents" in o:
            h["value_cents"] = _cents(o["value_cents"])

    for o in ops:
        kind = o.get("op")
        if kind in ("edit", "remove", "restore"):
            i = o.get("i")
            if not _int(i) or not 0 <= i < n or i in touched:
                raise OpsRefused("index")
            touched.add(i)
            h = hs[i]
            if kind == "remove":
                if h["state"] == "removed":   # a second remove would overwrite was, and restore could never put it back
                    raise OpsRefused("remove")
                h["was"], h["state"] = h["state"], "removed"
            elif kind == "restore":
                if h["state"] != "removed":
                    raise OpsRefused("restore")
                h["state"] = h.pop("was", "read")
            else:
                if set(o) - {"op", "i", "symbol", "name", "shares_milli", "value_cents"} or len(o) < 3:
                    raise OpsRefused("edit")
                fields(o, h)
                if h["state"] == "read":
                    h["state"] = "edited"
        elif kind == "add":
            if set(o) - {"op", "symbol", "name", "shares_milli", "value_cents"} or "name" not in o or "value_cents" not in o:
                raise OpsRefused("add")
            h = {"symbol": None, "name": "", "shares_milli": 0, "value_cents": 0, "cash": False, "page": None,
                 "state": "added"}
            fields(o, h)
            hs.append(h)
        else:
            raise OpsRefused("op")
    if len(hs) > MAX_HOLDINGS:
        raise OpsRefused("holdings")
    s.holdings = json.dumps(hs)


def put_assembled(s: StatementStage, reading, facts: dict) -> None:
    """A scan's assembled statement onto the stage (the reader's _finish_scan and the account change both use it): the
    holdings of an investment kind, the rows of a bank or card, and nothing of the other (F7: an investment or loan
    statement carries no transaction rows)."""
    facts = dict(facts)
    held = facts.pop("holdings", [])
    s.statement = json.dumps(facts)
    if facts["kind"] in HOLDING_KINDS:
        s.holdings = json.dumps([{**h, "page": None, "state": "read"} for h in held])
        s.rows = json.dumps([])
    else:
        s.holdings = None
        s.rows = json.dumps([] if facts["kind"] == "loan" else
                            [{"date": x.date.isoformat(), "description": x.description, "amount_cents": x.amount_cents,
                              "page": x.page, "section": x.section, "state": "read", "scan": True} for x in reading.rows])


def importable(s: StatementStage) -> bool:
    """Only ready statements reach a preview: ready, or off with Import anyway; with an account (spec, Batch preview)."""
    return s.removed_at is None and s.account_id is not None and (
        s.state == "ready" or (s.state == "off" and s.anyway))


def _label(s: StatementStage, f: dict) -> str | None:
    return f.get("label") or f.get("institution")


def _error_text(s: StatementStage) -> str | None:
    if not s.error:
        return None
    n = s.pages_done + 1 if s.error == "page_failed" else max(1, s.pages_done)
    return gateway_name.fill(ERRORS.get(s.error, "")).format(n=n, m=s.pages or n) or None


def needs_account(s: StatementStage, scanning: bool | None = None) -> bool:
    """A scan's bank-or-owed sense comes from its account (Engineering choice 6), so with none chosen there is no check
    to speak of: not a gap, not "off"; the line asks for the account."""
    if scanning is None:
        scanning = is_scanning(s)
    return scanning and s.account_id is None and s.state in ("ready", "off")


def line_out(s: StatementStage, people: dict[int, str], me: int, imported: str | None,
             scanning: bool | None = None) -> dict:
    """A statement line (spec, API). The last 4 only; "Added by" when it wasn't you. The listing says which stages are
    reading as scans in one query (scanning), so the long proposal is never loaded per line."""
    f = facts_of(s)
    if scanning is None:
        scanning = is_scanning(s)
    progress = {"done": s.pages_done, "of": s.pages or 1} if scanning and s.state in ("queued", "reading", "waiting") else None
    rows = _live(rows_of(s))
    period = f.get("period")
    return {"id": s.id, "name": s.filename, "bytes": s.bytes, "pages": s.pages,
            "added_by": None if s.added_by == me else people.get(s.added_by, "someone"),
            "kind": s.kind, "state": s.state, "error": s.error, "error_text": _error_text(s),
            "label": _label(s, f), "statement_kind": f.get("kind"),
            "period": {"start": period[0], "end": period[1]} if period else None,
            "rows": len(rows) if s.rows is not None else None,
            "holdings": len([h for h in holdings_of(s) if h["state"] != "removed"]) if s.holdings else None,
            "balance_cents": f.get("closing_cents") if f.get("kind") == "loan" else None,
            "gap_cents": None if needs_account(s, scanning) else s.gap_cents, "anyway": s.anyway,
            "needs_account": needs_account(s, scanning), "progress": progress, "last4": f.get("last4"),
            "account_id": s.account_id, "suggested_by": s.suggested_by, "imported_before": imported,
            "expires_at": s.expires_at.isoformat(), "removed": s.removed_at is not None}


def detail_out(s: StatementStage) -> dict:
    """The detail for the layout check and row review: the rows with their index, the sections, the check."""
    f = facts_of(s)
    rows = rows_of(s)
    return {"id": s.id, "state": s.state, "gap_cents": s.gap_cents, "anyway": s.anyway, "pages": s.pages,
            "statement": {k: f.get(k) for k in ("kind", "institution", "label", "last4", "period", "opening_cents",
                                                "closing_cents", "opening_label", "closing_label", "total_cents")},
            "holdings": [{"i": i, **{k: h.get(k) for k in ("symbol", "name", "shares_milli", "value_cents", "cash", "page", "state")}}
                         for i, h in enumerate(holdings_of(s))],
            "rows": [{"i": i, **{k: r.get(k) for k in ("date", "description", "amount_cents", "page", "section", "state")},
                "scan": bool(r.get("scan"))}
                     for i, r in enumerate(rows)],
            "sections": sections_of(s), "unreadable": f.get("unreadable", []), "holdings_update": holdings_update(s)}


def holdings_update(s: StatementStage) -> bool:
    """An investment scan whose pages were read for rows because the gateway couldn't read holdings (P31's note)."""
    return facts_of(s).get("kind") in HOLDING_KINDS and is_scanning(s) and bool(json.loads(s.proposal).get("holdings_old"))
