"""The set-aside routes (spec, API): household only; viewers read, managers write; validation per kind; one event per
write; the GET writer guard; the transaction detail's set_aside field."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import EventLog, SetAside, SetAsideMatch, Transaction
from steward.deps import VIEWER_COPY
from tests.factories import login, make_account, make_person, make_txn
from tests.setaside_fixtures import TODAY, household

OCT_25 = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)
YEARLY = {"name": "Home insurance", "kind": "yearly", "amount_cents": 138_000, "due_month": 5, "due_day": 12,
          "payee_key": "BIG MUTUAL", "category": "insurance"}
TWICE = {"name": "HOA dues", "kind": "twice_yearly", "amount_cents": 45_000, "due_month": 1, "due_day": 15,
         "second_month": 7, "second_day": 15}
ONCE = {"name": "Water heater", "kind": "one_off", "amount_cents": 225_000, "due_year": 2028, "due_month": 12,
        "estimate": {"item": "water_heater", "installed_year": 2014}}      # $2,250 is the estimate's own amount: the tag stays


@pytest.fixture
def oct25(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: OCT_25)


def events(db):
    """The set-aside event lines, oldest first: one per write (an add or an edit folds in what it matched)."""
    db.rollback()                                          # a fresh snapshot: the requests committed in other sessions
    db.expire_all()
    return [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "setaside").order_by(EventLog.id))]


def test_the_list_totals_states_suggestions_and_history(oct25, signed_in, db):
    h = household(db)
    body = signed_in.get("/api/b/ours/setasides").json()
    assert (body["as_of"], body["count"], body["monthly_cents"], body["yearly_cents"], body["one_off_cents"]) == (
        "2026-10-25", 7, 70_167 + 12_500 + 3_433 + 20_000 + 15_500 + 8_462 + 24_324, 1_459_200, 2_020_000)
    assert [r["name"] for r in body["rows"]] == ["Property tax", "Holidays", "Car registration", "Summer camps",
                                                 "Car insurance", "Water heater", "Roof"]
    tax = body["rows"][0]
    assert (tax["state"], tax["next_due"], tax["days_until"], tax["put_away_cents"], tax["should_cents"], tax["short_cents"]) == (
        "short", "2026-11-01", 7, 410_000, 0, 11_000)     # 7 days to Nov 1; nothing owed yet, so the $4,100 tops up the soonest: $110 short
    assert tax["account"] == {"id": h["accounts"]["house"].id, "name": "House fund", "balance_cents": 410_000,
                              "as_of": "2026-10-24", "stale": False, "shared_with": ["Water heater", "Roof"]}
    assert tax["payee_name"] == "County Tax Collector" and tax["monthly_cents"] == 70_167 and tax["is_estimate"] is False
    heater = body["rows"][5]
    assert (heater["is_estimate"], heater["estimate"]["planned_year"], heater["next_due"], heater["state"]) == (True, 2028, "2028-12-01", "on_track")
    assert body["rows"][1]["state"] == "no_account" and body["needs_look"] == 1
    assert body["history_months"] == 19 and body["first_visit"] is False      # April 9, 2025 to October 25, 2026 is 564 days: 564 / 30.44 is 18.5, which reads 19
    assert body["suggestions"] == [] and body["dismissed"] == []
    assert events(db) == []                                                   # a GET writes nothing (the writer guard)


def test_a_stale_snapshot_says_so(oct25, signed_in, db):
    from steward.db.models import BalanceSnapshot
    h = household(db)
    for snap in db.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == h["accounts"]["house"].id)):
        snap.as_of = date(2026, 10, 12)
    db.commit()
    tax = signed_in.get("/api/b/ours/setasides").json()["rows"][0]
    assert (tax["account"]["as_of"], tax["account"]["stale"], tax["put_away_cents"]) == ("2026-10-12", True, 410_000)


def test_an_empty_book_is_a_first_visit(oct25, signed_in, db):
    body = signed_in.get("/api/b/ours/setasides").json()
    assert (body["count"], body["rows"], body["first_visit"], body["history_months"], body["needs_look"]) == (0, [], True, 0, 0)


def test_adding_each_kind_and_the_events(oct25, signed_in, db):
    household(db)
    r = signed_in.post("/api/b/ours/setasides", json=YEARLY)
    assert r.status_code == 201, r.text
    b = r.json()
    assert (b["name"], b["kind"], b["first_month"], b["monthly_cents"], b["next_due"], b["state"]) == (
        "Home insurance", "yearly", "2026-11-01", 11_500, "2027-05-12", "no_account")
    assert b["dues"][0]["status"] == "next" and b["payments"] == [] and b["replace"] is None
    r = signed_in.post("/api/b/ours/setasides", json={**TWICE, "notes": "Maple Court"})
    assert r.status_code == 201 and r.json()["monthly_cents"] == 7_500 and r.json()["notes"] == "Maple Court"
    assert [d["due_on"] for d in r.json()["dues"]] == ["2027-01-15", "2027-07-15"]
    r = signed_in.post("/api/b/ours/setasides", json=ONCE)
    assert r.status_code == 201
    b = r.json()
    assert (b["is_estimate"], b["estimate"]["item"], b["estimate"]["planned_year"], b["monthly_cents"]) == (True, "water_heater", 2028, 8_654)
    r = signed_in.post("/api/b/ours/setasides", json={**ONCE, "name": "Roof", "amount_cents": 1_800_000, "due_year": 2033,
                                                    "estimate": {"item": "roof", "installed_year": 2003}})
    assert r.status_code == 201 and r.json()["is_estimate"] is False       # 2033 is not the estimate's 2032: confirmed
    assert events(db) == ["JR added Home insurance, $1,380 a year, due May 12",
                          "JR added HOA dues, $450 twice a year, Jan 15 and Jul 15",
                          "JR added Water heater, $2,250 about 2028",
                          "JR added Roof, $18,000 about 2033"]
    assert not [m for m in events(db) if m.startswith("Steward matched")]     # one event per write: no second line


def test_adding_runs_matching_from_history(oct25, signed_in, db):
    h = household(db)
    chk = h["accounts"]["checking"]
    make_txn(db, chk, date(2026, 5, 12), -138_000, "BIG MUTUAL INS", merchant="Big Mutual", category="insurance")
    b = signed_in.post("/api/b/ours/setasides", json=YEARLY).json()
    assert [(p["posted_at"], p["due_on"], p["how"]) for p in b["payments"]] == [("2026-05-12", "2026-05-12", "auto")]
    assert b["counted_from"] == "2026-05-01" and b["next_due"] == "2027-05-12"


def test_each_kind_is_validated(oct25, signed_in, db):
    """Review Focus 2 is among these: Feb 29 is a due day, Feb 30 is not."""
    cases = [({**YEARLY, "name": ""}, "Give it a name of up to 120 characters."),
             ({**YEARLY, "kind": "weekly"}, "Choose Every year, Twice a year or Once."),
             ({**YEARLY, "amount_cents": 0}, "Enter an amount from $0.01 to $1,000,000."),
             ({**YEARLY, "amount_cents": 100_000_001}, "Enter an amount from $0.01 to $1,000,000."),
             ({**YEARLY, "due_month": 13}, "Choose a month from 1 to 12."),
             ({**YEARLY, "due_day": 0}, "Choose a day from 1 to 31."),
             ({**YEARLY, "due_month": 2, "due_day": 30}, "February has at most 29 days."),
             ({**TWICE, "second_month": None}, "Twice a year needs two due dates."),
             ({**TWICE, "second_month": 1, "second_day": 15}, "The two due dates must differ."),
             ({**ONCE, "due_year": 2025}, "Choose a year from 2026 to 2086."),
             ({**ONCE, "due_year": None}, "Once needs a year and a month."),
             ({**YEARLY, "account_id": 999}, "Choose a checking or savings account."),
             ({**YEARLY, "category": "income"}, "That isn't a category Spending tracks."),
             ({**YEARLY, "notes": "x" * 501}, "Notes can be up to 500 characters."),
             ({**ONCE, "estimate": {"item": "boat"}}, "Choose Roof, Water heater, Heating and cooling, Car, Appliance or Something else."),
             ({**YEARLY, "due_month": 4, "due_day": 31}, "April has at most 30 days."),
             ({**YEARLY, "second_month": 11, "second_day": 1}, "Every year takes one due date: leave out the second date and the year."),
             ({**YEARLY, "due_year": 2030}, "Every year takes one due date: leave out the second date and the year."),
             ({**TWICE, "due_year": 2030}, "Twice a year takes two due dates: leave out the year."),
             ({**ONCE, "due_day": 1}, "Once takes a year and a month: leave out the day and the second date."),
             ({**ONCE, "second_month": 1}, "Once takes a year and a month: leave out the day and the second date."),
             ({**YEARLY, "estimate": {"item": "roof", "installed_year": 2003}}, "Only a cost that comes once has an estimate."),
             ({**TWICE, "second_month": 2, "second_day": 30}, "February has at most 29 days."),
             ({**YEARLY, "kind": []}, "Choose Every year, Twice a year or Once."),
             ({**YEARLY, "kind": {}}, "Choose Every year, Twice a year or Once."),
             ("junk", "That request wasn't understood.")]
    for body, message in cases:
        r = signed_in.post("/api/b/ours/setasides", json=body)
        assert r.status_code == 422 and r.json() == {"error": message}, body
    ok = signed_in.post("/api/b/ours/setasides", json={**YEARLY, "due_month": 2, "due_day": 29})
    assert ok.status_code == 201 and ok.json()["next_due"] == "2027-02-28"
    k401 = make_account(db, "401(k)", type="k401", owner="jr")
    r = signed_in.post("/api/b/ours/setasides", json={**TWICE, "account_id": k401.id})
    assert r.status_code == 422 and r.json() == {"error": "Choose a checking or savings account."}
    assert len(events(db)) == 1


def test_editing_rematches_and_confirms_an_estimate(oct25, signed_in, db):
    h = household(db)
    sa_id = h["heater"].id
    r = signed_in.put(f"/api/b/ours/setasides/{sa_id}", json={**ONCE, "amount_cents": 250_000, "account_id": h["accounts"]["house"].id})
    assert r.status_code == 200
    b = r.json()
    assert (b["amount_cents"], b["is_estimate"], b["estimate"]["planned_year"], b["monthly_cents"]) == (250_000, False, 2028, 9_615)
    assert events(db) == ["JR changed Water heater: amount $2,200 → $2,500"]   # the heater matches nothing: just the one line
    r = signed_in.put(f"/api/b/ours/setasides/{h['proptax'].id}", json={"name": "Property tax", "kind": "twice_yearly",
                      "amount_cents": 421_000, "due_month": 11, "due_day": 1, "second_month": 4, "second_day": 10,
                      "account_id": h["accounts"]["house"].id, "payee_key": "COUNTY TAX COLLECTOR", "category": "taxes"})
    assert r.status_code == 200
    assert [p["due_on"] for p in r.json()["payments"]] == ["2026-04-10", "2025-11-01", "2025-04-10"]   # matched by this edit
    assert events(db)[1:] == ["JR changed Property tax; matched 3 payments"]    # the one line carries the count
    assert signed_in.put(f"/api/b/ours/setasides/{h['proptax'].id}", json={}).status_code == 200
    assert len(events(db)) == 2                                                 # nothing changed, nothing new matched: no event
    assert signed_in.put("/api/b/ours/setasides/999", json=YEARLY).status_code == 404


def test_adding_folds_the_matches_into_its_one_event(oct25, signed_in, db):
    h = household(db)
    body = {"name": "Property tax 2", "kind": "twice_yearly", "amount_cents": 421_000, "due_month": 11, "due_day": 1,
            "second_month": 4, "second_day": 10, "payee_key": "COUNTY TAX COLLECTOR", "category": "taxes"}
    assert signed_in.post("/api/b/ours/setasides", json=body).status_code == 201
    assert events(db) == ["JR added Property tax 2, $4,210 twice a year, Nov 1 and Apr 10; matched 3 payments"]


def test_a_put_changes_only_the_fields_sent_and_the_tag_follows_year_and_amount(oct25, signed_in, db):
    h = household(db)
    url = f"/api/b/ours/setasides/{h['heater'].id}"
    r = signed_in.put(url, json={"notes": "Basement"})
    b = r.json()
    assert r.status_code == 200 and (b["notes"], b["amount_cents"], b["due_year"], b["account"]["name"], b["is_estimate"]) == (
        "Basement", 220_000, 2028, "House fund", True)
    kids = h["accounts"]["kids"].id
    assert signed_in.put(url, json={"account_id": kids}).json()["is_estimate"] is True      # an account change keeps the tag
    assert signed_in.put(url, json={"name": "Heater"}).json()["is_estimate"] is True
    b = signed_in.put(url, json={"due_year": 2029}).json()                                   # the year moved away
    assert (b["is_estimate"], b["name"], b["account"]["id"]) == (False, "Heater", kids)
    roof = signed_in.put(f"/api/b/ours/setasides/{h['roof'].id}", json={"amount_cents": 1_700_000}).json()
    assert (roof["is_estimate"], roof["due_year"]) == (False, 2032)                         # the amount moved away
    assert events(db)[-1] == "JR changed Roof: amount $18,000 → $17,000"
    r = signed_in.put(f"/api/b/ours/setasides/{h['carins'].id}", json={"kind": "twice_yearly", "second_month": 2, "second_day": 14})
    assert r.status_code == 200 and (r.json()["kind"], r.json()["due_month"], r.json()["due_day"]) == ("twice_yearly", 8, 14)
    r = signed_in.put(f"/api/b/ours/setasides/{h['carins'].id}", json={"due_year": 2030})
    assert r.status_code == 422 and r.json() == {"error": "Twice a year takes two due dates: leave out the year."}


def test_stop_archives_and_keeps_the_matches(oct25, signed_in, db):
    h = household(db)
    signed_in.put(f"/api/b/ours/setasides/{h['proptax'].id}", json={"name": "Property tax", "kind": "twice_yearly",
                  "amount_cents": 421_000, "due_month": 11, "due_day": 1, "second_month": 4, "second_day": 10,
                  "payee_key": "COUNTY TAX COLLECTOR", "category": "taxes"})
    r = signed_in.delete(f"/api/b/ours/setasides/{h['proptax'].id}")
    assert r.status_code == 204
    assert signed_in.get("/api/b/ours/setasides").json()["count"] == 6
    db.rollback()
    db.expire_all()
    assert db.get(SetAside, h["proptax"].id).archived_at == OCT_25
    assert db.scalar(select(SetAsideMatch).where(SetAsideMatch.set_aside_id == h["proptax"].id)) is not None
    assert signed_in.get(f"/api/b/ours/setasides/{h['proptax'].id}").json()["archived_at"] == OCT_25.isoformat()
    assert events(db)[-1] == "JR stopped setting aside Property tax"
    assert signed_in.delete(f"/api/b/ours/setasides/{h['proptax'].id}").status_code == 409   # already archived


def test_a_paid_one_off_offers_the_next_one_and_replace_starts_it(oct25, signed_in, db, monkeypatch):
    h = household(db)
    chk = h["accounts"]["checking"]
    bill = make_txn(db, chk, date(2026, 10, 20), -235_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    r = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": bill.id, "set_aside_id": h["heater"].id})
    assert r.status_code == 200
    b = r.json()
    assert b["paid"] == {"transaction_id": bill.id, "posted_at": "2026-10-20", "cents": 235_000, "account_name": "Checking"}
    assert b["replace"]["paid_cents"] == 235_000 and b["replace"]["next"]["planned_year"] == 2040   # installed 2026, 10 to 15 years, a year before the end
    assert events(db)[-1] == "JR matched a $2,350 payment to Water heater (Dec 1, 2028)"
    r = signed_in.post(f"/api/b/ours/setasides/{h['heater'].id}/replace")
    assert r.status_code == 201
    n = r.json()
    assert (n["name"], n["kind"], n["amount_cents"], n["due_year"], n["due_month"], n["is_estimate"], n["estimate"]["installed_year"]) == (
        "Water heater", "one_off", 235_000, 2040, 12, True, 2026)
    assert n["account"]["id"] == h["accounts"]["house"].id and n["first_month"] == "2026-11-01"
    db.rollback()
    db.expire_all()
    assert db.get(SetAside, h["heater"].id).archived_at == OCT_25
    assert events(db)[-1] == "JR started the next Water heater, $2,350 about 2040"
    assert signed_in.post(f"/api/b/ours/setasides/{h['holidays'].id}/replace").status_code == 409   # not a paid one-off


def test_skip_find_and_undo(oct25, signed_in, db):
    h = household(db)
    sa_id = h["proptax"].id
    r = signed_in.post(f"/api/b/ours/setasides/{sa_id}/skip", json={"due_on": "2026-11-01"})
    assert r.status_code == 200 and r.json()["next_due"] == "2027-04-10"
    assert [d["status"] for d in r.json()["dues"] if d["due_on"] == "2026-11-01"] == ["skipped"]
    assert events(db)[-1] == "JR said Property tax's Nov 1, 2026 installment was not due"
    r = signed_in.post(f"/api/b/ours/setasides/{sa_id}/skip", json={"due_on": "2026-11-01"})
    assert r.status_code == 422 and r.json() == {"error": "Nov 1, 2026 is already settled."}
    r = signed_in.post(f"/api/b/ours/setasides/{sa_id}/skip", json={"due_on": "nope"})
    assert r.status_code == 422 and r.json() == {"error": "That request wasn't understood."}
    chk = h["accounts"]["checking"]
    t = make_txn(db, chk, date(2027, 4, 12), -421_000, "COUNTY TAX COLLECTOR", merchant="County Tax Collector", category="taxes")
    r = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": t.id, "set_aside_id": sa_id})
    assert r.status_code == 200 and r.json()["next_due"] == "2027-11-01"
    rows = signed_in.get("/api/b/ours/transactions?category=taxes").json()["transactions"]
    assert next(x for x in rows if x["id"] == t.id)["set_aside"] == {"id": sa_id, "name": "Property tax", "how": "hand", "archived": False}
    assert all(x["set_aside"] is None for x in rows if x["id"] != t.id)
    r = signed_in.delete(f"/api/b/ours/setasides/match/{t.id}")
    assert r.status_code == 204
    assert events(db)[-1] == "JR unmatched a $4,210 payment from Property tax"
    rows = signed_in.get("/api/b/ours/transactions?category=taxes").json()["transactions"]
    assert next(x for x in rows if x["id"] == t.id)["set_aside"] is None
    assert signed_in.get(f"/api/b/ours/setasides/{sa_id}").json()["next_due"] == "2027-04-10"
    assert signed_in.delete(f"/api/b/ours/setasides/match/{t.id}").status_code == 422     # nothing to undo now
    r = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": 999, "set_aside_id": sa_id})
    assert r.status_code == 404


def test_not_this_one_is_undone_by_matching_the_payment_again(oct25, signed_in, db):
    """T3: "Not this one" (DELETE /match) is the undo of a match, and the payment's Paid from puts the match back."""
    h = household(db)
    sa_id = h["proptax"].id
    t = make_txn(db, h["accounts"]["checking"], date(2026, 10, 20), -421_000, "COUNTY TAX COLLECTOR",
                 merchant="County Tax Collector", category="taxes")
    matched = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": t.id, "set_aside_id": sa_id}).json()
    assert signed_in.delete(f"/api/b/ours/setasides/match/{t.id}").status_code == 204
    assert signed_in.get(f"/api/b/ours/setasides/{sa_id}").json()["dues"] != matched["dues"]
    again = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": t.id, "set_aside_id": sa_id})
    assert again.status_code == 200 and again.json()["dues"] == matched["dues"]
    row = next(x for x in signed_in.get("/api/b/ours/transactions?category=taxes").json()["transactions"] if x["id"] == t.id)
    assert row["set_aside"] == {"id": sa_id, "name": "Property tax", "how": "hand", "archived": False}


