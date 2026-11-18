"""GET /api/b/{slug}/ready: the eight rows of Get Steward ready, read live (guided setup spec 3.2, 3.3). Managers of
THE household book only (install_household: email, backups, the gateway and the key file belong to the whole install,
so an older install's second household book gets 404); it never writes. The gateway is asked before the first query,
so no transaction waits on it."""
from __future__ import annotations

import httpx2
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.advisor.state import chat_on, gateway_state
from steward.db.directory_models import Book, Membership
from steward.db.models import Account, AccountType, EventLog, ImportBatch, SimplefinLink, Transaction
from steward.deps import BookContext, book_db, directory_db, install_household, managers_only, now, open_book, today
from steward.events import visible_to
from steward.services import ready as rows
from steward.services.plan_inputs import setup_items
from steward.services.profile import FINISHED, missing, section_states
from steward.services.review import waiting_filter
from steward.services.scheduled_backup import read_last
from steward.services.simplefin.sync import SYNC_FAILED, needs_sign_in

router = APIRouter(prefix="/ready", dependencies=[Depends(open_book), Depends(install_household), Depends(managers_only)])

NOT_MONEY = (AccountType.mortgage, AccountType.property, AccountType.vehicle)
PROBE_S = 3


def _reachable(request: Request, url: str) -> bool:
    try:
        (request.app.state.http or httpx2).get(url.rstrip("/") + "/v1/health", timeout=PROBE_S)
    except httpx2.HTTPError:
        return False
    return True


@router.get("")
def ready(request: Request, origin: str | None = None, db: Session = Depends(book_db),
          ddb: Session = Depends(directory_db), ctx: BookContext = Depends(open_book)) -> dict:
    app = request.app
    settings, store, rt = app.state.settings, app.state.app_settings, app.state.advisor
    url = settings.gateway_url or None
    paired = rt.client is not None
    health = rt.monitor.fresh(10.0) if paired else None          # before the first query: no transaction is open
    reachable = _reachable(request, url) if url and not paired else None
    state = gateway_state(health, True) if paired else None
    at, day = now(), today()

    states = section_states(db)
    required = [i for i in setup_items(db, day) if i.required]
    link = db.scalar(select(SimplefinLink).order_by(SimplefinLink.id))
    failed = db.scalar(visible_to(select(EventLog.id), ctx.is_manager).where(
        EventLog.message == SYNC_FAILED, EventLog.resolved_at.is_(None)).limit(1)) is not None
    accounts = db.scalar(select(func.count()).select_from(Account).where(
        Account.is_active.is_(True), Account.type.not_in(NOT_MONEY))) or 0
    last_import = db.scalar(select(func.max(ImportBatch.imported_at)).where(ImportBatch.rolled_back_at.is_(None)))
    waiting = db.scalar(select(func.count()).select_from(Transaction).where(waiting_filter(at))) or 0
    parents = list(ddb.scalars(select(Book.name).join(Membership, Membership.book_id == Book.id).where(
        Book.kind == "parent", Membership.user_id == ctx.user_id, Membership.role == "manager",
        Book.archived_at.is_(None)).order_by(Book.id)))
    chat = chat_on(db)

    eff = store.effective()
    out = [
        rows.household_row(sum(s.status in FINISHED for s in states), len(states), sum(i.done for i in required),
                           len(required), next((s.key for s in states if s.status not in FINISHED), None)),
        rows.money_row(money_in=missing(db)["banks"] == [], linked=link is not None,
                       last_sync=link.last_sync_at if link else None, sync_failed=failed, accounts=accounts,
                       last_import=last_import, waiting=waiting, today=day, sign_in=needs_sign_in(db)),
        rows.ask_row(url=url, paired=paired, reachable=reachable, state=state, chat_on=chat,
                     accelerator=(health or {}).get("accelerator")),
        rows.email_row(eff=eff, configured=store.email() is not None, last=store.last_mail(),
                       version=store.email_version(), today=day),
        rows.backups_row(at=store.value("backup.at"), last=read_last(app.state.books.directory),
                         newest=rows.newest_copy(settings.backups_dir), now=at, folder=str(settings.backups_dir)),
        rows.someone_row(parents),
        rows.address_row(base_url=settings.base_url, trusted_proxies=settings.trusted_proxies,
                         scheme=request.url.scheme, origin=rows.clean_origin(origin),
                         peer=request.client.host if request.client else ""),
        rows.key_row(key_file=settings.key_file, key_path=settings.key_path, data_dir=settings.data_dir),
    ]
    db.rollback()
    return {"rows": [r.as_dict() for r in out], "need": sum(r.status == "needs" for r in out)}
