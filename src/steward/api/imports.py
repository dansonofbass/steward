import hashlib
import json
import re
from dataclasses import replace
from datetime import date
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload, undefer

from steward.api.body import json_object
from steward.api.body import text as body_text
from steward.db.directory_models import User
from steward.db.engine import begin_read
from steward.db.models import (Account, AccountType, BalanceSnapshot, Holding, ImportBatch, ImportHint, ImportLayout,
                               ImportSet, PositionsImport, Source, StatementLayout, StatementStage, Transaction)
from steward import clock
from steward.deps import (BookContext, book_db, current_user, managers_only, model, not_recorded, now,
                          open_book, real_book_only, recorded, today, viewer_ok)
from steward.events import log_event
from steward.inventory.files import clean_name
from steward.inventory.accounts import after_new_data, run_safely
from steward.inventory.changes import record
from steward.services import import_staging as staging
from steward.services import import_plan as plan_svc
from steward.services import imports as svc
from steward.services.holdings import Position, replace_holdings
from steward.services.importers import dates as D
from steward.services.importers.base import ParsedRow
from steward.services.importers.decode import FileRefused
from steward.services.importers.layouts import (Layout, Parsed, account_digits, date_format_for, mapping_from, norm, remembered,
                                                sample)
from steward.services.importers.sign import file_sign
from steward.services.ingest import model_fill, rule_suggestions, teaching_examples
from steward.services.review import duplicate_pairs
from steward.services.setasides import match_all
from steward.services.statements import stage as statement_stage
from steward.services.statements.rules import OWED
from steward.services.undo import TTL, capturing
from steward.watch.run import WATCH_FAILED, watch_after

# A viewer gets 404 on the whole import area, writes included: viewer_ok lets the write through open_book's 403 and
# managers_only (router-wide, after open_book) answers 404, so no route answers a viewer differently.
router = APIRouter(prefix="/import", dependencies=[Depends(open_book), Depends(real_book_only), Depends(managers_only)])
# The one import route a viewer reads: Came from shows a file's line and its rows to viewers (without Undo).
member_router = APIRouter(prefix="/import", dependencies=[Depends(open_book), Depends(real_book_only)])
IMPORT_FAILED = "Couldn't update the inventory after this import."
IMPORT_MATCH_FAILED = "Couldn't match payments to set-asides after this import."
MAX_BYTES = 5 * 1024 * 1024
CHUNK = 1024 * 1024
TOO_BIG = "That file is bigger than 5 MB."
NOT_UNDERSTOOD = "That request wasn't understood."
NO_FILE = "These files expired. Add them again."
EVERYDAY = frozenset({AccountType.checking, AccountType.savings, AccountType.credit, AccountType.business_checking,
                      AccountType.business_credit})


SAFELISTED = frozenset({"", "text/plain", "multipart/form-data", "application/x-www-form-urlencoded"})