def test_a_one_off_due_in_a_month_gone_by_this_year_is_refused_unless_an_edit_leaves_it(oct25, signed_in, db):
    """Final ruling: a one-off due before this month (Oct 2026) is refused, on add, edit and preview: a typo must not
    file a cost as neither next nor missed. An edit that leaves the year and month as they were keeps them."""
    fence = {"name": "Fence", "kind": "one_off", "amount_cents": 300_000, "due_year": 2026, "due_month": 9}
    passed = {"error": "That month has passed. Choose this month or later."}
    r = signed_in.post("/api/b/ours/setasides", json=fence)
    assert r.status_code == 422 and r.json() == passed
    r = signed_in.post("/api/b/ours/setasides/estimate", json={k: v for k, v in fence.items() if k != "name"})
    assert r.status_code == 422 and r.json() == passed
    assert signed_in.post("/api/b/ours/setasides", json={**fence, "due_month": 10}).status_code == 201      # this month is fine
    old = SetAside(name="Fence", kind="one_off", amount_cents=300_000, due_year=2026, due_month=9, first_month=date(2026, 9, 1),
                   created_at=datetime(2026, 8, 5, tzinfo=timezone.utc), updated_at=OCT_25)
    db.add(old)
    db.commit()
    url = f"/api/b/ours/setasides/{old.id}"
    assert signed_in.put(url, json={"notes": "Back yard"}).status_code == 200                              # left as it was
    assert signed_in.put(url, json={"due_year": 2026, "due_month": 9, "notes": "Gate"}).status_code == 200
    assert signed_in.post("/api/b/ours/setasides/estimate", json={"set_aside_id": old.id, "notes": "Gate"}).status_code == 200
    for body in ({"due_month": 8}, {"due_year": 2026, "due_month": 7}):
        r = signed_in.put(url, json=body)
        assert r.status_code == 422 and r.json() == passed, body
    b = signed_in.put(url, json={"due_month": 11}).json()
    assert (b["due_year"], b["due_month"]) == (2026, 11)


