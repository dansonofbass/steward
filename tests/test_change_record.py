from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from steward.db.directory_models import User
from steward.db.models import ChangeRecord, InventoryItem
from steward.deps import BookContext
from steward.inventory.changes import changed, describe, labels_for, record, record_system
from tests.factories import login

TODAY = date(2026, 10, 18)
OWNERS = {"margaret": "Margaret", "robert-husband": "Robert (husband)", "joint": "Joint"}


def _item(mdb, name, kind="insurance", institution=None, last4=None, status="confirmed"):
    i = InventoryItem(kind=kind, name=name, owner="margaret", institution=institution, last4=last4, status=status,
                      details="{}", data_source="manual")
    mdb.add(i)
    mdb.flush()
    return i


def test_household_books_record_nothing(books, ours, db):
    ctx = BookContext(ours, "manager", 1, ())
    assert record(db, ctx, "txn.edit", after={"category": "dining"}) is None
    assert db.scalar(select(ChangeRecord.id)) is None


def test_changed_keeps_only_what_differs():
    assert changed({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": None}) == ({"b": 2}, {"b": 3})


def test_an_edit_reads_as_old_and_new_values(mdb, mctx):
    home = _item(mdb, "Homeowners")
    checking = _item(mdb, "Joint checking", kind="account", institution="Wells Fargo", last4="4417")
    card = _item(mdb, "Citi card", kind="account", institution="Citi", last4="9012")
    row = record(mdb, mctx, "item.edit", target_id=home.id, item_id=home.id,
                 before={"renewal_on": None, "paid_from_id": card.id},
                 after={"renewal_on": "2026-03-01", "paid_from_id": checking.id},
                 note="From the renewal notice in the March mail")
    out = describe(row, "Robin", labels_for(mdb), OWNERS, TODAY)
    assert out["icon"] == "pencil" and out["text"] == "edited {item}"
    assert out["item"] == {"id": home.id, "label": "Homeowners"}
    assert out["diffs"] == [
        {"label": "Paid from", "before": "Citi card ••9012", "after": "Wells Fargo Joint checking ••4417"},
        {"label": "Renewal date", "before": "not known", "after": "Mar 1"},
    ]
    assert out["note"] == "From the renewal notice in the March mail"
    assert out["summary"] == "Robin edited Homeowners: paid from, renewal date"


def test_marking_confirmed_reads_as_marked(mdb, mctx):
    ira = _item(mdb, "Traditional IRA", kind="account", institution="Fidelity", last4="3390", status="needs_checking")
    row = record(mdb, mctx, "item.edit", target_id=ira.id, item_id=ira.id,
                 before={"status": "needs_checking"}, after={"status": "confirmed"})
    out = describe(row, "Robin", labels_for(mdb), OWNERS, TODAY)
    assert out["icon"] == "circle-check"
    assert out["diffs"] == [{"label": "Status", "before": "Needs checking", "after": "Confirmed"}]
    assert out["summary"] == "Robin marked Fidelity Traditional IRA ••3390 Confirmed"
    assert describe(row, "Robin", labels_for(mdb), OWNERS, TODAY, context="item")["text"] == "marked this item Confirmed"


def test_confirming_with_its_reason_cleared_still_reads_as_marked(mdb, mctx):
    ira = _item(mdb, "Traditional IRA", kind="account", institution="Fidelity", last4="3390", status="needs_checking")
    row = record(mdb, mctx, "item.edit", target_id=ira.id, item_id=ira.id,
                 before={"status": "needs_checking", "check_reason": "Seen in the mail"},
                 after={"status": "confirmed", "check_reason": None})
    out = describe(row, "Robin", labels_for(mdb), OWNERS, TODAY)
    assert out["icon"] == "circle-check"
    assert out["summary"] == "Robin marked Fidelity Traditional IRA ••3390 Confirmed"
    assert describe(row, "Robin", labels_for(mdb), OWNERS, TODAY, context="item")["text"] == "marked this item Confirmed"


def test_a_dismissal_names_the_parent_by_first_name(mdb, mctx):
    row = record(mdb, mctx, "suggestion.dismiss", after={"payer": "Westmark"})
    out = describe(row, "Robin", labels_for(mdb), OWNERS, TODAY)
    assert out["text"] == "answered Not Margaret's to a suggestion"


def test_closing_shows_the_date_only(mdb, mctx):
    chase = _item(mdb, "Savings", kind="account", institution="Chase", last4="6630")
    row = record(mdb, mctx, "item.close", target_id=chase.id, item_id=chase.id, before={"status": "confirmed"},
                 after={"status": "closed", "closed_on": "2025-02-14"}, note="Moved to Wells Fargo savings")
    out = describe(row, "JR", labels_for(mdb), OWNERS, TODAY)
    assert out["text"] == "closed {item}" and out["item"]["label"] == "Chase Savings ••6630"
    assert out["diffs"] == [{"label": "Closed on", "before": None, "after": "Feb 14, 2025"}]


def test_the_bank_feed_adds_items_without_a_person(mdb):
    i = _item(mdb, "Joint checking", kind="account", institution="Wells Fargo", last4="4417")
    row = record_system(mdb, "item.add", target_id=i.id, item_id=i.id, after={"from": "feed", "status": "confirmed"})
    out = describe(row, None, labels_for(mdb), OWNERS, TODAY, context="item")
    assert (out["who"], out["text"], out["lines"]) == (None, "Added from the bank feed",
                                                        ["Confirmed, because the feed reports it"])


def test_full_numbers_never_enter_a_row_unmasked(mdb, mctx):
    i = _item(mdb, "Medicare supplement")
    row = record(mdb, mctx, "item.edit", item_id=i.id, before={"number": None}, after={"number": "••0861"})
    out = describe(row, "JR", labels_for(mdb), OWNERS, TODAY)
    assert out["diffs"] == [{"label": "Policy number", "before": "not known", "after": "••0861"}]


def test_the_change_record_page(margaret, mdb, mctx, client, ddb, books):
    from steward.books.service import set_role
    i = _item(mdb, "Durable power of attorney", kind="document")
    record(mdb, mctx, "item.add", target_id=i.id, item_id=i.id,
           after={"kind": "document", "type": "power_of_attorney", "owner": "margaret", "status": "confirmed"})
    record(mdb, mctx, "file.add", target_id=7, item_id=i.id, after={"name": "POA.pdf", "type": "PDF", "size": 3_250_586})
    record_system(mdb, "item.add", target_id=i.id, item_id=i.id, after={"from": "feed", "status": "confirmed"})
    mdb.commit()
    vee = ddb.scalar(select(User.id).where(User.username == "vee"))
    set_role(ddb, margaret.id, vee, "manager", by=mctx.user_id)
    ddb.commit()

    login(client, "vee")   # now a manager; viewers see the page too (next test)
    out = client.get("/api/b/margaret-ellis/changes").json()
    texts = [c["text"] for c in out["changes"]]
    assert texts[0].startswith("made Vee a manager")
    assert "attached POA.pdf to {item}" in texts and "added {item}" in texts
    # the bank feed's own rows aren't listed (membership rows made by the fixture have no person, which is right)
    assert all(c["who"] is not None for c in out["changes"] if c["id"].startswith("c"))
    assert sum(c["text"] == "added {item}" for c in out["changes"]) == 1
    added = next(c for c in out["changes"] if c["text"] == "added {item}")
    assert added["lines"] == ["Document · power of attorney · Margaret · Confirmed"]
    files = client.get("/api/b/margaret-ellis/changes?kind=files").json()["changes"]
    assert [c["text"] for c in files] == ["attached POA.pdf to {item}"] and files[0]["lines"] == ["PDF · 3.1 MB"]
    members = client.get("/api/b/margaret-ellis/changes?kind=members").json()["changes"]
    assert all(c["id"].startswith("m") for c in members)
    mine = client.get(f"/api/b/margaret-ellis/changes?user_id={mctx.user_id}").json()["changes"]
    assert all(c["who"] == "Jr" for c in mine)
    assert {"id": mctx.user_id, "name": "Jr"} in out["people"]
    r = client.get("/api/b/margaret-ellis/changes?kind=nope")
    assert (r.status_code, r.json()) == (422, {"error": "Choose one of the kinds of change."})


def test_viewers_see_it_and_household_books_have_none(margaret, client):
    login(client, "vee")
    assert client.get("/api/b/margaret-ellis/changes").status_code == 200
    login(client, "jr")
    r = client.get("/api/b/ours/changes")
    assert (r.status_code, r.json()) == (404, {"error": "This book doesn't have that."})


def test_paging_goes_back_in_time(margaret, mdb, mctx, client):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for n in range(55):
        row = record(mdb, mctx, "item.reveal", item_id=None)
        row.at = t0 + timedelta(minutes=n)
    mdb.commit()
    login(client, "jr")
    first = client.get("/api/b/margaret-ellis/changes?kind=items").json()
    assert len(first["changes"]) == 50 and first["next"]
    second = client.get("/api/b/margaret-ellis/changes", params={"kind": "items", "before": first["next"]}).json()
    assert len(second["changes"]) == 5 and second["next"] is None
