"""Low balances (spec 4.1; ruling 11) and new accounts from the bank feed (ruling 13)."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from steward.db.models import ChangeRecord, Flag, InventoryItem
from steward.inventory.changes import describe, labels_for
from steward.inventory.items import FLOOR_RULE, ItemRefused, edit_item
from steward.services.accounts import record_balance
from steward.watch.balances import check_low, check_new_accounts
from steward.watch.run import run_watch
from tests.watch_helpers import NOW, TODAY, account, d


def _item(db, acct) -> InventoryItem:
    return db.scalar(select(InventoryItem).where(InventoryItem.account_id == acct.id))


def _floor(db, ctx, acct, cents) -> None:
    edit_item(db, ctx, _item(db, acct), {"details": {"floor_cents": cents}}, today=TODAY)
    db.commit()


def test_floors_go_on_cash_accounts_only(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings")
    card = account(mdb, "Citi card", "credit_card", owner="margaret")
    _floor(mdb, mctx, save, 2_500_000)
    item = _item(mdb, save)
    assert json.loads(item.details)["floor_cents"] == 2_500_000
    row = mdb.scalar(select(ChangeRecord).where(ChangeRecord.action == "item.edit"))
    out = describe(row, "Jr", labels_for(mdb), {}, TODAY, context="item")
    assert out["diffs"] == [{"label": "Low-balance floor", "before": "none", "after": "$25,000.00"}]
    with pytest.raises(ItemRefused, match=FLOOR_RULE):
        edit_item(mdb, mctx, _item(mdb, card), {"details": {"floor_cents": 100}}, today=TODAY)
    mdb.rollback()
    edit_item(mdb, mctx, _item(mdb, save), {"details": {"type": "brokerage"}}, today=TODAY)
    assert "floor_cents" not in json.loads(_item(mdb, save).details)


def test_a_low_balance_is_flagged_once_per_dip(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    _floor(mdb, mctx, save, 2_500_000)
    [fid] = check_low(mdb, TODAY, NOW, after="sync")
    f = mdb.get(Flag, fid)
    assert (f.check, f.severity, f.summary, f.title) == (
        "low", "normal", "Way2Save savings is under its $25,000.00 floor", "Way2Save savings is under its floor")
    facts = json.loads(f.facts)
    assert (facts["balance_cents"], facts["floor_cents"], facts["as_of"]) == (2_248_010, 2_500_000, "2026-10-18")
    assert f.item_id == _item(mdb, save).id and f.account_id == save.id
    assert check_low(mdb, TODAY, NOW, after="sync") == []               # the same dip
    f.status, f.resolved_at = "handled", NOW
    record_balance(mdb, save.id, TODAY, 2_600_000)
    assert check_low(mdb, TODAY, NOW, after="sync") == []               # back above the floor
    record_balance(mdb, save.id, TODAY + timedelta(days=1), 2_400_000)
    assert len(check_low(mdb, TODAY + timedelta(days=1), NOW, after="daily")) == 1


def test_a_new_floor_checks_again_and_future_balances_are_ignored(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings")
    record_balance(mdb, save.id, TODAY + timedelta(days=3), 100)
    mdb.commit()
    _floor(mdb, mctx, save, 2_500_000)
    assert check_low(mdb, TODAY, NOW, after="sync") == []               # dated after today
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    [first] = check_low(mdb, TODAY, NOW, after="sync")
    mdb.get(Flag, first).status = "expected"
    _floor(mdb, mctx, save, 2_300_000)
    assert len(check_low(mdb, TODAY, NOW, after="sync")) == 1           # a new floor is a new dip


def test_changing_a_floor_refreshes_the_open_flags_summary(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    _floor(mdb, mctx, save, 2_500_000)
    [fid] = check_low(mdb, TODAY, NOW, after="sync")
    _floor(mdb, mctx, save, 2_300_000)                                  # still under the new floor
    assert check_low(mdb, TODAY, NOW, after="sync") == []               # the same flag stays open, no second one
    f = mdb.get(Flag, fid)
    assert f.summary == "Way2Save savings is under its $23,000.00 floor"
    assert json.loads(f.facts)["floor_cents"] == 2_300_000
    assert len(mdb.scalars(select(Flag)).all()) == 1


def test_lowering_the_floor_below_the_balance_updates_the_open_flag(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    _floor(mdb, mctx, save, 2_500_000)
    [fid] = check_low(mdb, TODAY, NOW, after="sync")
    _floor(mdb, mctx, save, 2_000_000)                                  # the balance is above it now
    assert check_low(mdb, TODAY, NOW, after="sync") == []
    f = mdb.get(Flag, fid)
    assert "$25,000.00" not in f.summary
    assert f.summary == "Way2Save savings is back above its $20,000.00 floor"
    assert json.loads(f.facts)["floor_cents"] == 2_000_000


def test_a_recovered_balance_does_not_leave_the_flag_saying_under(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    _floor(mdb, mctx, save, 2_500_000)
    [fid] = check_low(mdb, TODAY, NOW, after="sync")
    record_balance(mdb, save.id, TODAY, 2_600_000)
    assert check_low(mdb, TODAY, NOW, after="sync") == []
    assert mdb.get(Flag, fid).summary == "Way2Save savings is back above its $25,000.00 floor"


def test_a_check_for_one_account_leaves_the_others_alone(margaret, mdb, mctx):
    a = account(mdb, "Way2Save savings", "savings", feed=True)
    b = account(mdb, "Premier savings", "savings", feed=True)
    for acct in (a, b):
        record_balance(mdb, acct.id, d(1), 100_000)
    mdb.commit()
    _floor(mdb, mctx, a, 500_000)
    _floor(mdb, mctx, b, 500_000)
    [fid] = check_low(mdb, TODAY, NOW, after="floor", account_id=a.id)
    assert mdb.get(Flag, fid).account_id == a.id
    assert len(mdb.scalars(select(Flag)).all()) == 1


def test_new_accounts_after_the_first_sync(margaret, mdb):
    account(mdb, "Joint checking", feed=True)
    assert check_new_accounts(mdb, NOW, after="sync") == []             # the first sync never raises one
    new = account(mdb, "Premier savings", "savings", feed=True)
    [fid] = check_new_accounts(mdb, NOW, after="sync")
    f = mdb.get(Flag, fid)
    assert (f.check, f.severity, f.account_id) == ("account", "normal", new.id)
    assert (f.summary, f.title) == ("Wells Fargo reports Premier savings, which wasn't in the inventory",
                                    "New account at Wells Fargo")
    assert check_new_accounts(mdb, NOW, after="sync") == []


def test_a_run_checks_balances_and_accounts_too(margaret, mdb, mctx):
    save = account(mdb, "Way2Save savings", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    _floor(mdb, mctx, save, 2_500_000)
    out = run_watch(mdb, TODAY, NOW, after="sync")
    assert [mdb.get(Flag, i).check for i in out.flags] == ["low"]


def test_a_floor_changed_on_one_account_raises_no_dip_on_another(margaret, mdb, mctx):
    a = account(mdb, "Way2Save savings", "savings", feed=True)
    b = account(mdb, "Joint checking", "checking", feed=True, institution="Other Bank")
    for acct in (a, b):
        record_balance(mdb, acct.id, d(1), 100_000)
    mdb.commit()
    item_b = _item(mdb, b)
    item_b.details = json.dumps({**json.loads(item_b.details), "floor_cents": 500_000})     # under, not yet checked
    mdb.commit()
    _floor(mdb, mctx, a, 50_000)
    assert check_low(mdb, TODAY, NOW, after="floor", account_id=a.id) == []
    assert mdb.scalars(select(Flag).where(Flag.account_id == b.id)).all() == []
