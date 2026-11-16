"""Chat on or off per book, the disclosure, and the plain lines Settings → Chat and the turn show (spec 5.4, 9.2,
9.3, 10)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from steward import gateway_name
from steward.books.sample_guard import SAMPLE_REFUSED, SampleRefused, is_sample
from steward.db.models import AdvisorState, ChatSeen
from steward_boundary.protocol import LINES

CHAT_ON = "chat_on"
OFF_LINE = "Chat is off for this book. A manager can turn it on in Settings → Chat."
# What the tools send Claude. docs/explanations/privacy.md and the README list the same (tests/test_privacy_docs.py).
SENT_TO_CLAUDE = ("balances", "income", "spending totals", "holdings", "debts", "ages", "your state", "tax facts")
# Says what the checks do, not more (0.1.0 gate, PRIV-2, PRIV-3, PRIV-9, TRI-2): the exact pass replaces what Steward
# holds, the gateway's model looks for the rest and can miss one, an approved payee can be a person, and approved rows
# stay in the conversation. tests/test_doc_words.py keeps the phrases the gate found false out of it.
DISCLOSURE = ("Steward sends Claude, an AI made by Anthropic, the numbers it needs to answer you: "
              f"{', '.join(SENT_TO_CLAUDE[:-1])} and {SENT_TO_CLAUDE[-1]}. It replaces the names, account numbers, "
              "addresses, emails and birth dates it holds, and your gateway looks for others but can miss one. Store "
              "and payee names, which can be a person's, are sent only in rows a manager approves, and those rows stay "
              "in that conversation. Every part of your data that is sent is kept in this book's log, which every "
              "member can read. Your conversations are listed only for you.")
GATEWAY_LINES = {"ok": "{gateway} is answering.", "away": LINES["away"], "not_set_up": LINES["not_set_up"],
                 "paused": LINES["privacy_not_ready"], "stopped": LINES["stopped_by_gateway"]}


def gateway_line(state: str) -> str:
    return gateway_name.fill(GATEWAY_LINES[state])


def chat_on(db: Session) -> bool:
    if is_sample(db.get_bind()):
        return False
    row = db.get(AdvisorState, CHAT_ON)
    return row is not None and row.value == "1"


def set_chat_on(db: Session, on: bool, user_id: int, now: datetime) -> None:
    if is_sample(db.get_bind()):
        raise SampleRefused(SAMPLE_REFUSED)
    row = db.get(AdvisorState, CHAT_ON) or AdvisorState(key=CHAT_ON)
    row.value, row.updated_at, row.updated_by = ("1" if on else "0"), now, user_id
    db.add(row)
    db.flush()


def changed(db: Session) -> tuple[int | None, datetime, bool] | None:
    row = db.get(AdvisorState, CHAT_ON)
    return None if row is None else (row.updated_by, row.updated_at, row.value == "1")


def seen(db: Session, user_id: int) -> bool:
    return db.get(ChatSeen, user_id) is not None


def mark_seen(db: Session, user_id: int, now: datetime) -> None:
    if db.get(ChatSeen, user_id) is None:
        db.add(ChatSeen(user_id=user_id, seen_at=now))
        db.flush()


def gateway_state(health: dict | None, configured: bool) -> str:
    if not configured:
        return "not_set_up"
    if health is None:
        return "away"
    if health.get("chat_stopped"):
        return "stopped"
    if not health.get("key_set"):
        return "not_set_up"
    if not health.get("redaction_ready"):
        return "paused"
    return "ok"


def money(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents // 100:,}.{cents % 100:02d}"


def budget_lines(budget: dict, household_name: str, today: date) -> dict:
    spent, cap, q = budget["spent_cents"], budget["cap_cents"], budget["questions"]
    line = f"This month: {money(spent)} of {money(cap)} · {q} question{'' if q == 1 else 's'}"
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    cap_line = None if budget.get("can_ask", True) else (
        f"This month's chat budget of {money(cap)} is used up. Chat starts again on {nxt:%b} {nxt.day}, or sooner "
        f"if a manager of {household_name} raises the budget in Settings → Chat.")
    warn = f"{money(spent)} of this month's {money(cap)} is used." if budget.get("warn") and not cap_line else None
    return {"line": line, "warn": warn, "cap_line": cap_line}