async def file_body(request: Request) -> bytes:
    """The upload is the request body itself, never multipart or UploadFile (plan Engineering choice 22: Starlette's
    multipart parser writes a part over 1 MB to a temporary file on disk, the NAS container has no tmpfs, and P3 says
    nothing from a file touches disk before commit). Its type is application/octet-stream or the file's own (text/csv,
    application/x-ofx), never a CORS-safelisted one, so a cross-site page can't send it without a preflight. A declared
    Content-Length over the cap is refused before anything is read; a chunked body is counted as it streams, in memory.
    BodyLimit guards the same path at 5 MB + 1 MB."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() in SAFELISTED:
        raise HTTPException(415, detail={"error": NOT_UNDERSTOOD})
    declared = request.headers.get("content-length", "").strip()
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(413, detail={"error": TOO_BIG})
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BYTES:
            raise HTTPException(413, detail={"error": TOO_BIG})
    return bytes(buf)


def remembered_for(db: Session):
    def find(key: str) -> Layout | None:
        row = db.scalar(select(ImportLayout).where(ImportLayout.key == key, ImportLayout.forgotten_at.is_(None)))
        if row is None:
            return None
        return remembered(row.key, json.loads(row.header), row.id, row.label,
                          {k: int(v) for k, v in json.loads(row.mapping).items()}, row.negate, row.date_format)
    return find


def _active_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).options(joinedload(Account.institution)).where(Account.is_active.is_(True))))


def _suggest(db: Session, f: staging.Staged, accounts: list[Account]) -> tuple[int | None, str | None]:
    """P5: a remembered OFX account, a remembered layout's last account, a unique last-4 match against account names,
    then the file name against institution names with exactly one everyday account (pre-selected only then)."""
    ids = {a.id for a in accounts}
    if f.hint_key:
        hint = db.get(ImportHint, f.hint_key)
        if hint is not None and hint.account_id in ids:
            return hint.account_id, "hint"
    if f.layout is not None and f.layout.state == "remembered":
        row = db.get(ImportLayout, f.layout.id)
        if row is not None and row.account_id in ids:
            return row.account_id, "layout"
    named = re.findall(r"(?<!\d)(\d{4})(?!\d)", f.name)
    digits = f.last4 or (account_digits(f.table) if f.table is not None else None) or (named[0] if len(named) == 1 else None)
    if digits:
        hits = [a for a in accounts if digits in a.name]
        if len(hits) == 1:
            return hits[0].id, "digits"
    words = f" {norm(f.name)} "
    insts = {a.institution_id for a in accounts if a.institution.source != Source.manual
             and len(norm(a.institution.name)) >= 3 and f" {norm(a.institution.name)} " in words}
    if len(insts) == 1:
        fits = [a for a in accounts if a.institution_id in insts and a.type in EVERYDAY]
        if len(fits) == 1:
            return fits[0].id, "name"
    return None, None


def _imported_before(db: Session, sha: str) -> str | None:
    at = db.scalar(select(func.max(ImportBatch.imported_at)).where(ImportBatch.content_sha256 == sha,
                                                                    ImportBatch.rolled_back_at.is_(None)))
    return at.astimezone(clock.household_tz()).date().isoformat() if at else None


def _date_question(lay: Layout) -> dict | None:
    if lay.date_example is None or lay.date_options is None:
        return None
    return {"example": lay.date_example, "options": [
        {"format": f, "label": D.day_label(D.parse_day(lay.date_example, f)), "reading": D.reading(f)}
        for f in lay.date_options]}


def _layout_out(f: staging.Staged) -> dict | None:
    lay = f.layout
    if lay is None or f.table is None:
        return None
    return {"id": lay.id, "key": lay.key, "header": list(f.table.header), "mapping": lay.mapping, "negate": lay.negate,
            "date_format": lay.date_format, "reading": D.reading(lay.date_format) if lay.date_format else None,
            "sign_fixed": lay.sign_fixed, "sign": file_sign(lay, f.parsed), "date_question": _date_question(lay),
            "sample": sample(f.table)}


def entry(db: Session, f: staging.Staged, accounts: list[Account]) -> dict:
    p = f.parsed
    account_id, by = _suggest(db, f, accounts)
    days = [r.posted_at for r in p.rows]
    return {"token": f.token, "name": f.name, "bytes": f.size, "kind": f.kind,
            "state": "known" if f.layout is None else f.layout.state,
            "label": "OFX" if f.layout is None else f.layout.label, "card": f.card, "rows": len(p.rows),
            "from": min(days).isoformat() if days else None, "to": max(days).isoformat() if days else None,
            "imported_before": _imported_before(db, f.sha256), "account_id": account_id, "suggested_by": by,
            "layout": _layout_out(f), "errors": [{"row": e.row, "text": e.text} for e in p.errors[:3]],
            "unreadable": len(p.errors), "held": p.held_text if p.held else None,
            "left_out": {k: p.left_out.get(k, 0) for k in ("pending", "balance", "totals", "currency")}, "error": None}


def _refused(name: str, size: int, error: str) -> dict:
    return {"token": None, "name": name, "bytes": size, "kind": None, "state": "error", "label": None, "card": False,
            "rows": 0, "from": None, "to": None, "imported_before": None, "account_id": None, "suggested_by": None,
            "layout": None, "errors": [], "unreadable": 0, "held": None,
            "left_out": {"pending": 0, "balance": 0, "totals": 0, "currency": 0}, "error": error}


def _staging(request: Request) -> staging.ImportStaging:
    return request.app.state.import_staging


def _refuse(e: staging.StagingRefused) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.message})


@router.post("/files", status_code=201)
@viewer_ok
@not_recorded("Staging reads the file and saves nothing.")
def stage_file(request: Request, batch: str | None = None, raw: bytes = Depends(file_body),
               db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Spec P2: one request per file. Plain def, so the parse and the reads run in the threadpool."""
    t = now()
    try:
        b = _staging(request).batch(ctx.user_id, ctx.book.id, batch, t)
    except staging.StagingRefused as e:
        raise _refuse(e) from None
    name = clean_name(unquote(request.headers.get("x-filename", "")))
    if hashlib.sha256(raw).hexdigest() in b.uploads:
        return {"batch": b.id, "files": [_refused(name, len(raw), staging.SAME_FILE)]}
    try:
        _staging(request).room_for(len(raw), t)                 # before the parse, from the raw size alone
    except staging.StagingRefused as e:
        raise _refuse(e) from None
    begin_read(db)
    try:
        sha, size, files = staging.build(name, raw, today(), remembered_for(db))
    except FileRefused as e:
        return {"batch": b.id, "files": [_refused(name, len(raw), e.message)]}
    try:
        _staging(request).add(b, sha, size, files, t, others=statement_stage.live_count(db))
    except staging.StagingRefused as e:
        raise _refuse(e) from None
    accounts = _active_accounts(db)
    return {"batch": b.id, "files": [entry(db, f, accounts) for f in files]}