def test_dismiss_and_restore_take_a_bounded_payee_and_a_category(oct25, signed_in, db):
    for path in ("dismiss", "restore"):
        url = f"/api/b/ours/setasides/suggestions/{path}"
        for body, message in (({"payee_key": "X" * 201, "category": "insurance"}, "That request wasn't understood."),
                              ({"payee_key": "", "category": "insurance"}, "That request wasn't understood."),
                              ({"payee_key": "BIG MUTUAL", "category": "boats"}, "That isn't a category Spending tracks."),
                              ({"payee_key": "BIG MUTUAL", "category": 5}, "That isn't a category Spending tracks.")):
            r = signed_in.post(url, json=body)
            assert r.status_code == 422 and r.json() == {"error": message}, (path, body)
    assert events(db) == []


def test_the_preview_names_a_new_draft_itself(oct25, signed_in, db):
    """A client's "name": null is no reason to refuse a preview: the name is not part of the arithmetic."""
    r = signed_in.post("/api/b/ours/setasides/estimate", json={**{k: v for k, v in YEARLY.items() if k != "name"}, "name": None})
    assert r.status_code == 200 and r.json()["monthly_cents"] == 11_500


def test_the_estimate_route_is_arithmetic_for_viewers_too(oct25, client, db, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    r = client.post("/api/b/ours/setasides/estimate", json={"item": "car", "model_year": 2016, "miles": 118_000})
    assert r.status_code == 200 and (r.json()["planned_year"], r.json()["amount_cents"]) == (2030, 2_156_000)
    r = client.post("/api/b/ours/setasides/estimate", json={"item": "roof"})
    assert r.status_code == 422 and r.json() == {"error": "Enter the year it was installed."}
    assert db.scalars(select(EventLog)).all() == []


def test_suggestions_dismissed_and_restored(oct25, signed_in, db):
    chk = make_account(db, "Checking")
    for d in (date(2025, 5, 9), date(2026, 5, 12)):
        make_txn(db, chk, d, -138_000, "BIG MUTUAL INS", merchant="Big Mutual", category="insurance")
    assert [s["name"] for s in signed_in.get("/api/b/ours/setasides").json()["suggestions"]] == ["Big Mutual"]
    r = signed_in.post("/api/b/ours/setasides/suggestions/dismiss", json={"payee_key": "BIG MUTUAL", "category": "insurance"})
    assert r.status_code == 200 and r.json()["suggestions"] == [] and r.json()["dismissed"][0]["payee_name"] == "Big Mutual"
    assert events(db) == ["JR dismissed the Big Mutual suggestion"]
    r = signed_in.post("/api/b/ours/setasides/suggestions/restore", json={"payee_key": "BIG MUTUAL", "category": "insurance"})
    assert r.status_code == 200 and len(r.json()["suggestions"]) == 1 and r.json()["dismissed"] == []
    assert events(db)[-1] == "JR brought back the Big Mutual suggestion"
    r = signed_in.post("/api/b/ours/setasides/suggestions/restore", json={"payee_key": "BIG MUTUAL", "category": "insurance"})
    assert r.status_code == 404


def test_a_viewer_reads_but_cannot_change_anything(oct25, client, db, ddb, ours):
    h = household(db)
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    assert client.get("/api/b/ours/setasides").status_code == 200
    assert client.get(f"/api/b/ours/setasides/{h['proptax'].id}").status_code == 200
    for method, path, body in (("POST", "/api/b/ours/setasides", YEARLY), ("PUT", f"/api/b/ours/setasides/{h['proptax'].id}", YEARLY),
                               ("DELETE", f"/api/b/ours/setasides/{h['proptax'].id}", None),
                               ("POST", f"/api/b/ours/setasides/{h['proptax'].id}/skip", {"due_on": "2026-11-01"}),
                               ("POST", f"/api/b/ours/setasides/{h['heater'].id}/replace", None),
                               ("POST", "/api/b/ours/setasides/suggestions/dismiss", {"payee_key": "X", "category": "taxes"}),
                               ("POST", "/api/b/ours/setasides/match", {"transaction_id": 1, "set_aside_id": 1}),
                               ("DELETE", "/api/b/ours/setasides/match/1", None)):
        r = client.request(method, path, json=body)
        assert r.status_code == 403 and r.json() == {"error": VIEWER_COPY}, (method, path)
    assert events(db) == []


def test_parent_books_have_no_set_asides(oct25, client, margaret):
    """Review Focus 5."""
    login(client, "jr")
    for method, path in (("GET", "/api/b/margaret-ellis/setasides"), ("GET", "/api/b/margaret-ellis/setasides/1"),
                         ("POST", "/api/b/margaret-ellis/setasides"), ("PUT", "/api/b/margaret-ellis/setasides/1"),
                         ("DELETE", "/api/b/margaret-ellis/setasides/1"), ("POST", "/api/b/margaret-ellis/setasides/estimate"),
                         ("POST", "/api/b/margaret-ellis/setasides/match"), ("DELETE", "/api/b/margaret-ellis/setasides/match/1")):
        assert client.request(method, path, json=YEARLY).status_code == 404, (method, path)


def test_set_asides_need_sign_in(client):
    assert client.get("/api/b/ours/setasides").status_code == 401


def test_a_snapshot_is_stale_after_seven_days_not_on_the_seventh(oct25, signed_in, db):
    from steward.db.models import BalanceSnapshot
    h = household(db)
    snaps = list(db.scalars(select(BalanceSnapshot).where(BalanceSnapshot.account_id == h["accounts"]["house"].id)))
    for as_of, stale in ((date(2026, 10, 18), False), (date(2026, 10, 17), True)):
        for snap in snaps:
            snap.as_of = as_of
        db.commit()
        account = signed_in.get(f"/api/b/ours/setasides/{h['proptax'].id}").json()["account"]
        assert (account["as_of"], account["stale"]) == (as_of.isoformat(), stale)


def test_a_replacement_costs_what_was_paid_and_keeps_the_tag_until_year_or_amount_move(oct25, signed_in, db):
    h = household(db)
    bill = make_txn(db, h["accounts"]["checking"], date(2026, 10, 20), -235_000, "DALES PLUMBING", merchant="Dale's Plumbing", category="home")
    detail = signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": bill.id, "set_aside_id": h["heater"].id}).json()
    assert detail["replace_offer"] == {"year": 2040, "cents": 235_000, "monthly_cents": 1_382}   # 235,000 / 170 months (Nov 2026 to Dec 2040)
    assert signed_in.get(f"/api/b/ours/setasides/{h['holidays'].id}").json()["replace_offer"] is None
    new = signed_in.post(f"/api/b/ours/setasides/{h['heater'].id}/replace").json()
    assert (new["estimate"]["replacement_cents"], new["estimate"]["sale_cents"], new["is_estimate"]) == (235_000, 0, True)
    assert new["monthly_cents"] == detail["replace_offer"]["monthly_cents"]
    url = f"/api/b/ours/setasides/{new['id']}"
    assert signed_in.put(url, json={"account_id": h["accounts"]["kids"].id}).json()["is_estimate"] is True
    assert signed_in.put(url, json={"amount_cents": 240_000}).json()["is_estimate"] is False


def test_a_new_book_is_a_first_visit_until_it_has_had_one_even_a_stopped_one(oct25, signed_in, db):
    assert signed_in.get("/api/b/ours/setasides").json()["first_visit"] is True
    sa_id = signed_in.post("/api/b/ours/setasides", json=YEARLY).json()["id"]
    assert signed_in.delete(f"/api/b/ours/setasides/{sa_id}").status_code == 204
    body = signed_in.get("/api/b/ours/setasides").json()
    assert (body["count"], body["first_visit"]) == (0, False)


def test_the_estimate_route_previews_any_draft(oct25, signed_in, db):
    household(db)
    r = signed_in.post("/api/b/ours/setasides/estimate", json={k: v for k, v in YEARLY.items() if k != "name"})
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("monthly_cents", "first_month", "next_due", "months", "yearly_cents")} == {
        "monthly_cents": 11_500, "first_month": "2026-11-01", "next_due": "2027-05-12", "months": 7, "yearly_cents": 138_000}
    r = signed_in.post("/api/b/ours/setasides/estimate", json={"kind": "twice_yearly", "amount_cents": 45_000, "due_month": 1,
                                                               "due_day": 15, "second_month": 7, "second_day": 15})
    assert (r.json()["monthly_cents"], r.json()["next_due"]) == (7_500, "2027-01-15")
    r = signed_in.post("/api/b/ours/setasides/estimate", json={"kind": "one_off", "item": "water_heater", "installed_year": 2014})
    b = r.json()
    assert (b["amount_cents"], b["due_year"], b["next_due"], b["months"], b["monthly_cents"], b["is_estimate"]) == (
        225_000, 2028, "2028-12-01", 26, 8_654, True)
    r = signed_in.post("/api/b/ours/setasides/estimate", json={"kind": "one_off", "amount_cents": 250_000, "due_year": 2029, "due_month": 6,
                                                               "estimate": {"item": "water_heater", "installed_year": 2014}})
    assert (r.json()["is_estimate"], r.json()["next_due"], r.json()["planned_year"]) == (False, "2029-06-01", 2028)
    for body, message in (({"kind": "yearly", "amount_cents": 1_000, "due_month": 2, "due_day": 30}, "February has at most 29 days."),
                          ({"kind": "yearly", "amount_cents": 1_000, "due_month": 2, "due_day": 3, "due_year": 2030},
                           "Every year takes one due date: leave out the second date and the year."),
                          ({"amount_cents": 1_000}, "Choose Every year, Twice a year or Once.")):
        r = signed_in.post("/api/b/ours/setasides/estimate", json=body)
        assert r.status_code == 422 and r.json() == {"error": message}
    assert events(db) == [] and signed_in.get("/api/b/ours/setasides").json()["count"] == 7      # nothing was written


