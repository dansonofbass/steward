"""The Spending routes (spec, API): household only; viewers read; managers write; plain refusals; event_log."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from steward.db.models import EventLog
from steward.deps import VIEWER_COPY
from tests.factories import login, make_account, make_person, make_txn
from tests.spending_fixtures import household

OCT_25 = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)          # noon in California
HALLOWEEN_NIGHT = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)  # 11:30 pm on October 31 in California
BODY = {"targets": [{"category": "groceries", "kind": "everyday", "monthly_cents": 125_000}]}


@pytest.fixture
def oct25(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: OCT_25)


@pytest.fixture
def halloween_night(monkeypatch):
    monkeypatch.setattr("steward.clock.now", lambda: HALLOWEEN_NIGHT)


def test_the_month_is_this_one_unless_asked(oct25, signed_in, db):
    household(db)
    r = signed_in.get("/api/b/ours/spending")
    assert r.status_code == 200
    body = r.json()
    assert (body["month"], body["day"], body["days_left"], body["head"]["spent_cents"]) == ("2026-10", 25, 6, 514_799)
    sep = signed_in.get("/api/b/ours/spending?month=2026-09").json()
    assert (sep["month"], sep["current"], sep["day"]) == ("2026-09", False, None)


def test_a_month_that_cant_be_shown_is_refused(oct25, signed_in, db):
    for bad in ("2026-13", "2026-1", "abc", "2026-11", "1999-12", "2026-00", "２０２６-10", "2026-10\n"):
        r = signed_in.get("/api/b/ours/spending", params={"month": bad})
        assert r.status_code == 422 and r.json() == {"error": "Choose a month like 2026-10: this month or an earlier one."}


def test_a_month_before_the_books_history_is_not_found(oct25, signed_in, db):
    """Ruling 22: history starts in April, so March answers 404 in plain words; every month shown carries earliest."""
    household(db)
    r = signed_in.get("/api/b/ours/spending?month=2026-03")
    assert r.status_code == 404 and r.json() == {"error": "Spending has nothing to show before April 2026."}
    assert signed_in.get("/api/b/ours/spending?month=2026-04").json()["earliest"] == "2026-04"
    assert signed_in.get("/api/b/ours/spending").json()["earliest"] == "2026-04"


def test_the_month_reads_the_books_first_month_once(oct25, signed_in, db, monkeypatch):
    """The refusal check and the answer's earliest share one read, for a book with history and one without."""
    from steward.services import spending as svc
    calls = []
    real = svc.earliest_month
    monkeypatch.setattr(svc, "earliest_month", lambda d: calls.append(1) or real(d))
    assert signed_in.get("/api/b/ours/spending").json()["earliest"] is None and len(calls) == 1
    household(db)
    assert signed_in.get("/api/b/ours/spending?month=2026-09").json()["earliest"] == "2026-04" and len(calls) == 2


def test_a_book_with_no_history_shows_only_this_month(oct25, signed_in, db):
    body = signed_in.get("/api/b/ours/spending").json()
    assert (body["month"], body["earliest"]) == ("2026-10", None)
    r = signed_in.get("/api/b/ours/spending?month=2026-09")
    assert r.status_code == 404 and r.json() == {"error": "Spending has nothing to show before October 2026."}


def test_rows_dated_after_today_never_refuse_this_month(oct25, signed_in, db):
    make_txn(db, make_account(db, "Checking"), date(2026, 11, 1), -5_000, "EARLY", category="dining")
    db.commit()
    r = signed_in.get("/api/b/ours/spending")
    assert r.status_code == 200 and r.json()["month"] == "2026-10"


def test_late_on_the_last_evening_it_is_still_the_households_last_day(halloween_night, signed_in, db):
    body = signed_in.get("/api/b/ours/spending").json()
    assert (body["month"], body["as_of"], body["day"], body["days"], body["days_left"]) == (
        "2026-10", "2026-10-31", 31, 31, 0)


def test_over_time_answers_six_or_twelve_months(oct25, signed_in, db):
    household(db)
    assert len(signed_in.get("/api/b/ours/spending/trends").json()["months"]) == 12
    assert len(signed_in.get("/api/b/ours/spending/trends?months=6").json()["months"]) == 6
    for bad in ("7", "0", "abc"):
        r = signed_in.get(f"/api/b/ours/spending/trends?months={bad}")
        assert r.status_code == 422 and r.json() == {"error": "Choose 6 or 12 months."}


def test_homes_strip_reads_spendings_months(oct25, signed_in, db):
    household(db)
    body = signed_in.get("/api/b/ours/spending/flow").json()
    assert body["as_of"] == "2026-10-25" and len(body["months"]) == 12
    month = signed_in.get("/api/b/ours/spending").json()["head"]
    assert body["months"][-1] == {"month": "2026-10", "in_cents": month["money_in_cents"],
                                  "out_cents": month["money_out_cents"],
                                  "net_cents": month["money_in_cents"] - month["money_out_cents"]}
    assert [m["month"] for m in signed_in.get("/api/b/ours/spending/flow?months=3").json()["months"]] == [
        "2026-08", "2026-09", "2026-10"]
    for bad in ("0", "25", "abc", "-1", "１２"):
        r = signed_in.get(f"/api/b/ours/spending/flow?months={bad}")
        assert r.status_code == 422 and r.json() == {"error": "Choose between 1 and 24 months."}


