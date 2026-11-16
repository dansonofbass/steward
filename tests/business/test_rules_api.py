"""GET, POST and DELETE /business/rules (spec 5)."""
from datetime import date

from tests.factories import login, make_account, make_person, make_txn

URL = "/api/b/ours/business/rules"


def test_make_list_and_remove_rules(frozen, signed_in, db):
    card = make_account(db, "Rewards Card", type="credit")
    a = make_txn(db, card, date(2026, 9, 3), -2_900, "NOTEFLOW PRO 0903", merchant="Noteflow")
    make_txn(db, card, date(2026, 8, 3), -2_900, "NOTEFLOW PRO 0803", merchant="Noteflow")
    r = signed_in.post(URL, json={"kind": "merchant", "transaction_id": a.id, "pct": 100, "line": "software"})
    assert r.status_code == 201
    body = r.json()
    assert body["also_tagged"] == 2
    assert body["rule"] == {"id": body["rule"]["id"], "kind": "merchant", "label": "Noteflow", "account_id": card.id,
                            "account_name": "Rewards Card", "pct": 100, "line": "software"}
    r = signed_in.post(URL, json={"kind": "account", "account_id": card.id, "pct": 100, "line": None})
    assert r.status_code == 201 and r.json()["rule"]["label"] == "Rewards Card"
    rules = signed_in.get(URL).json()["rules"]
    assert [x["kind"] for x in rules] == ["merchant", "account"]
    assert signed_in.delete(f"{URL}/{rules[0]['id']}").status_code == 204
    r = signed_in.delete(f"{URL}/{rules[0]['id']}")
    assert r.status_code == 404 and r.json() == {"error": "No such rule."}


def test_rule_refusals(frozen, signed_in, db):
    card = make_account(db, "Rewards Card", type="credit")
    out = make_txn(db, card, date(2026, 9, 3), -2_900, "HARBOR GRILL")
    for body, message in (
        ({"kind": "client", "transaction_id": out.id, "pct": 100}, "A client is someone who pays you, so choose money coming in."),
        ({"kind": "merchant", "transaction_id": 999_999, "pct": 100}, "No such transaction."),
        ({"kind": "account", "account_id": 999_999, "pct": 100}, "No such account."),
        ({"kind": "merchant", "transaction_id": out.id, "pct": 0}, "Choose a whole percent from 1 to 100."),
        ({"kind": "merchant", "transaction_id": "7", "pct": 50}, "No such transaction."),
    ):
        r = signed_in.post(URL, json=body)
        assert r.status_code in (404, 422) and r.json() == {"error": message}, body


def test_viewers_read_rules_and_parent_books_have_none(frozen, client, db, ddb, ours, margaret):
    make_person(ddb, "vee2", [(ours.id, "viewer")])      # the margaret fixture already made "vee", a parent-book viewer
    login(client, "vee2")
    assert client.get(URL).status_code == 200
    assert client.post(URL, json={"kind": "account", "account_id": 1, "pct": 100}).status_code == 403
    login(client, "jr")
    r = client.get("/api/b/margaret-ellis/business/rules")
    assert r.status_code == 404 and r.json() == {"error": "This book doesn't have that."}
