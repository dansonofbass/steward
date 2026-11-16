import json
from datetime import date

from sqlalchemy import select

from steward.db.models import Account, ChangeRecord, InventoryItem
from tests.factories import login, make_txn

BOOK = "/api/b/margaret-ellis/inventory"
POLICY = {"kind": "insurance", "name": "Medicare supplement", "owner": "margaret", "institution": "Globe Mutual",
          "number": "GM-55120-0861", "status": "needs_checking", "check_reason": "From a premium notice",
          "details": {"type": "supplement", "amount_cents": 18620, "frequency": "monthly", "usual_day": 15}}
CHECKING = {"kind": "account", "name": "Joint checking", "owner": "joint", "institution": "Wells Fargo",
            "last4": "4417", "status": "confirmed", "data_source": "statement", "details": {"type": "checking"},
            "balance_cents": 821455, "balance_on": "2026-10-13"}


def test_a_manager_adds_lists_and_opens_items(frozen, margaret, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/items", json=CHECKING)
    assert r.status_code == 201
    chk = r.json()
    assert chk["sub"] == "Wells Fargo · checking ••4417"
    assert (chk["amount_cents"], chk["total_group"], chk["owner_label"]) == (821455, "cash", "Joint")
    assert chk["joint_names"] == "Margaret and Robert (husband)"
    assert chk["balance"] == {"cents": 821455, "line": "From a statement, Oct 13"}
    pol = client.post(f"{BOOK}/items", json={**POLICY, "details": {**POLICY["details"], "paid_from_id": chk["id"]}}).json()
    assert pol["sub"] == "Globe Mutual · policy ••0861"
    assert (pol["amount_cents"], pol["amount_per"], pol["monthly_cents"]) == (18620, "mo", 18620)
    assert pol["refs"]["paid_from_id"] == {"id": chk["id"], "label": "Wells Fargo Joint checking ••4417"}
    assert pol["history"][0]["text"] == "added this item"
    items = client.get(BOOK).json()["items"]
    assert [i["name"] for i in items] == ["Joint checking", "Medicare supplement"]
    detail = client.get(f"{BOOK}/items/{chk['id']}").json()
    assert detail["paid_from_here"] == [{"id": pol["id"], "name": "Medicare supplement"}]


def test_the_full_number_appears_only_in_the_reveal(frozen, margaret, client, mdb):
    login(client, "jr")
    pol = client.post(f"{BOOK}/items", json=POLICY).json()
    client.patch(f"{BOOK}/items/{pol['id']}", json={"number": "GM-55120-7777", "note": "New card"})
    bodies = [client.get(BOOK).text, client.get(f"{BOOK}/items/{pol['id']}").text,
              client.get("/api/b/margaret-ellis/changes").text]
    assert all("55120" not in b for b in bodies)
    mdb.rollback()
    assert all("55120" not in (r.before or "") + (r.after or "") for r in mdb.scalars(select(ChangeRecord)))
    login(client, "vee")   # viewers may reveal too (design pass 5)
    r = client.post(f"{BOOK}/items/{pol['id']}/full-number")
    assert (r.status_code, r.json()) == (200, {"number": "GM-55120-7777"})
    history = client.get(f"{BOOK}/items/{pol['id']}").json()["history"]
    assert (history[0]["who"], history[0]["text"]) == ("Vee", "showed the full number")


def test_viewers_read_but_cannot_write(margaret, client):
    login(client, "jr")
    pol = client.post(f"{BOOK}/items", json=POLICY).json()
    login(client, "vee")
    assert client.get(BOOK).status_code == 200 and client.get(f"{BOOK}/items/{pol['id']}").status_code == 200
    for method, path in (("POST", "/items"), ("PATCH", f"/items/{pol['id']}"), ("POST", f"/items/{pol['id']}/close")):
        r = client.request(method, BOOK + path, json={})
        assert (r.status_code, r.json()) == (403, {"error": "You can see this book but not change it."})


def test_refusals_come_back_in_plain_words(margaret, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/items", json={**POLICY, "owner": "jr"})
    assert (r.status_code, r.json()) == (422, {"error": "Choose one of this book's owners."})
    assert client.get(f"{BOOK}/items/999").json() == {"error": "No such item."}
    pol = client.post(f"{BOOK}/items", json=POLICY).json()
    assert client.post(f"{BOOK}/items/{pol['id']}/close", json={}).json() == {
        "error": "Enter the date it closed, like 2026-03-01."}
    closed = client.post(f"{BOOK}/items/{pol['id']}/close", json={"closed_on": "2026-10-01", "why": "Cancelled"}).json()
    assert closed["status"] == "closed"
    r = client.patch(f"{BOOK}/items/{pol['id']}", json={"name": "x"})
    assert (r.status_code, r.json()) == (409, {"error": "This item is closed. Reopen it to change it."})
    assert client.post(f"{BOOK}/items/{pol['id']}/reopen").json()["status"] == "confirmed"


def test_household_books_have_no_inventory(margaret, client):
    login(client, "jr")
    assert client.get("/api/b/ours/inventory").json() == {"error": "This book doesn't have that."}


def test_an_income_item_lists_its_deposits_with_weekend_notes(frozen, margaret, client, mdb):
    login(client, "jr")
    chk = client.post(f"{BOOK}/items", json=CHECKING).json()
    acct = mdb.get(Account, chk["account_id"])
    for d in (date(2026, 10, 2), date(2026, 9, 3), date(2026, 5, 1)):   # Oct 3 2026 is a Saturday, May 3 a Sunday
        make_txn(mdb, acct, d, 214000, "SSA TREAS 310 XXSOC SEC")
    ss = client.post(f"{BOOK}/items", json={"kind": "income", "name": "Social Security", "owner": "margaret",
                                            "status": "confirmed", "details": {
                                                "source": "social_security", "amount_cents": 214000,
                                                "frequency": "monthly", "usual_day": 3, "lands_in_id": chk["id"],
                                                "match_text": "SSA TREAS 310"}}).json()
    assert ss["sub"] == "Monthly, around the 3rd · into ••4417"
    assert ss["matched"]["heading"] == "Last 3 deposits"
    assert [r["note"] for r in ss["matched"]["rows"]] == ["the 3rd is a Saturday", None, "the 3rd was a Sunday"]
    assert client.get(f"{BOOK}/items/{chk['id']}").json()["money_in_here"] == [{"id": ss["id"], "name": "Social Security"}]


def test_a_floor_typed_on_the_item_form_checks_the_balance_at_once(frozen, margaret, client, mdb):
    from steward.db.models import Flag
    login(client, "jr")
    chk = client.post(f"{BOOK}/items", json=CHECKING).json()
    r = client.patch(f"{BOOK}/items/{chk['id']}", json={"details": {"floor_cents": 2_500_000}})
    assert r.status_code == 200
    mdb.rollback()
    flags = list(mdb.scalars(select(Flag)))
    assert [(f.check, f.account_id is not None) for f in flags] == [("low", True)]
    client.patch(f"{BOOK}/items/{chk['id']}", json={"name": "Joint checking 2"})
    mdb.rollback()
    assert len(list(mdb.scalars(select(Flag)))) == 1


def test_a_floor_typed_on_the_item_form_raises_a_dip_only_on_that_account(frozen, margaret, client, mdb):
    from steward.db.models import Flag
    login(client, "jr")
    other = client.post(f"{BOOK}/items", json={**CHECKING, "name": "Old savings", "last4": "9921",
                                               "details": {"type": "savings", "floor_cents": 2_500_000}}).json()
    chk = client.post(f"{BOOK}/items", json=CHECKING).json()
    client.patch(f"{BOOK}/items/{chk['id']}", json={"details": {"floor_cents": 2_500_000}})
    mdb.rollback()
    flags = list(mdb.scalars(select(Flag)))
    item_ids = {f.item_id for f in flags}
    assert item_ids == {chk["id"]} and other["id"] not in item_ids