@router.get("/batch/{batch_id}")
def staged_batch(batch_id: str, request: Request, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Plan-owned (Engineering choice 6): the staged entries again, for a person coming back to the screen."""
    try:
        b = _staging(request).find(ctx.user_id, ctx.book.id, batch_id, now())
    except staging.StagingRefused as e:
        raise _refuse(e) from None
    accounts = _active_accounts(db)
    return {"batch": b.id, "files": [entry(db, f, accounts) for f in list(b.files.values())]}


@router.delete("/files/{token}", status_code=204)
@viewer_ok
@not_recorded("Removing a staged file saves nothing.")
def drop_file(token: str, request: Request, ctx: BookContext = Depends(open_book)):
    if not _staging(request).drop_file(ctx.user_id, ctx.book.id, token, now()):
        raise HTTPException(404, detail={"error": NO_FILE})


NOT_READY = "These files aren't ready yet."
NO_ACCOUNT = "No such account."
LABEL_MAX = 60


def _bad(message: str = NOT_UNDERSTOOD, status: int = 422) -> HTTPException:
    return HTTPException(status, detail={"error": message})


ID_MAX = 2**63 - 1        # SQLite's largest integer


def _ids(value) -> list[int]:
    """A list of row ids the database can hold (an oversized one is a refusal, never an OverflowError)."""
    if not isinstance(value, list) or not all(isinstance(i, int) and not isinstance(i, bool) and 1 <= i <= ID_MAX
                                              for i in value):
        raise _bad()
    return value


def _ints(value) -> list[int]:
    if not isinstance(value, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in value):
        raise _bad()
    return value


def _rows(value, n: int) -> frozenset[int]:
    """A file's include: each of its n rows at most once."""
    rows = _ints(value)
    if len(set(rows)) != len(rows) or not all(0 <= i < n for i in rows):
        raise _bad()
    return frozenset(rows)


def _sent_layout(f: staging.Staged, value) -> Layout | None:
    """A new layout the person confirmed, or a remembered one they answered again (P12, P14); None keeps the
    staged one. Known and built-in formats ignore it: their sign and dates are the format's."""
    if value is None or f.layout is None or f.layout.state in ("known", "builtin"):
        return None
    if not isinstance(value, dict):
        raise _bad()
    try:
        mapping = mapping_from(value.get("mapping"), len(f.table.header))
    except ValueError as e:
        raise _bad(str(e)) from None
    negate, fmt, label = value.get("negate"), value.get("date_format"), value.get("label")
    if negate is not None and not isinstance(negate, bool):
        raise _bad()
    if fmt not in (None, "") and fmt not in D.CANDIDATES:
        raise _bad()
    if label is not None and (not isinstance(label, str) or not label.strip() or len(label.strip()) > LABEL_MAX):
        raise _bad()
    if not fmt or mapping["date"] != f.layout.mapping.get("date"):
        # The server never dated this column (unguessed, unreadable, or Date moved in the confirm): work it out.
        fmt = date_format_for(f.table, mapping["date"])
    fixed = "direction" in mapping or ("amount" not in mapping and "debit" in mapping and "credit" in mapping)
    return replace(f.layout, mapping=mapping, negate=False if fixed else negate, date_format=fmt, sign_fixed=fixed,
                   label=label.strip() if label else f.layout.label)


KEPT = "The {day} balance was changed since, so it stays."


def _month_day(d: date) -> str:
    return f"{d:%b} {d.day}"


def _statement_choices(body: dict, db: Session) -> list[plan_svc.Choice]:
    """Spec, Batch preview and commit: only ready statements (ready, or off with Import anyway); each id once, its
    include within its rows; the stored gap recomputed from the stored rows (a stale one is the import round's 409)."""
    items = body.get("statements", [])
    if not isinstance(items, list) or len(items) > statement_stage.MAX_FILES or not all(isinstance(x, dict) for x in items):
        raise _bad()
    if any(set(x) - {"id", "account_id", "include"} for x in items):
        raise _bad()
    ids = _ids([x.get("id") for x in items])
    if len(set(ids)) != len(ids):
        raise _bad()
    found = {s.id: s for s in db.scalars(select(StatementStage).options(undefer(StatementStage.rows),
                                                                        undefer(StatementStage.statement),
                                                                        undefer(StatementStage.holdings))
                                         .where(StatementStage.id.in_(ids)))}
    try:
        aids = _ids([x.get("account_id") for x in items])
    except HTTPException:
        raise _bad(NOT_READY) from None
    accounts = {a.id: a for a in db.scalars(select(Account).options(joinedload(Account.institution))
                                            .where(Account.id.in_(set(aids))))}
    out = []
    for x, aid in zip(items, aids):
        s = found.get(x["id"])
        if s is None or s.removed_at is not None or not (s.state == "ready" or (s.state == "off" and s.anyway)):
            raise _bad(NOT_READY)
        if aid not in accounts:
            raise _bad(NO_ACCOUNT, 404)
        f = statement_stage.facts_of(s)
        if statement_stage.regap(s) != s.gap_cents or not f.get("period"):
            raise HTTPException(409, detail={"error": CHANGED})
        live = [r for r in statement_stage.rows_of(s) if r["state"] != "removed"]
        rows = tuple(ParsedRow(date.fromisoformat(r["date"]), r["amount_cents"], r["description"], None, r.get("page"))
                     for r in live)
        period = (date.fromisoformat(f["period"][0]), date.fromisoformat(f["period"][1]))
        staged = plan_svc.StatementStaged(
            token=f"s{s.id}", name=s.filename, sha256=s.content_sha256, stage_id=s.id, version=s.updated_at.isoformat(),
            period=period, facts=f, pages=s.pages, layout_id=s.layout_id, gap=s.gap_cents,
            anyway=s.state == "off" and s.anyway, hint_key=statement_stage.hint_key(f.get("institution"), f.get("last4")),
            last4=f.get("last4"), card=f.get("kind") in OWED,
            scan=any(r.get("scan") for r in live) or bool(f.get("scan")),
            holdings=tuple(h for h in statement_stage.holdings_of(s) if h["state"] != "removed"))
        out.append(plan_svc.Choice(staged, accounts[aid], None, Parsed(rows, (), {}),
                                   _rows(x.get("include", []), len(rows)), False))
    return out


def _statements_moved(db: Session, choices: list[plan_svc.Choice]) -> bool:
    """After the model call, under the write lock: a staged statement edited, forgotten or changed since it was read."""
    seen = {c.staged.stage_id: c.staged.version for c in choices if plan_svc.is_statement(c)}
    if not seen:
        return False
    cols = (StatementStage.id, StatementStage.updated_at, StatementStage.removed_at, StatementStage.state,
            StatementStage.anyway)
    live = {r.id: r for r in db.execute(select(*cols).where(StatementStage.id.in_(list(seen))))}
    for sid, version in seen.items():
        r = live.get(sid)
        if r is None or r.removed_at is not None or not (r.state == "ready" or (r.state == "off" and r.anyway)) \
                or r.updated_at.isoformat() != version:
            return True
    return False


def _choices(request: Request, body: dict, db: Session, ctx: BookContext) -> tuple[str | None, list[plan_svc.Choice], set[int]]:
    batch_id, files = body.get("batch"), body.get("files", [])
    if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
        raise _bad()
    sf_include = set(_ints(body.get("simplefin_include", [])))
    out: list[plan_svc.Choice] = []
    if files:
        if not isinstance(batch_id, str):
            raise _bad()
        out += _csv_choices(request, batch_id, files, db, ctx)
    elif batch_id is not None and not isinstance(batch_id, str):
        raise _bad()
    out += _statement_choices(body, db)
    if not out:
        raise _bad(NOT_READY)
    return (batch_id if files else None), out, sf_include


def _csv_choices(request: Request, batch_id: str, files: list[dict], db: Session, ctx: BookContext) -> list[plan_svc.Choice]:
    tokens = [f.get("token") for f in files]
    if not all(isinstance(t, str) for t in tokens) or len(set(tokens)) != len(tokens):
        raise _bad()                                       # each staged file is planned at most once
    store = _staging(request)
    try:
        b = store.find(ctx.user_id, ctx.book.id, batch_id, now())
    except staging.StagingRefused as e:
        raise _refuse(e) from None
    if len(files) > len(b.files):
        raise _bad()
    ids = [f.get("account_id") for f in files]
    if any(i is None for i in ids):
        raise _bad(NOT_READY)
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise _bad()
    accounts = {a.id: a for a in db.scalars(select(Account).options(joinedload(Account.institution))
                                            .where(Account.id.in_(set(ids))))}
    out: list[plan_svc.Choice] = []
    t = today()
    for f, aid in zip(files, ids):
        staged = b.files.get(f["token"])
        if staged is None:
            raise _refuse(staging.StagingRefused(410, staging.EXPIRED))
        if aid not in accounts:
            raise _bad(NO_ACCOUNT, 404)
        sent = _sent_layout(staged, f.get("layout"))
        layout = sent or staged.layout
        if layout is not None and (layout.state == "new" and sent is None or
                                   (layout.needs_sign and layout.negate is None) or layout.date_format is None):
            raise _bad(NOT_READY)
        try:
            parsed = store.parsed_for(b, staged, layout, t, now()) if layout is not None else staged.parsed
        except staging.StagingRefused as e:
            raise _refuse(e) from None
        out.append(plan_svc.Choice(staged, accounts[aid], layout, parsed, _rows(f.get("include", []), len(parsed.rows)),
                                   sent is not None))
    return out


@router.post("/batch/preview")
@viewer_ok
@not_recorded("A preview reads the files and saves nothing.")
def batch_preview(request: Request, body: dict = Depends(json_object), db: Session = Depends(book_db),
                  ctx: BookContext = Depends(open_book)):
    """Plain def (threadpool), under a plain read transaction (plan Engineering choice 7)."""
    begin_read(db)
    _, choices, sf_include = _choices(request, body, db, ctx)
    out = plan_svc.preview_out(plan_svc.build(db, choices, sf_include))
    holdings = _holdings_line(db, choices)
    return {**out, "balances": _balances(db, choices), "holdings": holdings,
            "writes": out["new"] + _rowless_writes(db, choices)}


def _has_holdings(db: Session, c: plan_svc.Choice) -> bool:
    return db.scalar(select(Holding.id).where(Holding.account_id == c.account.id, Holding.as_of == c.staged.period[1])
                     .limit(1)) is not None


def _kept_days(db: Session, choices: list[plan_svc.Choice]) -> tuple[list[bool], list[bool]]:
    """Per choice, as the commit will find it: is the day's holdings, and the day's balance, already there? An earlier
    statement in the same batch for the same account and day writes them first, so a later one is kept (P38, P39)."""
    held_days: set[tuple[int, date]] = set()
    balance_days: set[tuple[int, date]] = set()
    held, balance = [], []
    for c in choices:
        if not plan_svc.is_statement(c):
            held.append(False)
            balance.append(False)
            continue
        key = (c.account.id, c.staged.period[1])
        held.append(bool(c.staged.holdings) and (key in held_days or _has_holdings(db, c)))
        balance.append(c.staged.facts.get("closing_cents") is not None and
                       (key in balance_days or db.get(BalanceSnapshot, key) is not None))
        if c.staged.holdings:
            held_days.add(key)
        if c.staged.facts.get("closing_cents") is not None:
            balance_days.add(key)
    return held, balance


def _holdings_line(db: Session, choices: list[plan_svc.Choice]) -> dict:
    """Spec, Batch preview and commit: "Holdings {n} statements", each day already holding positions kept (P39)."""
    rows = []
    for c, kept in zip(choices, _kept_days(db, choices)[0]):
        if not plan_svc.is_statement(c) or not c.staged.holdings:
            continue
        rows.append({"account": c.account.name, "as_of": c.staged.period[1].isoformat(), "count": len(c.staged.holdings),
                     "kept": kept})
    return {"n": len(rows), "kept": sum(r["kept"] for r in rows), "rows": rows}


def _rowless_writes(db: Session, choices: list[plan_svc.Choice]) -> int:
    """Pre-flight F22: what an investment or loan statement (no rows) will save: its holdings, else its balance, so a
    batch of only those is still importable."""
    n = 0
    for c, held, balance in zip(choices, *_kept_days(db, choices)):
        if not plan_svc.is_statement(c) or c.parsed.rows:
            continue
        if c.staged.holdings and not held:
            n += len(c.staged.holdings)
        elif c.staged.facts.get("closing_cents") is not None and not balance:
            n += 1
    return n


def _balances(db: Session, choices: list[plan_svc.Choice]) -> dict:
    """P38's preview line: each statement's closing balance for its period end, and whether one is already there."""
    rows = []
    for c, kept in zip(choices, _kept_days(db, choices)[1]):
        if not plan_svc.is_statement(c) or c.staged.facts.get("closing_cents") is None:
            continue
        closing, as_of = c.staged.facts["closing_cents"], c.staged.period[1]
        cents = -closing if c.staged.facts.get("kind") in OWED else closing
        rows.append({"account": c.account.name, "as_of": as_of.isoformat(), "cents": cents, "kept": kept})
    return {"n": len(rows), "kept": sum(r["kept"] for r in rows), "rows": rows}


def _decode(raw: bytes) -> str:
    """Kept for the investments upload (api/investments.py), which still reads its CSV as multipart text."""
    try:
        return raw.decode("utf-8").lstrip("﻿")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


CHANGED = "Something changed since the preview. Check the new numbers."
NO_IMPORT = "That import doesn't exist."
ALREADY_UNDONE = "That import was already undone."


def _default_label(acct: Account) -> str:
    """Plan Engineering choice 3: the institution at first save, or the account's name for a manual account."""
    name = acct.name if acct.institution.source == Source.manual else acct.institution.name
    return name[:LABEL_MAX]


def _save_layouts(db: Session, choices: list[plan_svc.Choice], t) -> dict[str, int]:
    """Saved at commit (P14): a new layout once per key (reusing a forgotten row), a remembered one's last use."""
    ids: dict[str, int] = {}
    for c in choices:
        lay = c.layout
        if c.parsed.held or lay is None or lay.state in ("known", "builtin"):
            continue
        if lay.state == "new":
            row = db.scalar(select(ImportLayout).where(ImportLayout.key == lay.key))
            if row is None:
                row = ImportLayout(key=lay.key, header=json.dumps(list(c.staged.table.header)), created_at=t, uses=0)
                db.add(row)
            row.label = lay.label or _default_label(c.account)
            row.forgotten_at = None
        else:
            row = db.get(ImportLayout, lay.id)
            if row is None:
                continue
        if c.sent:
            row.mapping, row.negate, row.date_format = json.dumps(lay.mapping), bool(lay.negate), lay.date_format
        row.last_used_at, row.uses, row.account_id = t, (row.uses or 0) + 1, c.account.id
        db.flush()
        ids[c.staged.token] = row.id
    return ids


def _save_hints(db: Session, choices: list[plan_svc.Choice], t) -> None:
    for c in choices:
        if c.staged.hint_key and not c.parsed.held:
            hint = db.get(ImportHint, c.staged.hint_key)
            if hint is None:
                db.add(ImportHint(key=c.staged.hint_key, account_id=c.account.id, updated_at=t))
            else:
                hint.account_id, hint.updated_at = c.account.id, t


def _statement_extras(db: Session, c: plan_svc.Choice, b: ImportBatch, t, me: int, set_id: int,
                      kept_holdings: list[str]) -> tuple[date | None, int]:
    """P38, P39, P23, spec step 5: the closing balance and the day's holdings (never over ones already there), the
    layout's use, the stage gone. Returns the kept balance's day and what was written (holdings, else the balance)."""
    st, f = c.staged, c.staged.facts
    kept, wrote = None, 0
    if f.get("closing_cents") is not None:
        cents = -f["closing_cents"] if f.get("kind") in OWED else f["closing_cents"]
        if db.get(BalanceSnapshot, (c.account.id, st.period[1])) is None:
            db.add(BalanceSnapshot(account_id=c.account.id, as_of=st.period[1], balance_cents=cents))
            b.snapshot_as_of, b.snapshot_cents = st.period[1], cents
            wrote = 1
        else:
            kept = st.period[1]
    if st.holdings:
        as_of = st.period[1]
        if _has_holdings(db, c):
            kept_holdings.append(as_of.isoformat())
        else:
            pi = PositionsImport(account_id=c.account.id, as_of=as_of, filename=st.name[:200], row_count=len(st.holdings),
                                 imported_at=t, imported_by=me, source="pdf_scan" if st.scan else "pdf", set_id=set_id,
                                 batch_id=b.id, period_start=st.period[0], check_state=b.check_state,
                                 balance_cents=f.get("closing_cents"), snapshot_as_of=b.snapshot_as_of)
            db.add(pi)
            db.flush()
            replace_holdings(db, c.account.id, as_of, [Position(h["symbol"], h["name"], h["shares_milli"], h["value_cents"])
                                                       for h in st.holdings], import_id=pi.id)
            log_event(db, "info", "import", f"Imported {len(st.holdings)} holdings into {c.account.name} from {st.name}")
            wrote = len(st.holdings)
    if st.layout_id is not None:
        row = db.get(StatementLayout, st.layout_id)
        if row is not None:
            row.uses, row.last_used_at, row.account_id = (row.uses or 0) + 1, t, c.account.id
    db.execute(delete(StatementStage).where(StatementStage.id == st.stage_id))
    db.flush()
    return kept, wrote


def _parent_hooks(db: Session) -> None:
    after_new_data(db, today(), IMPORT_FAILED)
    run_safely(db, lambda s: watch_after(s, "import"), WATCH_FAILED["import"])


@router.post("/batch/commit", status_code=201)
@viewer_ok
@recorded
def batch_commit(request: Request, body: dict = Depends(json_object), me: User = Depends(current_user),
                 db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P18: the preview's request plus its digest. The server recomputes everything and never trusts the client's
    counts. P19: the rules for every kept row, then the model once for the batch (INLINE_ROWS shared), with no
    transaction open. Then, under the write lock, the plan once more (Engineering choice 7) and one transaction."""
    digest = body.get("digest")
    if not isinstance(digest, str):
        raise _bad()
    begin_read(db)
    batch_id, choices, sf_include = _choices(request, body, db, ctx)
    plan = plan_svc.build(db, choices, sf_include)
    if plan.digest != digest:
        raise HTTPException(409, detail={"error": CHANGED, "preview": plan_svc.preview_out(plan)})
    kept = [[f.choice.parsed.rows[i] for i in f.new] for f in plan.files]
    found = [s for f, rows in zip(plan.files, kept) for s in rule_suggestions(db, rows, f.choice.account.type)]
    llm = model(request)
    examples = teaching_examples(db, llm)
    db.commit()
    filled = model_fill(llm, [r for rows in kept for r in rows], found, examples)
    again = plan_svc.build(db, choices, sf_include)          # the route's own BEGIN IMMEDIATE now
    if again.digest != digest or _statements_moved(db, choices):
        db.rollback()
        raise HTTPException(409, detail={"error": CHANGED, "preview": plan_svc.preview_out(again)})
    t = now()
    s = ImportSet(imported_at=t, imported_by=me.id)
    db.add(s)
    db.flush()
    layout_ids = _save_layouts(db, choices, t)
    _save_hints(db, choices, t)
    household = ctx.book.kind == "household"
    batches: list[ImportBatch] = []
    statements, added_up, kept_balances, kept_holdings = 0, 0, [], []
    extra_writes, wrote_into = 0, {}
    pos = 0
    for f, rows in zip(again.files, kept):
        c, new = f.choice, set(f.new)
        if c.parsed.held:
            continue
        statement = plan_svc.is_statement(c)
        extra = dict(period=c.staged.period, pages=c.staged.pages, statement_layout_id=c.staged.layout_id,
                     check_state="anyway" if c.staged.anyway else "adds_up",
                     check_gap_cents=c.staged.gap if c.staged.anyway else 0) if statement else {}
        b = svc.commit_batch(db, c.account.id, c.staged.name, ("pdf_scan" if c.staged.scan else "pdf") if statement else (c.layout.fmt if c.layout else "ofx"),
                             list(c.parsed.rows), me.id, [i not in new for i in range(len(c.parsed.rows))], t,
                             household=household, suggestions=filled[pos:pos + len(rows)], set_id=s.id,
                             layout_id=layout_ids.get(c.staged.token), content_sha256=c.staged.sha256, **extra)
        pos += len(rows)
        if statement:
            statements += 1
            added_up += not c.staged.anyway
            day, wrote = _statement_extras(db, c, b, t, me.id, s.id, kept_holdings)
            if day is not None:
                kept_balances.append(day.isoformat())
            if not c.parsed.rows and wrote:
                extra_writes += wrote
                wrote_into[c.account.id] = c.account.name
        batches.append(b)
        log_event(db, "info", "import", f"Imported {b.row_count} rows into {c.account.name} from {c.staged.name}")
        record(db, ctx, "import.add", target_id=b.id,
               after={"filename": c.staged.name, "rows": b.row_count, "account": c.account.name, "set": s.id})
    if household:
        run_safely(db, lambda x: match_all(x, today(), by=me.id), IMPORT_MATCH_FAILED)
    else:
        _parent_hooks(db)
    # Phase 17 spec 3.7: the receipt's "{n} to sort in Review": this commit's rows Review will ask about.
    ids = [b.id for b in batches]
    waiting = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.import_batch_id.in_(ids), Transaction.category == "uncategorized",
        Transaction.is_transfer.is_(False), Transaction.reviewed_at.is_(None))) if ids else 0
    duplicates = len(duplicate_pairs(db, limit=None, batch_ids=ids)) if ids else 0   # issue #32: the other reason
    db.commit()
    if batch_id is not None:
        _staging(request).drop(batch_id)
    into = {f.choice.account.id: f.choice.account.name for f in again.files if f.new} | wrote_into
    days = [r.posted_at for r in again.new_rows()]
    return {"set_id": s.id, "imported": sum(b.row_count for b in batches) + extra_writes, "accounts": len(into),
            "account": next(iter(into.values())) if len(into) == 1 else None,
            "skipped": sum(len(f.already) + len(f.simplefin) + len(f.same) for f in again.files),
            "months": plan_svc.months(min(days), max(days)) if days else 0, "batch_ids": [b.id for b in batches],
            "waiting": waiting, "duplicates": duplicates, "statements": statements, "added_up": added_up, "kept_balances": kept_balances,
            "kept_holdings": kept_holdings}


def _batch_out(b: ImportBatch, names: dict[int, str]) -> dict:
    return {"id": b.id, "account_id": b.account_id, "account_name": names.get(b.account_id), "filename": b.filename,
            "format": b.format, "row_count": b.row_count, "imported_at": b.imported_at.isoformat(),
            "imported_by": b.imported_by, "rolled_back_at": b.rolled_back_at.isoformat() if b.rolled_back_at else None,
            "period_end": b.period_end.isoformat() if b.period_end else None, "check_state": b.check_state,
            "check_gap_cents": b.check_gap_cents}


@router.get("/batches")
def batches(db: Session = Depends(book_db)):
    """Past imports grouped by batch, newest first (P20); a legacy file (no set) is a batch of one."""
    names = dict(db.execute(select(Account.id, Account.name)).all())
    sets = {s.id: s for s in db.scalars(select(ImportSet))}
    groups: dict[tuple, list[ImportBatch]] = {}
    for b in svc.list_batches(db):
        groups.setdefault(("s", b.set_id) if b.set_id else ("b", b.id), []).append(b)
    out = []
    for (kind, key), files in groups.items():
        files.sort(key=lambda b: b.id)
        s = sets.get(key) if kind == "s" else None
        gone = [b.rolled_back_at for b in files]
        rolled = (s.rolled_back_at if s is not None and s.rolled_back_at else max(gone) if all(gone) else None)
        out.append({"set_id": s.id if s else None, "imported_at": (s or files[0]).imported_at.isoformat(),
                    "imported_by": (s or files[0]).imported_by, "rolled_back_at": rolled.isoformat() if rolled else None,
                    "files": [_batch_out(b, names) for b in files]})
    return {"imports": out}


@member_router.get("/batches/{bid}")
def batch_one(bid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """Plan-owned (Engineering choice 4): one file, for "Show all N from this file"'s bar. Any member reads it; only a
    manager is offered its Undo."""
    b = db.get(ImportBatch, bid)
    if b is None:
        raise HTTPException(404, detail={"error": NO_IMPORT})
    rows_in = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.import_batch_id == bid))
    names = dict(db.execute(select(Account.id, Account.name).where(Account.id == b.account_id)).all())
    return {**_batch_out(b, names), "rows_in": rows_in, "undoable": ctx.is_manager and b.rolled_back_at is None}


def _undo_holdings(db: Session, b: ImportBatch) -> None:
    svc.undo_holdings(db, b.id, now())


@router.post("/sets/{sid}/rollback")
@viewer_ok
@recorded
def rollback_set(sid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P20: every file of the batch still in, in one transaction, each logged and recorded as today; the parent hooks
    once (Engineering choice 17)."""
    s = db.get(ImportSet, sid)
    if s is None:
        raise HTTPException(404, detail={"error": NO_IMPORT})
    live = db.scalars(select(ImportBatch).where(ImportBatch.set_id == sid, ImportBatch.rolled_back_at.is_(None))
                      .order_by(ImportBatch.id)).all()
    if not live:
        raise HTTPException(409, detail={"error": ALREADY_UNDONE})
    total, kept = 0, []
    for b in live:
        n = svc.rollback_batch(db, b.id, now())
        kept.append(svc.undo_snapshot(db, b))
        _undo_holdings(db, b)
        total += n
        log_event(db, "info", "import", f"Undid an import of {n} rows")
        record(db, ctx, "import.undo", target_id=b.id, after={"filename": b.filename, "rows": n})
    s.rolled_back_at = now()
    if ctx.book.kind == "parent":
        _parent_hooks(db)
    db.commit()
    return {"deleted": total, "kept": [KEPT.format(day=_month_day(d)) for d in kept if d]}


@router.post("/batches/{bid}/rollback")
@viewer_ok
@recorded
def rollback(bid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    batch = db.get(ImportBatch, bid)
    filename = batch.filename if batch else None
    try:
        n = svc.rollback_batch(db, bid, now())
    except ValueError as e:
        missing = str(e) == "That import doesn't exist."
        raise HTTPException(404 if missing else 409, detail={"error": str(e)}) from None
    kept = svc.undo_snapshot(db, batch)
    _undo_holdings(db, batch)
    log_event(db, "info", "import", f"Undid an import of {n} rows")
    record(db, ctx, "import.undo", target_id=bid, after={"filename": filename, "rows": n})
    if ctx.book.kind == "parent":
        _parent_hooks(db)
    db.commit()
    return {"deleted": n, "kept": [KEPT.format(day=_month_day(kept))] if kept else []}


LAYOUTS_NOT_RECORDED = "A remembered layout is how files are read, not the book's money."
NAME_RULE = "Give it a name, up to 60 characters."
NO_LAYOUT = "That layout isn't here anymore."


def _layout_row(row: ImportLayout) -> dict:
    return {"id": row.id, "label": row.label, "kind": "csv", "header": json.loads(row.header),
            "mapping": {k: int(v) for k, v in json.loads(row.mapping).items()}, "negate": row.negate,
            "date_format": row.date_format, "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "uses": row.uses, "account_id": row.account_id}      # plan-owned: Edit words the sign for the account's kind


def _live_layout(db: Session, lid: int) -> ImportLayout:
    row = db.get(ImportLayout, lid)
    if row is None or row.forgotten_at is not None:
        raise HTTPException(404, detail={"error": NO_LAYOUT})
    return row


def _purge_forgotten(db: Session, t) -> None:
    """Engineering choice 1: a forgotten layout goes for good once its 15-minute Undo has passed (at a layout write)."""
    db.execute(delete(ImportLayout).where(ImportLayout.forgotten_at.is_not(None), ImportLayout.forgotten_at <= t - TTL))


@router.get("/layouts")
def list_layouts(db: Session = Depends(book_db)):
    """CSV layouts and statement layouts together (PDF statements spec, Remembered layouts), most recently used first."""
    rows = [_layout_row(r) for r in db.scalars(select(ImportLayout).where(ImportLayout.forgotten_at.is_(None)))]
    rows += [{"id": r.id, "label": r.label, "kind": "statement", "statement_kind": r.kind,
              "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None, "uses": r.uses,
              "account_id": r.account_id}
             for r in db.scalars(select(StatementLayout).where(StatementLayout.forgotten_at.is_(None)))]
    rows.sort(key=lambda x: x["label"])
    rows.sort(key=lambda x: x["last_used_at"] or "", reverse=True)        # stable: by label within a tie, unused last
    return {"layouts": rows}


@router.patch("/layouts/{lid}")
@viewer_ok
@not_recorded(LAYOUTS_NOT_RECORDED)
def edit_layout(lid: int, body: dict = Depends(json_object), db: Session = Depends(book_db),
                ctx: BookContext = Depends(open_book)):
    """P14's Edit: checked against the stored header (no sample rows: files aren't kept)."""
    row = _live_layout(db, lid)
    changes: dict = {}
    if "label" in body:
        changes["label"] = body_text(body["label"], NAME_RULE, LABEL_MAX)
    if "mapping" in body:
        try:
            changes["mapping"] = json.dumps(mapping_from(body["mapping"], len(json.loads(row.header))))
        except ValueError as e:
            raise _bad(str(e)) from None
    if "negate" in body:
        if not isinstance(body["negate"], bool):
            raise _bad()
        changes["negate"] = body["negate"]
    if "date_format" in body:
        if body["date_format"] not in D.CANDIDATES:
            raise _bad()
        changes["date_format"] = body["date_format"]
    mapping = json.loads(changes.get("mapping", row.mapping))
    if "direction" in mapping or ("amount" not in mapping and "debit" in mapping and "credit" in mapping):
        changes["negate"] = False                 # the columns say the sign, so a kept negate would flip every row
    t = now()
    _purge_forgotten(db, t)
    with capturing(db, ctx.user_id, "layout", t) as cap:
        for k, v in changes.items():
            setattr(row, k, v)
    db.commit()
    return {"layout": _layout_row(row), "undo": cap.token}


@router.delete("/layouts/{lid}")
@viewer_ok
@not_recorded(LAYOUTS_NOT_RECORDED)
def forget_layout(lid: int, db: Session = Depends(book_db), ctx: BookContext = Depends(open_book)):
    """P14's Forget, with "Forgot {label} · Undo" through the journal."""
    row = _live_layout(db, lid)
    t = now()
    _purge_forgotten(db, t)
    with capturing(db, ctx.user_id, "forget", t) as cap:
        row.forgotten_at = t
    db.commit()
    return {"undo": cap.token}
