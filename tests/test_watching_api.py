"""Settings → Watching (README screen 5): the large amount, low-balance floors, known payees, and who is emailed
(decision 4; ruling 5), each change recorded (spec 5)."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from steward.db.directory_models import Membership, User
from steward.db.models import ChangeRecord, Flag, InventoryItem, MailOutbox
from steward.mail import FakeMailer
from steward.services.accounts import record_balance
from steward.watch.flags import mark_expected
from steward.watch.recipients import members, urgent_to
from steward.watch.store import add_flag
from tests.factories import login, make_person
from tests.watch_helpers import NOW, account, d

BOOK = "/api/b/margaret-ellis"


@pytest.fixture
def at_now(monkeypatch):
    """Pin steward.deps.now to Mon Oct 19, 2026, 6:12 AM Pacific. List it before logging in."""
    monkeypatch.setattr("steward.clock.now", lambda: NOW)
    return NOW


def _ids(ddb):
    return {u.username: u.id for u in ddb.scalars(select(User))}


def _save(mdb):
    save = account(mdb, "Way2Save savings", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    mdb.commit()
    return save, mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == save.id))


def test_the_settings_page_starts_with_the_defaults(at_now, margaret, mdb, client, ddb):
    _save(mdb)
    account(mdb, "Citi card", "credit_card", owner="margaret", institution="Citi")
    login(client, "jr")
    s = client.get(f"{BOOK}/watching").json()
    assert (s["large_cents"], s["default_cents"], s["can_edit"]) == (50_000, 50_000, True)
    assert [(f["name"], f["sub"], f["balance_cents"], f["floor_cents"], f["under"]) for f in s["floors"]] == [
        ("Way2Save savings", "Wells Fargo · now $22,480.10", 2_248_010, None, False)]
    assert s["known"] == [] and s["mail"] == {"ready": True, "last_sent": None, "failure": None}
    ids = _ids(ddb)
    assert s["people"] == [
        {"user_id": ids["jr"], "name": "Jr", "role": "manager", "role_label": "Manager", "urgent": True,
         "summary": True, "can_change": True, "is_me": True},
        {"user_id": ids["vee"], "name": "Vee", "role": "viewer", "role_label": "Viewer", "urgent": False,
         "summary": False, "can_change": True, "is_me": False}]


def test_the_large_amount(at_now, margaret, mdb, client):
    login(client, "jr")
    r = client.patch(f"{BOOK}/watching/large", json={"cents": 75_000, "note": "Fewer flags for groceries."})
    assert r.status_code == 200 and r.json()["large_cents"] == 75_000
    row = mdb.scalar(select(ChangeRecord).where(ChangeRecord.action == "watch.large"))
    assert json.loads(row.before) == {"large_cents": 50_000} and json.loads(row.after) == {"large_cents": 75_000}
    assert row.note == "Fewer flags for groceries."
    assert client.patch(f"{BOOK}/watching/large", json={"cents": 50}).json() == {
        "error": "Enter an amount from $1.00 to $1,000,000.00."}
    login(client, "vee")
    assert client.patch(f"{BOOK}/watching/large", json={"cents": 60_000}).status_code == 403


def test_the_cash_alert_floor(at_now, margaret, mdb, client):
    login(client, "jr")
    assert client.get(f"{BOOK}/watching").json()["cash_alert_floor_cents"] == 20_000
    r = client.patch(f"{BOOK}/watching/cash-floor", json={"cents": 30_000})
    assert r.status_code == 200 and r.json()["cash_alert_floor_cents"] == 30_000
    row = mdb.scalar(select(ChangeRecord).where(ChangeRecord.action == "watch.cash_floor"))
    assert json.loads(row.before) == {"cash_alert_floor_cents": 20_000} and json.loads(row.after) == {"cash_alert_floor_cents": 30_000}
    assert client.patch(f"{BOOK}/watching/cash-floor", json={"cents": 50}).status_code == 422
    assert client.patch(f"{BOOK}/watching/cash-floor", json={"cents": True}).status_code == 422
    login(client, "vee")
    assert client.patch(f"{BOOK}/watching/cash-floor", json={"cents": 60_000}).status_code == 403


def test_setting_a_floor_checks_the_balance_at_once(at_now, margaret, mdb, client):
    save, item = _save(mdb)
    card = account(mdb, "Citi card", "credit_card", owner="margaret", institution="Citi")
    card_item = mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == card.id))
    login(client, "jr")
    r = client.put(f"{BOOK}/watching/floors/{item.id}", json={"cents": 2_500_000})
    assert r.status_code == 200
    assert [(f["floor_cents"], f["under"]) for f in r.json()["floors"]] == [(2_500_000, True)]
    mdb.rollback()                                       # end the test session's old read snapshot
    [flag] = mdb.scalars(select(Flag)).all()
    assert (flag.check, flag.account_id) == ("low", save.id)
    row = mdb.scalar(select(ChangeRecord).where(ChangeRecord.action == "watch.floor"))
    assert (row.target_id, row.item_id) == (item.id, item.id)
    assert json.loads(row.before) == {"floor_cents": None} and json.loads(row.after) == {"floor_cents": 2_500_000}
    assert client.put(f"{BOOK}/watching/floors/{card_item.id}", json={"cents": 100}).json() == {
        "error": "Choose a checking, savings or CD account."}
    assert client.put(f"{BOOK}/watching/floors/{item.id}", json={"cents": None}).json()["floors"][0]["floor_cents"] is None
    mdb.rollback()
    mdb.expire_all()
    assert "floor_cents" not in json.loads(mdb.get(InventoryItem, item.id).details)


def test_known_payees_are_listed_and_removed(at_now, margaret, mdb, mctx, client):
    f = add_flag(mdb, check="large", severity="normal", summary="$640.00 to Brea Family Dental",
                 title="$640.00 to Brea Family Dental", now=NOW, after="sync",
                 facts={"payee": "Brea Family Dental", "payee_key": "BREA FAMILY DENTAL", "method": "card",
                        "amount_cents": 64_000})
    mark_expected(mdb, mctx, f, {"scope": "about", "note": "Margaret's crown."}, NOW)
    mdb.commit()
    login(client, "jr")
    [k] = client.get(f"{BOOK}/watching").json()["known"]
    assert (k["payee"], k["range"], k["added"], k["note"]) == (
        "Brea Family Dental", "$480 to $800", "Jr, Oct 19, from a Large amount flag", "Margaret's crown.")
    r = client.post(f"{BOOK}/watching/known/{k['id']}/remove", json={"note": "The crown is done."})
    assert r.status_code == 200 and r.json()["known"] == []
    assert client.post(f"{BOOK}/watching/known/{k['id']}/remove", json={}).status_code == 409
    assert client.post(f"{BOOK}/watching/known/999999/remove", json={}).status_code == 404


def test_email_switches_and_the_last_manager_rule(at_now, margaret, mdb, client, ddb):
    ids = _ids(ddb)
    login(client, "jr")
    r = client.patch(f"{BOOK}/watching/emails/{ids['jr']}", json={"urgent": False})
    assert (r.status_code, r.json()) == (409, {"error": "At least one manager has to get urgent emails. Turn them on "
                                                        "for another manager first."})
    r = client.patch(f"{BOOK}/watching/emails/{ids['vee']}", json={"urgent": True, "summary": True})
    vee = next(p for p in r.json()["people"] if p["name"] == "Vee")
    assert (vee["urgent"], vee["summary"]) == (True, True)
    row = mdb.scalar(select(ChangeRecord).where(ChangeRecord.action == "watch.emails"))
    assert row.target_id == ids["vee"] and json.loads(row.after) == {"urgent": True, "summary": True}
    ddb.rollback()                                       # end the test session's old read snapshot
    sam = make_person(ddb, "sam", [(margaret.id, "manager")])
    assert client.patch(f"{BOOK}/watching/emails/{ids['jr']}", json={"urgent": False}).status_code == 200
    r = client.patch(f"{BOOK}/watching/emails/{sam.id}", json={"summary": False})
    assert (r.status_code, r.json()) == (403, {"error": "You can change your own emails and a viewer's."})
    assert client.patch(f"{BOOK}/watching/emails/{ids['jr']}", json={"urgent": "no"}).status_code == 422
    assert client.patch(f"{BOOK}/watching/emails/999999", json={"urgent": True}).status_code == 404


def test_a_viewer_can_stop_their_own_emails(at_now, margaret, mdb, client, ddb):
    ids = _ids(ddb)
    login(client, "jr")
    client.patch(f"{BOOK}/watching/emails/{ids['vee']}", json={"urgent": True, "summary": True})
    login(client, "vee")
    s = client.get(f"{BOOK}/watching").json()
    assert s["can_edit"] is False and [p["can_change"] for p in s["people"]] == [False, False]
    r = client.post(f"{BOOK}/watching/emails/stop")
    vee = next(p for p in r.json()["people"] if p["is_me"])
    assert (r.status_code, vee["urgent"], vee["summary"]) == (200, False, False)
    assert client.patch(f"{BOOK}/watching/emails/{ids['vee']}", json={"urgent": True}).status_code == 403


def test_urgent_mail_falls_back_to_every_manager(margaret, mdb, books, ddb, client):
    ddb.rollback()                                       # end the test session's old read snapshot
    sam = make_person(ddb, "sam", [(margaret.id, "manager")])
    ids = _ids(ddb)
    login(client, "sam")
    assert client.patch(f"{BOOK}/watching/emails/{sam.id}", json={"urgent": False}).status_code == 200
    assert [m.name for m in urgent_to(mdb, members(books.directory, margaret.id))] == ["Jr"]
    ddb.rollback()
    ddb.execute(delete(Membership).where(Membership.user_id == ids["jr"], Membership.book_id == margaret.id))
    ddb.commit()
    assert [m.name for m in urgent_to(mdb, members(books.directory, margaret.id))] == ["Sam"]


def test_the_test_email_and_mail_that_isnt_set_up(at_now, margaret, app, client):
    login(client, "jr")
    r = client.post(f"{BOOK}/watching/test-email", json={})
    assert r.json() == {"sent_to": "jr@x.com"}
    to, subject, body = app.state.mailer.sent[-1]
    assert (to, subject) == ("jr@x.com", "Steward test email") and "Margaret Ellis" in body
    app.state.mailer = FakeMailer(configured=False)
    assert client.get(f"{BOOK}/watching").json()["mail"]["ready"] is False
    assert client.post(f"{BOOK}/watching/test-email", json={}).json() == {"error": "Email isn't set up."}


def test_the_last_sent_and_failure_lines(at_now, margaret, mdb, client, ddb):
    ids = _ids(ddb)
    f = add_flag(mdb, check="scam", severity="urgent", summary="$500.00 gift card at CVS Pharmacy",
                 title="$500.00 gift card at CVS Pharmacy", facts={}, now=NOW - timedelta(days=1), after="sync")
    mail = mdb.scalar(select(MailOutbox))
    mail.status, mail.tries, mail.to_user_ids = "failed", 3, json.dumps([ids["jr"]])
    mail.failed_at, mail.last_error = NOW - timedelta(days=1) + timedelta(hours=1), "535 authentication failed"
    mdb.add(MailOutbox(kind="summary", status="sent", created_at=NOW, next_try_at=NOW, tries=1, flag_ids="[]",
                       to_user_ids=json.dumps([ids["jr"]]), sent_to=json.dumps([ids["jr"]]),
                       subject="Margaret Ellis: 2 new to look into, Mon Oct 19", sent_at=NOW + timedelta(minutes=48)))
    mdb.commit()
    login(client, "jr")
    mail = client.get(f"{BOOK}/watching").json()["mail"]
    assert mail["last_sent"] == "Last sent today at 7:00 AM (daily summary to Jr)."
    assert mail["failure"] is None                                      # an email went through after it
    mdb.scalar(select(MailOutbox).where(MailOutbox.kind == "summary")).sent_at = NOW - timedelta(days=2)
    mdb.commit()
    assert client.get(f"{BOOK}/watching").json()["mail"]["failure"] == {
        "title": "An urgent email couldn't be sent.",
        "line": '"$500.00 gift card at CVS Pharmacy" to Jr, Oct 18. Tried 3 times until 7:12 AM; the mail server '
                'said: "535 authentication failed".'}


def test_a_viewer_cannot_remove_a_known_payee(at_now, margaret, mdb, mctx, client):
    f = add_flag(mdb, check="large", severity="normal", summary="$640.00 to Brea Family Dental",
                 title="$640.00 to Brea Family Dental", now=NOW, after="sync",
                 facts={"payee": "Brea Family Dental", "payee_key": "BREA FAMILY DENTAL", "method": "card",
                        "amount_cents": 64_000})
    mark_expected(mdb, mctx, f, {"scope": "about"}, NOW)
    mdb.commit()
    login(client, "jr")
    [k] = client.get(f"{BOOK}/watching").json()["known"]
    login(client, "vee")
    r = client.post(f"{BOOK}/watching/known/{k['id']}/remove", json={})
    assert (r.status_code, r.json()) == (403, {"error": "You can see this book but not change it."})
    login(client, "jr")
    assert len(client.get(f"{BOOK}/watching").json()["known"]) == 1
