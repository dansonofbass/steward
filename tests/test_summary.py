from datetime import date, datetime, timedelta, timezone

from steward.db.models import AccountType
from steward.events import log_event
from steward.services.accounts import record_balance
from steward.services.networth import by_type_on, month_start, net_worth_on, history
from tests.factories import make_account, make_user


def login(client, db):
    make_user(db, "jr", "jr@x.com", "JR", "pw-one-two-3")
    client.post("/api/auth/login", json={"username": "jr", "password": "pw-one-two-3"})


def test_net_worth_uses_latest_on_or_before(db):
    chk = make_account(db, "Checking")
    mort = make_account(db, "Mortgage", type=AccountType.mortgage)
    record_balance(db, chk.id, date(2026, 9, 30), 10_000_00)
    record_balance(db, chk.id, date(2026, 10, 5), 12_000_00)
    record_balance(db, mort.id, date(2026, 9, 1), -400_000_00)
    db.commit()
    assert net_worth_on(db, date(2026, 10, 1)) == 10_000_00 - 400_000_00
    assert net_worth_on(db, date(2026, 10, 12)) == 12_000_00 - 400_000_00
    pts = history(db, date(2026, 10, 4), date(2026, 10, 6))
    assert [p[1] for p in pts] == [10_000_00 - 400_000_00, 12_000_00 - 400_000_00, 12_000_00 - 400_000_00]


def test_history_matches_net_worth_on_every_day(db):
    a = make_account(db, "Checking")
    late = make_account(db, "Savings", type=AccountType.savings)
    gone = make_account(db, "Closed", type=AccountType.savings)
    record_balance(db, a.id, date(2026, 10, 3), 1_000_00)
    record_balance(db, a.id, date(2026, 10, 7), 2_500_00)
    record_balance(db, late.id, date(2026, 10, 6), 9_000_00)
    record_balance(db, gone.id, date(2026, 10, 2), 40_000_00)
    record_balance(db, gone.id, date(2026, 10, 8), 41_000_00)
    gone.is_active = False
    db.commit()
    start, end = date(2026, 9, 30), date(2026, 10, 12)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    pts = history(db, start, end)
    assert pts == [(d, net_worth_on(db, d)) for d in days]
    assert [c for d, c in pts if d < date(2026, 10, 3)] == [0, 0, 0]
    assert pts[-1][1] == 2_500_00 + 9_000_00


def test_inactive_account_excluded(db):
    chk = make_account(db, "Checking")
    old = make_account(db, "Old savings", type=AccountType.savings)
    record_balance(db, chk.id, date(2026, 10, 1), 5_000_00)
    record_balance(db, old.id, date(2026, 10, 1), 7_000_00)
    old.is_active = False
    db.commit()
    assert net_worth_on(db, date(2026, 10, 12)) == 5_000_00
    assert by_type_on(db, date(2026, 10, 12)) == {"checking": 5_000_00}


def test_month_start_in_pacific_time(monkeypatch):
    # 2026-11-01 05:30 UTC is still Oct 31 in Los Angeles
    import steward.deps as deps
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc))
    assert deps.today() == date(2026, 10, 31)
    assert month_start(deps.today()) == date(2026, 10, 1)


def test_summary_endpoint(client, db, monkeypatch):
    login(client, db)
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc))
    chk = make_account(db, "Checking")
    record_balance(db, chk.id, date(2026, 9, 30), 1_000_10)
    record_balance(db, chk.id, date(2026, 10, 12), 1_000_30)
    log_event(db, "warn", "sync", "Marcus needs you to sign in again at SimpleFIN", actionable=True)
    log_event(db, "info", "system", "Started", actionable=False)
    db.commit()
    s = client.get("/api/b/ours/summary").json()
    assert s["net_worth_cents"] == 1_000_30 and s["change_month_cents"] == 20  # exact cents, no float drift
    assert s["month_start"] == "2026-10-01" and s["accounts_by_type"] == {"checking": 1_000_30}
    assert [n["message"] for n in s["needs_attention"]] == ["Marcus needs you to sign in again at SimpleFIN"]
    h = client.get("/api/b/ours/summary/history?days=3").json()["points"]
    assert len(h) == 3 and h[-1] == {"date": "2026-10-12", "net_worth_cents": 1_000_30, "investable_cents": 1_000_30}


def test_change_month_is_null_on_a_fresh_month(client, db, monkeypatch):
    login(client, db)
    monkeypatch.setattr("steward.clock.now", lambda: datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc))
    chk = make_account(db, "Checking")
    record_balance(db, chk.id, date(2026, 10, 12), 1_000_00)
    db.commit()
    s = client.get("/api/b/ours/summary").json()
    assert s["net_worth_cents"] == 1_000_00 and s["change_month_cents"] is None
