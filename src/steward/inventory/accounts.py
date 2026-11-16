"""Accounts and their inventory items (spec 3.1; rulings 16, 17). In a parent book every account has its item: bank
feed accounts arrive Confirmed with data source feed, and accounts made before the inventory existed get one too."""
from __future__ import annotations

from steward import clock
import json
import logging
import re
from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from steward.db.models import Account, EventLog, ImportBatch, InventoryItem, Source
from steward.events import log_event, resolve_events_matching
from steward.inventory import kinds as K
from steward.inventory.changes import record_system
from steward.inventory.items import snapshot
from steward.inventory.present import log_safe

log = logging.getLogger("steward.inventory")
SYNC_FAILED = "Couldn't update the inventory after this sync."


def _last4(name: str) -> str | None:
    m = re.search(r"(\d{4})\D*$", name)
    return m.group(1) if m else None


def ensure_account_items(db: Session) -> int:
    """Adds the missing items. Never touches an existing item, so a closed one stays closed."""
    have = set(db.scalars(select(InventoryItem.account_id).where(InventoryItem.account_id.is_not(None))))
    imported = set(db.scalars(select(ImportBatch.account_id).distinct()))
    added = 0
    for acct in db.scalars(select(Account).order_by(Account.id)).all():
        if acct.id in have:
            continue
        feed = acct.source == Source.simplefin
        t = clock.now()
        type_ = K.ACCOUNT_TO_ACCOUNT_TYPE.get(acct.type)
        item = InventoryItem(kind="account", name=acct.name, owner=acct.owner,
                             institution=acct.institution.name if feed else None, last4=_last4(acct.name),
                             status="confirmed",
                             data_source="feed" if feed else "statement" if acct.id in imported else "manual",
                             account_id=acct.id, details=json.dumps({"type": type_}), created_at=t, updated_at=t)
        db.add(item)
        db.flush()
        record_system(db, "item.add", target_id=item.id, item_id=item.id,
                      after={**snapshot(item), "kind": "account", "from": "feed" if feed else "account"})
        if feed:
            resolve_events_matching(db, "system", f"New account '{acct.name}' from ", t)
            if type_ is None:
                log_event(db, "info", "system", f"New account '{acct.name}' from {acct.institution.name} is in the "
                                                "inventory. Set its type and owner there.", actionable=True)
        added += 1
    return added


def after_new_data(db: Session, today: date, failure: str) -> None:
    """After every sync or import in a parent book (spec 3.1, 3.3): items for new accounts, then suggestions. Each
    runs in its own savepoint, so a failure in the suggestions keeps the new items and the resolved notices. A failure
    is logged once; a run where both work clears it."""
    from steward.inventory import suggestions
    items_ok = run_safely(db, ensure_account_items, failure, once=True)
    suggestions_ok = run_safely(db, lambda s: suggestions.refresh(s, today), failure, once=True)
    if items_ok and suggestions_ok:
        resolve_events_matching(db, "system", failure, clock.now())


def run_safely(db: Session, hook: Callable[[Session], None], failure: str, *, once: bool = False) -> bool:
    """Runs a parent hook in a savepoint (ledger ruling 6). If it raises, its changes are undone and an error event
    is logged (with once=True, not again while the same one is still open); the caller's own work (the sync or import) still commits. The
    inventory must never lose a sync. Returns whether the hook finished."""
    try:
        with db.begin_nested():
            hook(db)
    except Exception as e:  # noqa: BLE001
        log.error("%s %s", failure, log_safe(e))      # no traceback: it can carry bank text and recipients
        if not once or db.scalar(select(EventLog.id).where(EventLog.kind == "system", EventLog.message == failure,
                                                           EventLog.resolved_at.is_(None)).limit(1)) is None:
            log_event(db, "error", "system", failure)
        return False
    return True


def parent_hook(kind: str) -> Callable[[Session], None] | None:
    """After a sync in a parent book: the inventory (items, suggestions), then the checks (spec 4.1). Each runs in
    its own savepoint, so a failure in one is logged and undone without touching the other or the sync."""
    if kind != "parent":
        return None

    def hook(db: Session) -> None:
        from steward.deps import today
        from steward.watch.run import WATCH_FAILED, watch_after
        after_new_data(db, today(), SYNC_FAILED)
        run_safely(db, lambda s: watch_after(s, "sync"), WATCH_FAILED["sync"])
    return hook
