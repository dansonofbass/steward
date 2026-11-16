from datetime import date, datetime, timezone

from steward.advisor.state import (
    DISCLOSURE, budget_lines, changed, chat_on, gateway_state, mark_seen, money, seen, set_chat_on,
)

NOW = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)


def test_chat_is_off_until_a_manager_turns_it_on(db):
    assert chat_on(db) is False and changed(db) is None
    set_chat_on(db, True, 7, NOW)
    db.commit()
    assert chat_on(db) is True and changed(db) == (7, NOW, True)


def test_the_disclosure_is_seen_once_per_person(db):
    assert not seen(db, 3)
    mark_seen(db, 3, NOW)
    mark_seen(db, 3, NOW)
    db.commit()
    assert seen(db, 3) and not seen(db, 4)
    assert DISCLOSURE.startswith("Steward sends Claude, an AI made by Anthropic, the numbers it needs to answer you")


def test_gateway_states():
    ok = {"key_set": True, "redaction_ready": True, "chat_stopped": False}
    assert gateway_state(ok, True) == "ok"
    assert gateway_state(None, True) == "away" and gateway_state(ok, False) == "not_set_up"
    assert gateway_state({**ok, "chat_stopped": True}, True) == "stopped"
    assert gateway_state({**ok, "key_set": False}, True) == "not_set_up"
    assert gateway_state({**ok, "redaction_ready": False}, True) == "paused"


def test_budget_lines():
    assert money(1000) == "$10" and money(312) == "$3.12" and money(810) == "$8.10"
    b = {"spent_cents": 312, "cap_cents": 1000, "questions": 26, "warn": False, "can_ask": True}
    assert budget_lines(b, "Ours", date(2026, 10, 20)) == {"line": "This month: $3.12 of $10 · 26 questions",
                                                           "warn": None, "cap_line": None}
    assert budget_lines({**b, "spent_cents": 810, "warn": True}, "Ours", date(2026, 10, 20))["warn"] == \
        "$8.10 of this month's $10 is used."
    capped = budget_lines({**b, "spent_cents": 975, "warn": True, "can_ask": False}, "Ours", date(2026, 10, 20))
    assert capped["cap_line"] == ("This month's chat budget of $10 is used up. Chat starts again on Nov 1, or sooner "
                                  "if a manager of Ours raises the budget in Settings → Chat.")
    assert capped["warn"] is None
    assert budget_lines({**b, "questions": 1}, "Ours", date(2026, 12, 5))["line"].endswith("· 1 question")