def test_a_transactions_set_aside_comes_with_the_edit_too(oct25, signed_in, db):
    h = household(db)
    t = make_txn(db, h["accounts"]["checking"], date(2026, 10, 1), -5_000, "SOMEWHERE", merchant="Somewhere", category="home")
    assert signed_in.patch(f"/api/b/ours/transactions/{t.id}", json={"category": "taxes"}).json()["set_aside"] is None
    signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": t.id, "set_aside_id": h["proptax"].id})
    assert signed_in.patch(f"/api/b/ours/transactions/{t.id}", json={"merchant": "Somewhere Else"}).json()["set_aside"] == {
        "id": h["proptax"].id, "name": "Property tax", "how": "hand", "archived": False}


def test_the_edit_preview_uses_the_real_set_aside(oct25, signed_in, client, db, ddb, ours):
    h = household(db)
    draft = {"kind": "twice_yearly", "amount_cents": 421_000, "due_month": 11, "due_day": 1, "second_month": 4, "second_day": 10}
    signed_in.post(f"/api/b/ours/setasides/{h['proptax'].id}/skip", json={"due_on": "2026-11-01"})
    new = signed_in.post("/api/b/ours/setasides/estimate", json=draft).json()
    assert (new["next_due"], new["months"], "should_cents" in new) == ("2026-11-01", 1, False)    # treated as new
    real = signed_in.post("/api/b/ours/setasides/estimate", json={**draft, "set_aside_id": h["proptax"].id}).json()
    assert (real["next_due"], real["months"], real["first_month"], real["should_cents"]) == ("2027-04-10", 6, "2026-11-01", 0)
    partial = signed_in.post("/api/b/ours/setasides/estimate", json={"set_aside_id": h["heater"].id, "amount_cents": 250_000}).json()
    assert (partial["kind"], partial["next_due"], partial["months"], partial["monthly_cents"]) == ("one_off", "2028-12-01", 26, 9_615)
    for bad_id in (999, "x"):
        r = signed_in.post("/api/b/ours/setasides/estimate", json={**draft, "set_aside_id": bad_id})
        assert r.status_code == 404 and r.json() == {"error": "No such set-aside."}
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    r = client.post("/api/b/ours/setasides/estimate", json={**draft, "set_aside_id": h["proptax"].id})
    assert r.status_code == 200 and r.json()["next_due"] == "2027-04-10"
    assert client.post("/api/b/ours/setasides/estimate", json={**draft, "set_aside_id": 999}).status_code == 404
    assert len(events(db)) == 1                                                 # only the skip


