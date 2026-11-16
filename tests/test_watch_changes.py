"""README screen 8: the change record's rows for flag actions and Watching settings, under the kind "Flags and
watching". What the checks do on their own is not here (it's in the flag's History)."""
import json

from sqlalchemy import select

from steward.db.directory_models import User
from steward.db.models import InventoryItem
from steward.inventory.changes import history_for, page, record
from steward.watch.flags import mark_checking, mark_expected, reopen
from steward.watch.store import add_flag
from tests.watch_helpers import NOW, TODAY

OWNERS = {"margaret": "Margaret", "robert-husband": "Robert (husband)", "joint": "Joint"}
DENTAL = {"payee": "Brea Family Dental", "payee_key": "BREA FAMILY DENTAL", "method": "card", "amount_cents": 64_000}


def _page(mdb, books, margaret, kind="watching"):
    return page(mdb, books.directory, margaret.id, user_id=None, kind=kind, before=None, today=TODAY,
                owners=OWNERS)["changes"]


def test_flag_actions_read_like_the_mockup(margaret, mdb, mctx, books):
    dup = add_flag(mdb, check="duplicate", severity="normal", summary="$64.18 at Ralphs on Oct 13 and again on Oct 14",
                   title="$64.18 at Ralphs, twice", facts={"amount_cents": 6418}, now=NOW, after="sync")
    mark_checking(mdb, mctx, dup, {"note": "Asked Margaret about two trips to Ralphs. Waiting to hear back."}, NOW)
    big = add_flag(mdb, check="large", severity="normal", summary="$640.00 to Brea Family Dental",
                   title="$640.00 to Brea Family Dental", facts=DENTAL, now=NOW, after="sync")
    mark_expected(mdb, mctx, big, {"scope": "about", "note": "Margaret's crown."}, NOW)
    mdb.commit()
    exp, chk = _page(mdb, books, margaret)
    assert (exp["who"], exp["icon"], exp["text"]) == ("Jr", "circle-check", "marked {item} Expected")
    assert exp["item"] == {"id": big.id, "label": "Large amount: $640.00 to Brea Family Dental",
                           "path": f"/look-into/{big.id}"}
    assert exp["diffs"] == [{"label": "Status", "before": "Open", "after": "Expected"},
                            {"label": "Known payees", "before": None, "after": "+ Brea Family Dental, $480 to $800"}]
    assert exp["note"] == "Margaret's crown."
    assert exp["summary"] == "Jr marked Large amount: $640.00 to Brea Family Dental Expected"
    assert (chk["icon"], chk["text"], chk["item"]["label"]) == ("hourglass", "marked {item} Still checking",
                                                                "Duplicate: $64.18 at Ralphs, twice")
    reopen(mdb, mctx, big, NOW)
    mdb.commit()
    again = _page(mdb, books, margaret)[0]
    assert (again["icon"], again["text"]) == ("flag", "reopened {item}")
    assert again["diffs"] == [{"label": "Status", "before": "Expected", "after": "Open"},
                              {"label": "Known payees", "before": "Brea Family Dental, $480 to $800", "after": None}]


def test_watching_settings_rows(margaret, mdb, mctx, books, ddb):
    vee = ddb.scalar(select(User).where(User.username == "vee"))
    item = InventoryItem(kind="account", name="Way2Save savings", owner="joint", institution="Wells Fargo",
                         status="confirmed", data_source="feed", details=json.dumps({"type": "savings"}))
    mdb.add(item)
    mdb.flush()
    record(mdb, mctx, "watch.floor", target_id=item.id, item_id=item.id, before={"floor_cents": None},
           after={"floor_cents": 2_500_000}, note="Six months of costs.")
    record(mdb, mctx, "watch.large", before={"large_cents": 75_000}, after={"large_cents": 50_000})
    record(mdb, mctx, "watch.emails", target_id=vee.id, before={"urgent": True, "summary": True},
           after={"urgent": False, "summary": False})
    record(mdb, mctx, "watch.known_remove", target_id=7, before={"known": "Zelle to K. Nguyen, any amount"},
           note="Paid in full for the fence.")
    mdb.commit()
    known, emails, large, floor = _page(mdb, books, margaret)
    assert (known["icon"], known["text"], known["diffs"]) == (
        "trash", "removed a known payee", [{"label": "Known payees", "before": "Zelle to K. Nguyen, any amount",
                                            "after": None}])
    assert (emails["icon"], emails["text"]) == ("mail", "changed Vee's emails")
    assert emails["diffs"] == [{"label": "Urgent", "before": "on", "after": "off"},
                               {"label": "Daily summary", "before": "on", "after": "off"}]
    assert (large["icon"], large["text"], large["diffs"]) == (
        "banknote", "changed the large amount", [{"label": "Flag money out of", "before": "$750.00", "after": "$500.00"}])
    assert (floor["icon"], floor["text"], floor["item"]) == ("trending-down", "set a low-balance floor on {item}",
                                                            {"id": item.id, "label": "Way2Save savings"})
    assert floor["diffs"] == [{"label": "Floor", "before": "none", "after": "$25,000.00"}]
    assert _page(mdb, books, margaret, kind="items") == []
    [hist] = history_for(mdb, books.directory, item.id, TODAY, OWNERS)
    assert hist["text"] == "set a low-balance floor" and hist["item"] is None
