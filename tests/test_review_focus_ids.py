"""Review focus P22: a sort applied to the matching rows names them (result.ids), so Focus can drop exactly those cards
and the list can mark exactly those as matched. applied stays len(ids); Undo still restores every one."""
from datetime import date

from steward.db.models import CategorySource
from tests.factories import make_account, make_txn, make_user


def _login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_a_sort_applied_to_matching_names_the_rows_it_changed_and_undo_restores_them(client, db):
    _login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    others = [make_txn(db, a, date(2026, 9, d), -8000, f"UNION SERVICE CENTER 00{d}") for d in (3, 4)]
    make_txn(db, a, date(2026, 9, 5), -8000, "UNION SERVICE CENTER 0005", category="home",
             category_source=CategorySource.rule)                          # already Home: not changed, not named
    res = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home", "apply_to_matching": True}).json()["result"]
    assert res["ids"] == sorted(o.id for o in others)
    assert res["applied"] == len(res["ids"]) == 2
    r = client.post(f"/api/b/ours/undo/{res['undo']}")
    assert r.status_code == 200 and r.json()["undone"] == 3
    db.rollback()
    assert [o.category for o in others] == ["uncategorized", "uncategorized"]


def test_without_apply_the_result_names_no_rows(client, db):
    _login(client, db)
    a = make_account(db)
    t = make_txn(db, a, date(2026, 10, 3), -8000, "UNION SERVICE CENTER 0041")
    make_txn(db, a, date(2026, 9, 3), -8000, "UNION SERVICE CENTER 0040")
    res = client.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "home"}).json()["result"]
    assert (res["ids"], res["applied"]) == ([], 0)
