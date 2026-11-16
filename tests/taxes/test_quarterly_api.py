"""The quarterly routes (spec 7.1): household only; viewers read; writes checked; plain refusals."""
from datetime import date

from tests.factories import login, make_account, make_txn
from tests.taxes.helpers import household


def test_quarterly_needs_set_up_then_answers(frozen, signed_in, db):
    r = signed_in.get("/api/b/ours/taxes/quarterly").json()
    assert r == {"available": False, "reason": "Add both birth dates, your state and how you file taxes in Set up first."}
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    r = signed_in.get("/api/b/ours/taxes/quarterly").json()
    assert r["available"] is True and r["year"] == 2026 and r["prior_year"] == 2025
    assert [a["label"] for a in r["agencies"]] == ["Federal (IRS)", "California (FTB)"]
    fed = r["agencies"][0]
    assert [d["due"] for d in fed["dues"]] == ["2026-04-15", "2026-06-15", "2026-09-15", "2027-01-15"]
    assert [d["status"] for d in fed["dues"]] == ["short", "short", "short", "upcoming"]
    assert r["agencies"][1]["dues"][2]["installment_cents"] == 0
    assert r["next"]["due"] == "2027-01-15" and r["next"]["due_label"] == "January 15, 2027"
    assert r["notice"] is None                                         # October 13 is outside the window
    assert r["email_on"] is False and r["never"] == "Steward never pays or files anything."
    assert r["rules_note"] == "2026 federal and 2025 California rules"


def test_return_withholding_and_payment_writes(frozen, signed_in, db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000, salary="16500000")
    r = signed_in.put("/api/b/ours/taxes/return/2025", json={"federal_tax_cents": 400_000, "federal_agi_cents": 6_000_000,
                                                             "state_tax_cents": None, "state_agi_cents": None}).json()
    assert r["prior"] == {"federal_tax_cents": 400_000, "federal_agi_cents": 6_000_000, "state_tax_cents": None,
                          "state_agi_cents": None}
    assert r["agencies"][0]["method"] == "prior_year"
    bad = signed_in.put("/api/b/ours/taxes/return/2025", json={"federal_tax_cents": -5})
    assert bad.status_code == 422 and bad.json() == {"error": "Enter amounts from $0 to $100,000,000, or leave them blank."}
    assert signed_in.put("/api/b/ours/taxes/return/2019", json={}).status_code == 422
    assert r["needs_withholding"] is True
    r = signed_in.put("/api/b/ours/taxes/withholding/2026",
                      json={"federal_ytd_cents": 1_500_000, "state_ytd_cents": 600_000, "as_of": "2026-09-30"}).json()
    assert r["needs_withholding"] is False and r["withholding"]["as_of"] == "2026-09-30"
    assert signed_in.put("/api/b/ours/taxes/withholding/2026",
                         json={"federal_ytd_cents": 1, "state_ytd_cents": 1, "as_of": "2026-11-01"}).status_code == 422


def test_marking_a_payment_changes_what_is_still_due(frozen, signed_in, db):
    household(db, profit_cents=4_000_000, low=2_000_000, high=6_000_000)
    t = make_txn(db, make_account(db, "Checking"), date(2026, 4, 14), -100_000, "IRS USATAXPYMT")
    before = signed_in.get("/api/b/ours/taxes/quarterly").json()
    assert before["payments"][0]["counts"] is True and before["agencies"][0]["paid_cents"] == 100_000
    after = signed_in.put(f"/api/b/ours/taxes/payments/{t.id}", json={"counts": False}).json()
    assert after["payments"][0]["counts"] is False and after["agencies"][0]["paid_cents"] == 0
    assert after["next"]["federal_cents"] == before["next"]["federal_cents"] + 100_000
    assert signed_in.put("/api/b/ours/taxes/payments/99999", json={"counts": False}).status_code == 404
    assert signed_in.put(f"/api/b/ours/taxes/payments/{t.id}", json={"counts": "no"}).status_code == 422


def test_early_january_shows_last_years_fourth_payment(client, db, ddb, monkeypatch):
    from datetime import datetime, timezone

    from sqlalchemy import update

    from steward.db.directory_models import Session as LoginSession
    from tests.factories import make_user
    make_user(db)
    assert client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"}).status_code == 200
    # sign in on the real clock, then keep the session alive into January (its 30 days would have run out)
    ddb.execute(update(LoginSession).values(expires_at=datetime(2027, 3, 1, tzinfo=timezone.utc)))
    ddb.commit()
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2027, 1, 6, 19, 0, tzinfo=timezone.utc))
    household(db, profit_cents=15_000_000)
    r = client.get("/api/b/ours/taxes/quarterly").json()
    assert r["year"] == 2026 and r["next"]["due"] == "2027-01-15"
    n = client.get("/api/b/ours/taxes/notice").json()["notice"]
    assert n["due"] == "2027-01-15" and n["line"].startswith("Quarterly taxes due January 15: $")


def test_parent_books_have_no_taxes(frozen, client, margaret):
    login(client, "jr")
    assert client.get("/api/b/margaret-ellis/taxes/quarterly").status_code == 404
    assert client.get("/api/b/margaret-ellis/taxes/notice").status_code == 404


def test_a_viewer_reads_but_cannot_write(frozen, client, db, books, ddb, ours):
    from tests.factories import make_person
    make_person(ddb, "vee", [(ours.id, "viewer")])
    household(db, profit_cents=4_000_000)
    login(client, "vee")
    assert client.get("/api/b/ours/taxes/quarterly").json()["available"] is True
    assert client.put("/api/b/ours/taxes/return/2025", json={}).status_code == 403