def test_a_non_string_kind_is_a_422_on_put_and_the_edit_preview(oct25, signed_in, db):
    h = household(db)
    for kind in ([], {}, 3):
        r = signed_in.put(f"/api/b/ours/setasides/{h['proptax'].id}", json={"kind": kind})
        assert r.status_code == 422 and r.json() == {"error": "Choose Every year, Twice a year or Once."}, kind
        r = signed_in.post("/api/b/ours/setasides/estimate", json={"set_aside_id": h["proptax"].id, "kind": kind})
        assert r.status_code == 422 and r.json() == {"error": "Choose Every year, Twice a year or Once."}, kind


def test_undo_refuses_a_stopped_set_aside_and_the_row_says_so(oct25, signed_in, db):
    h = household(db)
    t = make_txn(db, h["accounts"]["checking"], date(2026, 10, 1), -5_000, "SOMEWHERE", merchant="Somewhere", category="home")
    signed_in.post("/api/b/ours/setasides/match", json={"transaction_id": t.id, "set_aside_id": h["proptax"].id})
    signed_in.delete(f"/api/b/ours/setasides/{h['proptax'].id}")
    row = next(x for x in signed_in.get("/api/b/ours/transactions?category=home").json()["transactions"] if x["id"] == t.id)
    assert row["set_aside"]["archived"] is True
    r = signed_in.delete(f"/api/b/ours/setasides/match/{t.id}")
    assert r.status_code == 409 and r.json() == {"error": "That set-aside was stopped."}
    assert events(db)[-1] == "JR stopped setting aside Property tax"
    assert db.scalar(select(SetAsideMatch).where(SetAsideMatch.transaction_id == t.id)).how == "hand"


