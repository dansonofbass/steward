import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from steward.books.jobs import sync_all_books
from steward.db.models import Account, AccountType, ChangeRecord, EventLog, InventoryItem, Source, SimplefinLink
from tests.factories import login, make_account
from tests.fake_simplefin import make_fake

NOW = datetime(2026, 10, 18, 13, 10, tzinfo=timezone.utc)


def _link(books, book):
    with Session(books.engine_for(book)) as db:
        db.add(SimplefinLink(access_url="http://demo:demo@testserver/simplefin", claimed_at=NOW))
        db.commit()


def _sync(books, fake):
    with TestClient(fake) as http:
        return sync_all_books(books, http, None, NOW, ("testserver",))


def test_a_feed_account_arrives_as_a_confirmed_feed_item(books, margaret, mdb):
    fake, state = make_fake()
    state.add_account("wf", "Wells Fargo", "wf", "CHECKING 4417", 821455, int(NOW.timestamp()) - 3600, txns=[])
    _link(books, margaret)
    _sync(books, fake)
    mdb.rollback()
    item = mdb.scalar(select(InventoryItem))
    assert (item.kind, item.name, item.institution, item.last4, item.status, item.data_source, item.owner) == (
        "account", "CHECKING 4417", "Wells Fargo", "4417", "confirmed", "feed", "joint")
    assert json.loads(item.details) == {"type": None}
    row = mdb.scalar(select(ChangeRecord).where(ChangeRecord.item_id == item.id))
    assert (row.user_id, row.action, json.loads(row.after)["from"]) == (None, "item.add", "feed")
    open_notices = list(mdb.scalars(select(EventLog.message).where(EventLog.resolved_at.is_(None))))
    assert open_notices == ["New account 'CHECKING 4417' from Wells Fargo is in the inventory. Set its type and owner there."]


def test_a_closed_feed_item_stays_closed_and_is_not_added_again(books, margaret, mdb):
    fake, state = make_fake()
    state.add_account("wf", "Wells Fargo", "wf", "SAVINGS 6630", 0, int(NOW.timestamp()) - 3600, txns=[])
    _link(books, margaret)
    _sync(books, fake)
    mdb.rollback()
    item = mdb.scalar(select(InventoryItem))
    item.status, item.closed_on = "closed", datetime(2025, 2, 14).date()
    mdb.commit()
    _sync(books, fake)
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(InventoryItem)) == 1
    assert mdb.scalar(select(InventoryItem.status)) == "closed"


def test_household_books_get_no_items_from_a_sync(books, ours, db):
    fake, state = make_fake()
    state.add_account("wf", "Wells Fargo", "wf", "CHECKING 1", 100, int(NOW.timestamp()) - 3600, txns=[])
    _link(books, ours)
    _sync(books, fake)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Account)) == 1
    assert db.scalar(select(func.count()).select_from(InventoryItem)) == 0


def test_an_import_gives_its_account_a_statement_item(frozen, margaret, mdb, client):
    from pathlib import Path

    from tests.import_helpers import import_file
    a = make_account(mdb, "Joint checking")
    login(client, "jr")
    sample = Path(__file__).parent / "samples" / "chase_checking.csv"
    r = import_file(client, "chase_checking.csv", a.id, raw=sample.read_bytes(), slug="margaret-ellis")
    assert r.status_code == 201
    mdb.rollback()
    item = mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == a.id))
    assert (item.data_source, item.status, item.institution) == ("statement", "confirmed", None)


def test_start_up_gives_older_parent_accounts_their_items(books, margaret, ours, db):
    with Session(books.engine_for(margaret)) as mdb:
        make_account(mdb, "Old checking")
    make_account(db, "Ours checking")
    books.upgrade_all()
    with Session(books.engine_for(margaret)) as mdb:
        item = mdb.scalar(select(InventoryItem))
        assert (item.name, item.data_source, json.loads(item.details)) == ("Old checking", "manual", {"type": "checking"})
    db.rollback()
    assert db.scalar(select(func.count()).select_from(InventoryItem)) == 0


