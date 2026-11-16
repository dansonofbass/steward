"""Every item write route must leave nothing behind when a late check refuses (leftovers row 9). create_item,
edit_item, close_item, reopen_item and reveal all change the session before some checks can refuse, so each route
has to drop that work on ItemRefused. The refusal here is forced after the real function has done its writes."""
from sqlalchemy import func, select

import steward.api.inventory as api
import steward.api.inventory_files as files_api
from steward.db.models import ChangeRecord, InventoryItem, StoredFile
from steward.inventory.items import ItemRefused
from tests.factories import login

BOOK = "/api/b/margaret-ellis/inventory"
POLICY = {"kind": "insurance", "name": "Medicare supplement", "owner": "margaret", "institution": "Globe Mutual",
          "number": "GM-55120-0861", "status": "needs_checking", "check_reason": "From a premium notice",
          "details": {"type": "supplement", "amount_cents": 18620, "frequency": "monthly", "usual_day": 15}}
PDF = b"%PDF-1.4\n%made-up statement\n%%EOF\n"


def _late_refusal(real):
    def wrapper(*a, **kw):
        real(*a, **kw)
        raise ItemRefused("Forced late refusal.")
    return wrapper


def _state(mdb):
    mdb.rollback()
    items = [(i.id, i.name, i.status, i.closed_on) for i in mdb.scalars(select(InventoryItem).order_by(InventoryItem.id))]
    return (items, mdb.scalar(select(func.count()).select_from(ChangeRecord)),
            mdb.scalar(select(func.count()).select_from(StoredFile)))


def _make(client):
    login(client, "jr")
    return client.post(f"{BOOK}/items", json=POLICY).json()["id"]


def test_add_rolls_back_on_a_late_refusal(frozen, margaret, client, mdb, monkeypatch):
    login(client, "jr")
    before = _state(mdb)
    monkeypatch.setattr(api, "create_item", _late_refusal(api.create_item))
    r = client.post(f"{BOOK}/items", json=POLICY)
    assert (r.status_code, r.json()) == (422, {"error": "Forced late refusal."})
    assert _state(mdb) == before


def test_change_rolls_back_on_a_late_refusal(frozen, margaret, client, mdb, monkeypatch):
    item_id = _make(client)
    before = _state(mdb)
    monkeypatch.setattr(api, "edit_item", _late_refusal(api.edit_item))
    r = client.patch(f"{BOOK}/items/{item_id}", json={"name": "Renamed", "note": "x"})
    assert r.status_code == 422
    assert _state(mdb) == before


def test_close_rolls_back_on_a_late_refusal(frozen, margaret, client, mdb, monkeypatch):
    item_id = _make(client)
    before = _state(mdb)
    monkeypatch.setattr(api, "close_item", _late_refusal(api.close_item))
    r = client.post(f"{BOOK}/items/{item_id}/close", json={"closed_on": "2026-10-01", "why": "Cancelled"})
    assert r.status_code == 422
    assert _state(mdb) == before


def test_reopen_rolls_back_on_a_late_refusal(frozen, margaret, client, mdb, monkeypatch):
    item_id = _make(client)
    client.post(f"{BOOK}/items/{item_id}/close", json={"closed_on": "2026-10-01", "why": "Cancelled"})
    before = _state(mdb)
    monkeypatch.setattr(api, "reopen_item", _late_refusal(api.reopen_item))
    r = client.post(f"{BOOK}/items/{item_id}/reopen")
    assert r.status_code == 422
    assert _state(mdb) == before


def test_full_number_rolls_back_on_a_late_refusal(frozen, margaret, client, mdb, monkeypatch):
    item_id = _make(client)
    before = _state(mdb)
    monkeypatch.setattr(api, "reveal", _late_refusal(api.reveal))
    r = client.post(f"{BOOK}/items/{item_id}/full-number")
    assert r.status_code == 422
    assert _state(mdb) == before


def test_upload_with_confirm_rolls_back_on_a_late_refusal(frozen, margaret, client, mdb, monkeypatch, books):
    item_id = _make(client)
    before = _state(mdb)
    monkeypatch.setattr(files_api, "edit_item", _late_refusal(files_api.edit_item))
    r = client.post(f"{BOOK}/files", files={"file": ("statement.pdf", PDF, "application/octet-stream")},
                    data={"item_id": str(item_id), "confirm": "true"})
    assert r.status_code == 422
    assert _state(mdb) == before