def test_a_manager_changes_a_target_and_the_event_log_says_who(oct25, signed_in, db):
    household(db)
    r = signed_in.put("/api/b/ours/spending/targets", json=BODY)
    assert r.status_code == 200
    body = r.json()
    groceries = next(c for c in body["categories"] if c["category"] == "groceries")
    assert groceries["monthly_cents"] == 125_000
    assert (body["updated_by"], body["updated_at"], body["has_targets"]) == ("JR", OCT_25.isoformat(), True)
    assert "updated_by_id" not in body
    messages = [e.message for e in db.scalars(select(EventLog).where(EventLog.kind == "spending"))]
    assert messages == ["JR changed Spending: Groceries $1,300 → $1,250."]
    assert signed_in.get("/api/b/ours/spending/targets").json()["updated_by"] == "JR"


def test_a_bad_body_is_refused_in_plain_words(oct25, signed_in, db):
    cases = [({"targets": "x"}, "That request wasn't understood."),
             ({**BODY, "targets": [{"category": "income", "kind": "everyday"}]}, "That isn't a category Spending tracks."),
             ({**BODY, "targets": [{"category": "dining", "kind": "everyday", "monthly_cents": -5}]},
              "Enter a target from $0 to $1,000,000, or leave it blank.")]
    for body, message in cases:
        r = signed_in.put("/api/b/ours/spending/targets", json=body)
        assert r.status_code == 422 and r.json() == {"error": message}
    assert db.scalars(select(EventLog).where(EventLog.kind == "spending")).all() == []


def test_a_viewer_reads_but_cannot_change_targets(oct25, client, db, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    household(db)
    login(client, "vee")
    for path in ("/api/b/ours/spending", "/api/b/ours/spending/trends", "/api/b/ours/spending/targets",
                 "/api/b/ours/spending/flow"):
        assert client.get(path).status_code == 200
    r = client.put("/api/b/ours/spending/targets", json=BODY)
    assert r.status_code == 403 and r.json() == {"error": VIEWER_COPY}


def test_parent_books_have_no_spending(oct25, client, margaret):
    login(client, "jr")
    for path in ("/api/b/margaret-ellis/spending", "/api/b/margaret-ellis/spending/trends",
                 "/api/b/margaret-ellis/spending/targets", "/api/b/margaret-ellis/spending/flow"):
        assert client.get(path).status_code == 404
    assert client.put("/api/b/margaret-ellis/spending/targets", json=BODY).status_code == 404


def test_a_viewer_is_refused_before_the_body_is_read(oct25, client, db, ddb, ours):
    make_person(ddb, "vee", [(ours.id, "viewer")])
    login(client, "vee")
    r = client.put("/api/b/ours/spending/targets", content="junk", headers={"content-type": "text/plain"})
    assert r.status_code == 403 and r.json() == {"error": VIEWER_COPY}


def test_a_parent_book_is_refused_before_the_body_is_read(oct25, client, margaret):
    login(client, "jr")
    r = client.put("/api/b/margaret-ellis/spending/targets", content="junk", headers={"content-type": "text/plain"})
    assert r.status_code == 404


def test_a_book_someone_isnt_in_answers_as_one_that_doesnt_exist(oct25, client, margaret):
    login(client, "vee")      # views Margaret's book only
    for method in ("get", "put"):
        theirs = client.request(method.upper(), "/api/b/ours/spending/targets", json=BODY)
        none = client.request(method.upper(), "/api/b/no-such-book/spending/targets", json=BODY)
        assert theirs.status_code == none.status_code == 404 and theirs.json() == none.json()


def test_spending_needs_sign_in(client):
    assert client.get("/api/b/ours/spending").status_code == 401


def test_the_month_with_set_asides_and_a_matched_payment_reads_under_the_get_guard(oct25, signed_in, db):
    from steward.db.models import BalanceSnapshot, SetAside
    from steward.services import setasides as sas
    from tests.setaside_fixtures import AT
    h = household(db)
    house = make_account(db, "House fund", type="savings")
    db.add(BalanceSnapshot(account_id=house.id, as_of=date(2026, 10, 24), balance_cents=100_000))
    row = SetAside(name="Property tax", kind="twice_yearly", amount_cents=421_000, due_month=11, due_day=1, second_month=4, second_day=10,
                   first_month=date(2026, 11, 1), account_id=house.id, payee_key="COUNTY TAX COLLECTOR", category="taxes",
                   created_at=AT, updated_at=AT)
    db.add(row); db.commit()
    sas.match_set_aside(db, row, date(2026, 10, 25))
    db.commit()
    r = signed_in.get("/api/b/ours/spending")
    assert r.status_code == 200
    s = r.json()["set_aside"]
    assert (s["count"], s["monthly_cents"], [p["name"] for p in s["paid"]]) == (1, 70_167, ["Property tax"])
    assert h["checking"].id