def test_linking_the_feed_from_the_app_adds_items_and_records_it(settings, books, margaret, ddb):
    import base64
    from steward.app import create_app
    fake, state = make_fake()
    state.add_account("wf", "Wells Fargo", "wf", "CHECKING 4417", 821455, int(NOW.timestamp()) - 3600, txns=[])
    token = base64.b64encode(b"http://testserver/claim/abc").decode()
    with TestClient(fake) as fake_http:
        app = create_app(settings, books, http=fake_http)
        with TestClient(app, base_url="https://nas.tail1234.ts.net") as c:
            login(c, "jr")
            assert c.post("/api/b/margaret-ellis/simplefin/link", json={"setup_token": token}).status_code == 201
            items = c.get("/api/b/margaret-ellis/inventory").json()["items"]
            assert [(i["name"], i["data_source"]) for i in items] == [("CHECKING 4417", "feed")]
            assert c.get("/api/b/margaret-ellis/changes?kind=bank_feed").json()["changes"][0]["text"] == \
                "connected the bank feed"


def test_a_failing_hook_keeps_the_synced_transactions(books, margaret, mdb):
    from steward.db.models import Transaction
    from steward.services.simplefin.sync import sync_now
    fake, state = make_fake()
    state.add_account("wf", "Wells Fargo", "wf", "CHECKING 4417", 821455, int(NOW.timestamp()) - 3600,
                      txns=[("t1", int(NOW.timestamp()) - 7200, -1250, "COFFEE")])
    _link(books, margaret)

    def boom(db):
        db.add(EventLog(level="info", kind="system", message="half done"))
        raise RuntimeError("the inventory broke")

    with TestClient(fake) as http:
        sync_now(books.engine_for(margaret), http, None, NOW, ("testserver",), after=boom)
    mdb.rollback()
    assert mdb.scalar(select(func.count()).select_from(Transaction)) == 1
    messages = list(mdb.scalars(select(EventLog.message)))
    assert "half done" not in messages
    assert "Couldn't update the inventory after this sync." in messages


def _broken_refresh(monkeypatch):
    from steward.inventory import suggestions
    real, state = suggestions.refresh, {"broken": True}

    def refresh(db, today):
        if state["broken"]:
            raise RuntimeError("suggestions broke")
        return real(db, today)
    monkeypatch.setattr(suggestions, "refresh", refresh)
    return state


def test_a_hook_failure_keeps_the_new_account_notice_resolved(margaret, mdb, monkeypatch):
    from steward.events import log_event
    from steward.inventory.accounts import parent_hook
    from tests.watch_helpers import account
    account(mdb, "CHECKING 4417", feed=True, item=False)
    log_event(mdb, "info", "system", "New account 'CHECKING 4417' from Wells Fargo needs its type and owner set in Settings",
              actionable=True)
    mdb.commit()
    _broken_refresh(monkeypatch)
    parent_hook("parent")(mdb)
    mdb.commit()
    notice = mdb.scalar(select(EventLog).where(EventLog.message.startswith("New account 'CHECKING 4417' from Wells Fargo needs")))
    assert notice.resolved_at is not None
    assert mdb.scalar(select(func.count()).select_from(InventoryItem)) == 1


def test_a_failing_hook_logs_the_inventory_failure_once_and_clears_it_after_a_good_run(margaret, mdb, monkeypatch):
    from steward.inventory.accounts import parent_hook
    msg = "Couldn't update the inventory after this sync."
    state = _broken_refresh(monkeypatch)
    for _ in range(3):
        parent_hook("parent")(mdb)
        mdb.commit()
    rows = list(mdb.scalars(select(EventLog).where(EventLog.message == msg)))
    assert len(rows) == 1 and rows[0].resolved_at is None
    state["broken"] = False
    parent_hook("parent")(mdb)
    mdb.commit()
    mdb.refresh(rows[0])
    assert rows[0].resolved_at is not None


def test_a_watch_that_fails_recovers_and_fails_again_shows_both_failures(margaret, mdb):
    from steward.inventory.accounts import run_safely
    from steward.watch.run import WATCH_FAILED
    msg = WATCH_FAILED["sync"]

    def boom(db):
        raise RuntimeError("the checks broke")

    run_safely(mdb, boom, msg)
    run_safely(mdb, lambda db: None, msg)         # a good run in between
    run_safely(mdb, boom, msg)
    mdb.commit()
    assert len(list(mdb.scalars(select(EventLog).where(EventLog.message == msg)))) == 2
