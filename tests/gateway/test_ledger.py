import threading
from datetime import datetime, timezone

import pytest

from steward_gateway.config import GatewayConfig
from steward_gateway.ledger import CapReached, Ledger
from tests.waiting import CEILING

NOW = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)
DOLLAR = 1_000_000_000


def make(tmp_path, cap_cents=1000) -> Ledger:
    return Ledger(tmp_path / "ledger.db", "America/Los_Angeles", cap_cents, 10_000, "claude-opus-5-5")


def reserve(led, amount, turn="t_0000000000000001", now=NOW, book=1, user=2):
    return led.reserve(now=now, book_id=book, user_id=user, turn_id=turn, channel="chat", model="claude-opus-5-5",
                       estimate_nd=amount)


def test_reserve_settle_and_release(tmp_path):
    led = make(tmp_path)
    rid = reserve(led, 4 * DOLLAR)
    reserve(led, 4 * DOLLAR)
    with pytest.raises(CapReached):
        reserve(led, 3 * DOLLAR)                 # 8 reserved + 3 would pass $10
    led.settle(rid, DOLLAR // 10)                # the first cost $0.10
    reserve(led, 3 * DOLLAR)                     # now 0.10 + 4 + 3 fits
    st = led.state(NOW, GatewayConfig(tmp_path, tmp_path))
    assert st["spent_cents"] == 10 and st["cap_cents"] == 1000 and st["reserved_cents"] == 700


def test_concurrent_reservations_never_pass_the_cap(tmp_path):
    led = make(tmp_path, cap_cents=100)          # $1
    won, lost = [], []

    def go(i):
        try:
            won.append(reserve(led, 300_000_000, turn=f"t_{i:016x}"))
        except CapReached:
            lost.append(i)
    threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(CEILING)
    assert not any(t.is_alive() for t in threads)
    assert len(won) == 3 and len(lost) == 17


def test_reservations_left_by_a_crash_count_in_full(tmp_path):
    led = make(tmp_path)
    reserve(led, 2 * DOLLAR)
    again = make(tmp_path)                       # a new process after a crash
    assert again.settle_stale() == 1
    assert again.state(NOW, GatewayConfig(tmp_path, tmp_path))["spent_cents"] == 200


def test_the_month_is_pacific(tmp_path):
    led = make(tmp_path)
    assert led.month(datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)) == "2026-10"   # 11:30 PM Oct 31 PDT
    assert led.month(datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)) == "2026-11"


def test_last_months_spending_doesnt_count(tmp_path):
    led = make(tmp_path)
    rid = reserve(led, 9 * DOLLAR, now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
    led.settle(rid, 9 * DOLLAR)
    reserve(led, 9 * DOLLAR)


def test_the_cap_setting(tmp_path):
    led = make(tmp_path)
    assert led.cap_cents() == 1000
    led.set_cap_cents(2500)
    assert make(tmp_path).cap_cents() == 2500
    for bad in (99, 10_001):
        with pytest.raises(ValueError, match=r"from \$1 to \$100"):
            led.set_cap_cents(bad)
    led.set_model("claude-sonnet-5-5")
    assert led.model() == "claude-sonnet-5-5"
    with pytest.raises(ValueError):
        led.set_model("claude-haiku-5-5")


def test_warning_at_80_percent_and_a_stop_when_a_request_wont_fit(tmp_path):
    cfg = GatewayConfig(tmp_path, tmp_path)
    led = make(tmp_path)
    led.settle(reserve(led, 7 * DOLLAR), 7 * DOLLAR)
    assert led.state(NOW, cfg)["warn"] is False
    led.settle(reserve(led, DOLLAR + DOLLAR // 10), DOLLAR + DOLLAR // 10)
    st = led.state(NOW, cfg)
    assert st["warn"] is True and st["can_ask"] is True
    led.settle(reserve(led, 1_600_000_000), 1_600_000_000)     # $9.70 spent: a worst-case request won't fit
    assert led.state(NOW, cfg)["can_ask"] is False


def test_usage_by_month_book_and_person(tmp_path):
    led = make(tmp_path)
    led.settle(reserve(led, DOLLAR, turn="t_0000000000000001", book=1, user=2), DOLLAR // 10)
    led.settle(reserve(led, DOLLAR, turn="t_0000000000000001", book=1, user=2), DOLLAR // 10)
    led.settle(reserve(led, DOLLAR, turn="t_0000000000000002", book=3, user=4), DOLLAR // 5)
    u = led.usage(NOW)
    assert u["month"] == "2026-10" and u["months"][-1] == {"month": "2026-10", "spent_cents": 40, "questions": 2}
    assert len(u["months"]) == 12 and u["months"][0]["month"] == "2025-11"
    assert {(b["book_id"], b["spent_cents"], b["questions"]) for b in u["by_book"]} == {(1, 20, 1), (3, 20, 1)}
    assert {(p["book_id"], p["user_id"]) for p in u["by_person"]} == {(1, 2), (3, 4)}


def test_the_sent_list_has_no_content(tmp_path):
    led = make(tmp_path)
    led.record_sent(NOW, [("a" * 64, 120), ("b" * 64, 4000)], 1, "chat")
    rows = led.sent_since(datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert [(r["sha256"], r["bytes"], r["book_id"], r["channel"]) for r in rows] == [
        ("a" * 64, 120, 1, "chat"), ("b" * 64, 4000, 1, "chat")]
    assert set(rows[0]) == {"at", "sha256", "bytes", "book_id", "channel"}
