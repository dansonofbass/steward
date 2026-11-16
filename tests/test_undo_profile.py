"""Undo for Profile's writes (profile spec P26-P27, Engineering choices 9-10): facts and balances made are deleted,
accounts and kids put back, a removed kid comes back (without a 529 someone took since), Later is cleared; never a
name; a made account that something newer points at refuses with 409."""
from datetime import date

from sqlalchemy import select

from steward.db.models import BalanceSnapshot, Fact, UndoEntry
from tests.factories import make_account

U = "/api/b/ours"


def undo(c, token):
    return c.post(f"{U}/undo/{token}")


def test_a_fact_made_is_deleted_and_the_previous_value_is_back(frozen, signed_in, db):
    first = signed_in.post(f"{U}/facts", json={"key": "health.premium_cents", "value": "1680000"}).json()
    second = signed_in.post(f"{U}/facts", json={"key": "health.premium_cents", "value": "2400000"}).json()
    assert undo(signed_in, second["undo"]).status_code == 200
    assert signed_in.get(f"{U}/facts").json()["facts"]["health.premium_cents"]["value"] == "1680000"
    assert first["undo"] != second["undo"]


def test_the_home_value_undo_takes_back_the_account_it_made_its_balance_and_link(frozen, signed_in, db):
    r = signed_in.post(f"{U}/facts", json={"key": "home.value_cents", "value": "125000000"}).json()
    db.rollback()   # end the read snapshot so we see the request's commit
    assert db.scalar(select(Fact).where(Fact.key == "home.account_id")) is not None
    assert undo(signed_in, r["undo"]).status_code == 200
    db.rollback()   # end the read snapshot so we see the request's commit
    assert db.scalars(select(Fact)).all() == [] and db.scalars(select(BalanceSnapshot)).all() == []
    assert [a["name"] for a in signed_in.get(f"{U}/accounts").json()["accounts"]] == []


def test_an_account_change_is_put_back_and_its_name_never_enters_the_journal(frozen, signed_in, db):
    mortgage = make_account(db, "Chase mortgage", type="mortgage")
    r = signed_in.patch(f"{U}/accounts/{mortgage.id}", json={"rate_bp": 287, "is_active": False}).json()
    assert undo(signed_in, r["undo"]).status_code == 200
    db.rollback()   # end the read snapshot so we see the request's commit
    assert (mortgage.rate_bp, mortgage.is_active) == (None, True)
    e = db.scalar(select(UndoEntry).order_by(UndoEntry.created_at.desc()))
    assert "Chase" not in e.before + e.after


def test_a_balance_typed_over_one_on_the_same_day_is_put_back(frozen, signed_in, db):
    car = make_account(db, "Subaru", type="vehicle")
    signed_in.post(f"{U}/accounts/{car.id}/balance", json={"balance_cents": 2_000_000})
    r = signed_in.post(f"{U}/accounts/{car.id}/balance", json={"balance_cents": 1_800_000}).json()
    assert undo(signed_in, r["undo"]).status_code == 200
    db.rollback()   # end the read snapshot so we see the request's commit
    assert db.get(BalanceSnapshot, (car.id, date(2026, 10, 13))).balance_cents == 2_000_000


def test_undoing_a_made_account_that_now_has_rows_is_refused(frozen, signed_in, db):
    """Review Focus 5: Add a property, then a balance on it, then Undo of the add."""
    made = signed_in.post(f"{U}/accounts", json={"name": "Cabin", "type": "property", "owner": "joint",
                                                "balance_cents": 40_000_000, "as_of": "2026-10-01"}).json()
    signed_in.post(f"{U}/accounts/{made['id']}/balance", json={"balance_cents": 41_000_000})
    r = undo(signed_in, made["undo"])
    assert r.status_code == 409 and r.json() == {"error": "That changed since, so it can't be undone."}
    assert [a["name"] for a in signed_in.get(f"{U}/accounts").json()["accounts"]] == ["Cabin"]


def test_a_removed_kid_comes_back_with_its_529_and_its_name_never_enters_the_journal(frozen, signed_in, db):
    p529 = make_account(db, "Fidelity 529", type="plan529")
    kid = signed_in.post(f"{U}/children", json={"label": "Zoë", "birth_year": 2015, "account_id": p529.id}).json()
    gone = signed_in.delete(f"{U}/children/{kid['id']}")
    assert gone.status_code == 200
    assert signed_in.get(f"{U}/children").json()["children"] == []
    assert undo(signed_in, gone.json()["undo"]).status_code == 200
    back = signed_in.get(f"{U}/children").json()["children"]
    assert [(k["label"], k["account_id"]) for k in back] == [("Zoë", p529.id)]
    db.rollback()
    for e in db.scalars(select(UndoEntry)):
        assert "Zoë" not in e.before + e.after


def test_undoing_a_remove_after_the_529_was_relinked_keeps_the_new_link(frozen, signed_in, db):
    """Review Focus 2: removed and added back under the same name, the 529 linked to the new row."""
    p529 = make_account(db, "Fidelity 529", type="plan529")
    old = signed_in.post(f"{U}/children", json={"label": "Ava", "birth_year": 2015, "account_id": p529.id}).json()
    gone = signed_in.delete(f"{U}/children/{old['id']}").json()
    new = signed_in.post(f"{U}/children", json={"label": "Ava", "birth_year": 2015, "account_id": p529.id}).json()
    assert undo(signed_in, gone["undo"]).status_code == 200
    kids = {k["id"]: k["account_id"] for k in signed_in.get(f"{U}/children").json()["children"]}
    assert kids == {old["id"]: None, new["id"]: p529.id}


def test_later_is_undone_by_its_token(frozen, signed_in, db):
    r = signed_in.post(f"{U}/profile/later", json={"later": True}).json()
    assert r["me"]["later_until"] is not None
    assert undo(signed_in, r["undo"]).status_code == 200
    assert signed_in.get(f"{U}/profile").json()["me"]["later_until"] is None


def test_entries_written_before_this_change_still_undo(frozen, signed_in, db):
    """Keys stay "12" for one-column keys, as every open entry already has them."""
    from steward.services.undo import _ident
    from steward.db.models import MerchantRule
    assert _ident(MerchantRule, "12") == 12 and _ident(BalanceSnapshot, "3|2026-10-01") == (3, date(2026, 10, 1))
