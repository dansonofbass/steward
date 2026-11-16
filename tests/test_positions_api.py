"""POST /accounts/{id}/positions/preview and POST /accounts/{id}/positions (investment views spec)."""
import json
from datetime import date

from sqlalchemy import select

from steward.api.limits import MB
from steward.db.models import Holding
from steward.deps import NOT_IN_THIS_BOOK, VIEWER_COPY
from tests.factories import login, make_account, make_person

CSV = "Symbol,Description,Quantity,Market Value\nVTI,Total Stock,400,\"$108,000.00\"\nAccount Total,,,\"$108,000.00\"\n"
M = {"symbol": "Symbol", "name": "Description", "shares": "Quantity", "value": "Market Value", "cost_basis": None}


def _file(text=CSV, name="positions.csv"):
    return {"file": (name, text.encode(), "text/csv")}


def test_preview_then_save(frozen, signed_in, db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions/preview", files=_file())
    assert r.status_code == 200 and r.json()["needs_mapping"] and r.json()["as_of"] == "2026-10-13"
    r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions/preview", files=_file(),
                       data={"mapping": json.dumps(M), "as_of": "2026-10-10"})
    assert r.status_code == 200 and (r.json()["count"], r.json()["total_cents"], r.json()["as_of"]) == (1, 108_000_00, "2026-10-10")
    r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions", files=_file(), data={"mapping": json.dumps(M)})
    assert r.status_code == 201 and r.json() == {"count": 1, "total_cents": 108_000_00, "as_of": "2026-10-13", "first": True}
    db.rollback()
    assert [(h.as_of, h.symbol) for h in db.scalars(select(Holding))] == [(date(2026, 10, 13), "VTI")]


def test_the_date_cant_be_in_the_future_or_unreadable(frozen, signed_in, db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    for day, msg in (("2026-10-14", "Choose a date that isn't in the future."), ("10/13/2026", "Choose a date.")):
        r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions", files=_file(), data={"mapping": json.dumps(M), "as_of": day})
        assert r.status_code == 422 and r.json() == {"error": msg}


def test_only_an_investment_account_takes_positions(frozen, signed_in, db):
    chk = make_account(db, "Checking")
    r = signed_in.post(f"/api/b/ours/accounts/{chk.id}/positions/preview", files=_file())
    assert r.status_code == 409 and r.json() == {"error": "That isn't an investment account."}
    assert signed_in.post("/api/b/ours/accounts/999/positions/preview", files=_file()).status_code == 404


def test_a_bad_mapping_is_a_plain_error(frozen, signed_in, db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions", files=_file(), data={"mapping": "{nope"})
    assert r.status_code == 422 and r.json() == {"error": "That column mapping wasn't understood."}
    r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions", files=_file(), data={"mapping": json.dumps({**M, "value": "Price"})})
    assert r.status_code == 422 and r.json() == {"error": "Choose the value column, and a symbol or a name column."}


def test_a_file_over_1_mb_is_refused(frozen, signed_in, db):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    r = signed_in.post(f"/api/b/ours/accounts/{a.id}/positions/preview", files=_file("x" * (MB + 1)))
    assert r.status_code == 413 and r.json() == {"error": "That file is bigger than 1 MB."}


def test_a_parent_book_has_no_positions_import(frozen, client, margaret):
    login(client, "jr")
    r = client.post("/api/b/margaret-ellis/accounts/1/positions/preview", files=_file())
    assert r.status_code == 404 and r.json() == {"error": NOT_IN_THIS_BOOK}


def test_a_viewer_cannot_save_positions(frozen, client, db, ddb, ours):
    a = make_account(db, "Betterment", type="brokerage_taxable")
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    r = client.post(f"/api/b/ours/accounts/{a.id}/positions", files=_file(), data={"mapping": json.dumps(M)})
    assert r.status_code == 403 and r.json() == {"error": VIEWER_COPY}
