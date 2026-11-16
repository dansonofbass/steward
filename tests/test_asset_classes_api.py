from datetime import date

from steward.db.models import AssetClass, Holding
from tests.factories import make_account

CHOOSE = "Choose US stocks, international stocks, bonds or cash."


def _hold(db):
    a = make_account(db, "Brokerage", type="brokerage_taxable")
    for sym, name in (("VTI", "Total Stock"), ("ZZFUNDX", "Mystery Fund"), (None, "Cash sweep")):
        db.add(Holding(account_id=a.id, as_of=date(2026, 10, 1), symbol=sym, name=name, shares_milli=1, market_value_cents=100))
    db.commit()


def test_lists_held_symbols_unknown_first(frozen, signed_in, db):
    _hold(db)
    body = signed_in.get("/api/b/ours/asset-classes").json()
    assert body["classes"] == ["us_stock", "intl_stock", "bond", "cash"]
    assert [(r["symbol"], r["source"], r["class"]) for r in body["symbols"]] == [("ZZFUNDX", "default", None), ("VTI", "builtin", "us_stock")]
    assert body["symbols"][0]["accounts"] == ["Brokerage"] and body["symbols"][0]["mix"] is None
    assert body["symbols"][0]["name"] == "Mystery Fund"
    assert body["symbols"][1]["mix"] == {"stock": 1.0, "bond": 0.0, "cash": 0.0}


def test_put_sets_and_clears_an_override(frozen, signed_in, db):
    _hold(db)
    r = signed_in.put("/api/b/ours/asset-classes", json={"symbol": " zzfundx ", "class": "bond"})
    assert r.status_code == 200
    row = next(s for s in r.json()["symbols"] if s["symbol"] == "ZZFUNDX")
    assert (row["source"], row["class"], row["mix"]) == ("override", "bond", {"stock": 0.0, "bond": 1.0, "cash": 0.0})
    assert db.get(AssetClass, "ZZFUNDX").source == "override"
    r = signed_in.put("/api/b/ours/asset-classes", json={"symbol": "ZZFUNDX", "class": None})
    row = next(s for s in r.json()["symbols"] if s["symbol"] == "ZZFUNDX")
    assert row["source"] == "default"
    db.rollback()  # end the read snapshot the earlier db.get opened
    assert db.get(AssetClass, "ZZFUNDX") is None
    r = signed_in.put("/api/b/ours/asset-classes", json={"symbol": "VTI", "class": "cash"})
    assert next(s for s in r.json()["symbols"] if s["symbol"] == "VTI")["source"] == "override"


def test_put_checks_values(frozen, signed_in):
    for body, message in (({"symbol": "", "class": "bond"}, "Enter the fund's ticker symbol."),
                          ({"symbol": "not a ticker!", "class": "bond"}, "Enter the fund's ticker symbol."),
                          ({"symbol": 5, "class": "bond"}, "Enter the fund's ticker symbol."),
                          ({"symbol": "VTI", "class": "gold"}, CHOOSE),
                          ({"symbol": "VTI"}, CHOOSE)):
        r = signed_in.put("/api/b/ours/asset-classes", json=body)
        assert r.status_code == 422 and r.json() == {"error": message}, body


def test_asset_classes_need_sign_in(client):
    assert client.get("/api/b/ours/asset-classes").status_code == 401
    assert client.put("/api/b/ours/asset-classes", json={}).status_code == 401