def test_a_far_one_off_has_its_schedule(oct25, signed_in, db):
    h = household(db)
    dues = signed_in.get(f"/api/b/ours/setasides/{h['roof'].id}").json()["dues"]
    assert [(d["due_on"], d["status"]) for d in dues] == [("2032-12-01", "next")]


def test_the_edit_preview_keeps_or_drops_the_estimate_tag(oct25, signed_in, db):
    h = household(db)
    url = "/api/b/ours/setasides/estimate"
    same = signed_in.post(url, json={"set_aside_id": h["heater"].id}).json()
    assert (same["is_estimate"], same["estimate"]["item"], same["estimate"]["planned_year"]) == (True, "water_heater", 2028)
    assert signed_in.post(url, json={"set_aside_id": h["heater"].id, "account_id": None}).json()["is_estimate"] is True
    assert signed_in.post(url, json={"set_aside_id": h["heater"].id, "amount_cents": 250_000}).json()["is_estimate"] is False
    assert signed_in.post(url, json={"set_aside_id": h["heater"].id, "due_year": 2029}).json()["is_estimate"] is False
    assert "estimate" not in signed_in.post(url, json={"set_aside_id": h["proptax"].id}).json()


def test_the_detail_carries_the_day_the_estimates_evidence_and_the_find_window(oct25, signed_in, db, monkeypatch):
    h = household(db)
    detail = signed_in.get(f"/api/b/ours/setasides/{h['heater'].id}").json()
    assert detail["as_of"] == "2026-10-25" and (detail["find_from"], detail["find_to"]) == (None, None)
    assert detail["estimate"]["age"] == 12                                  # installed 2014
    assert len(detail["estimate"]["sources"]) == 2 and all(detail["estimate"]["sources"])
    assert signed_in.get(f"/api/b/ours/setasides/{h['holidays'].id}").json()["estimate"] is None
    # 6 weeks past the Nov 1 installment, nothing matched: the window runs from 45 days before it to today
    monkeypatch.setattr("steward.clock.today", lambda: date(2026, 12, 14))
    pid = h["proptax"].id
    late = signed_in.get(f"/api/b/ours/setasides/{pid}").json()
    assert (late["missed_due"], late["find_from"], late["find_to"]) == ("2026-11-01", "2026-09-17", "2026-12-14")
